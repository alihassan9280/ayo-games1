"""AYO Easypaisa Payment Gateway v2.

Receives Easypaisa "Received" notifications from the AYO Payment Helper Android app,
lets customers verify payments on a "Pay now" page, credits Discord users via the AYO bot,
and keeps full records (payments, orders, devices, audit log) with an admin dashboard.

Run (Windows):  start.bat          Run (any OS):  python app.py
Settings come from environment variables or a `.env` file next to this script.
"""
import csv
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import sqlite3
import threading
import time
import urllib.request
import uuid
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from flask import Flask, Response, g, jsonify, request

HERE = os.path.dirname(os.path.abspath(__file__))


def load_env(path=os.path.join(HERE, ".env")):
    """Minimal .env loader (KEY=VALUE lines); real env vars win."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_env()

# ---------------------------------------------------------------- constants
FORMAT = re.compile(
    r"^Trx ID (\d{6,30})\. You have Received Rs "
    r"((?:\d+|\d{1,3}(?:,\d{3})+)\.\d{2}) from (.+?) "
    r"with Easypaisa Account (92[\d*]+)\.?$")
MAX_PAISA = 100_000_000
MAX_AGE = timedelta(days=7)
FUTURE_SKEW = timedelta(minutes=5)
ORDER_TTL = timedelta(minutes=int(os.getenv("ORDER_TTL_MIN", "30")))
LOOKBACK = timedelta(minutes=int(os.getenv("VERIFY_LOOKBACK_MIN", "30")))
TZ = timezone(timedelta(hours=float(os.getenv("TZ_OFFSET_HOURS", "5"))))   # PKT for reports
OFFLINE_AFTER = timedelta(minutes=int(os.getenv("DEVICE_OFFLINE_MIN", "20")))

SCHEMA = """
CREATE TABLE IF NOT EXISTS devices(
  id TEXT PRIMARY KEY, name TEXT NOT NULL, token_hash TEXT NOT NULL,
  created TEXT NOT NULL, revoked INTEGER NOT NULL DEFAULT 0, last_seen TEXT,
  offline_alerted INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS orders(
  id TEXT PRIMARY KEY, amount INTEGER NOT NULL, note TEXT NOT NULL DEFAULT '',
  source TEXT NOT NULL DEFAULT 'web', discord_user_id TEXT,
  status TEXT NOT NULL DEFAULT 'open', created TEXT NOT NULL, expires TEXT NOT NULL,
  payment_tid TEXT, paid_at TEXT, approved_by TEXT,
  credited INTEGER NOT NULL DEFAULT 0, credited_at TEXT);
CREATE TABLE IF NOT EXISTS payments(
  tid TEXT PRIMARY KEY, amount INTEGER NOT NULL, sender TEXT NOT NULL,
  account TEXT NOT NULL, text TEXT NOT NULL, observed_at TEXT NOT NULL,
  received_at TEXT NOT NULL, device_id TEXT NOT NULL, order_id TEXT,
  status TEXT NOT NULL DEFAULT 'unmatched', note TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS audit(
  id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, actor TEXT NOT NULL,
  action TEXT NOT NULL, ref TEXT NOT NULL DEFAULT '', detail TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS ix_pay_received ON payments(received_at);
CREATE INDEX IF NOT EXISTS ix_ord_status ON orders(status, credited);
"""


# ---------------------------------------------------------------- helpers
def now():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_iso(s):
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timezone required")
    return dt.astimezone(timezone.utc)


def rs(paisa):
    return f"{paisa / 100:.2f}"


def to_paisa(value):
    try:
        d = Decimal(str(value).strip())
        if d != d.quantize(Decimal("0.01")):
            return None
        return int(d * 100)
    except (InvalidOperation, ValueError, TypeError):
        return None


def parse_payment(text):
    """Re-parse server side; never trust the phone's parsing."""
    if not isinstance(text, str) or len(text) > 2000:
        return None
    t = re.sub(r"\s+", " ", text.strip())
    m = FORMAT.match(t)
    if not m or len(m.group(4)) != 12:
        return None
    paisa = to_paisa(m.group(2).replace(",", ""))
    if paisa is None or not 1 <= paisa <= MAX_PAISA:
        return None
    return {"tid": m.group(1), "amount": paisa, "sender": m.group(3),
            "account": m.group(4), "text": t}


def norm_number(raw):
    """03004123413 / +92 300 4123413 / 923004123413 -> '923004123413' (or None)."""
    d = re.sub(r"\D", "", str(raw or ""))
    if d.startswith("0092"):
        d = d[2:]
    if d.startswith("0"):
        d = "92" + d[1:]
    return d if re.fullmatch(r"92\d{10}", d) else None


def mask_matches(masked, number):
    return len(masked) == len(number) and all(m in ("*", n) for m, n in zip(masked, number))


def notify(text):
    """Fire-and-forget message to a Discord channel webhook (optional)."""
    url = os.getenv("DISCORD_WEBHOOK_URL", "")
    if not url:
        return

    def send():
        try:
            req = urllib.request.Request(url, data=json.dumps({"content": text[:1900]}).encode(),
                                         headers={"Content-Type": "application/json",
                                                  "User-Agent": "ayo-gateway"})
            urllib.request.urlopen(req, timeout=10).close()
        except Exception as e:   # never break payments because Discord is down
            print("webhook failed:", e)
    threading.Thread(target=send, daemon=True).start()


# ---------------------------------------------------------------- app
def create_app(db_path=None, admin_key=None, auto_approve=None, bot_key=None, start_watcher=True):
    app = Flask(__name__)
    app.config["DB"] = db_path or os.getenv("DB_PATH", os.path.join(HERE, "data", "gateway.sqlite3"))
    os.makedirs(os.path.dirname(os.path.abspath(app.config["DB"])), exist_ok=True)
    app.config["ADMIN_KEY"] = admin_key if admin_key is not None else os.getenv("ADMIN_KEY", "")
    app.config["BOT_KEY"] = bot_key if bot_key is not None else os.getenv("BOT_KEY", "")
    app.config["AUTO_APPROVE"] = (os.getenv("AUTO_APPROVE", "0") == "1") if auto_approve is None else auto_approve
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024
    hits = defaultdict(deque)
    hits_lock = threading.Lock()

    def connect():
        c = sqlite3.connect(app.config["DB"], timeout=10, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        return c

    def db():
        if "db" not in g:
            g.db = connect()
        return g.db

    @app.teardown_appcontext
    def close(_):
        d = g.pop("db", None)
        if d:
            d.close()

    with connect() as c:
        c.executescript(SCHEMA)
        seed_id, seed_tok = os.getenv("DEVICE_ID", ""), os.getenv("DEVICE_TOKEN", "")
        if seed_id and seed_tok:
            if not (re.fullmatch(r"[0-9a-fA-F-]{36}", seed_id) and re.fullmatch(r"[0-9a-f]{64}", seed_tok)):
                raise SystemExit("DEVICE_ID must be a UUID and DEVICE_TOKEN 64 lowercase hex chars")
            c.execute("INSERT OR IGNORE INTO devices(id,name,token_hash,created) VALUES(?,?,?,?)",
                      (seed_id, "seeded-device", hashlib.sha256(seed_tok.encode()).hexdigest(), iso(now())))

    # ------------------------------------------------------------ plumbing
    def err(code, msg):
        return jsonify({"error": msg}), code

    def client_ip():
        fwd = request.headers.get("CF-Connecting-IP") or request.headers.get("X-Forwarded-For", "")
        return fwd.split(",")[0].strip() or request.remote_addr or ""

    def limited(key, limit=60, window=60):
        t = time.monotonic()
        with hits_lock:
            q = hits[key]
            while q and q[0] < t - window:
                q.popleft()
            if len(q) >= limit:
                return True
            q.append(t)
        return False

    def key_ok(header, configured):
        got = request.headers.get(header, "")
        return bool(configured) and hmac.compare_digest(got.encode(), configured.encode())

    def is_admin():
        if limited("admin:" + client_ip(), limit=120):
            return False
        return key_ok("X-Admin-Key", app.config["ADMIN_KEY"])

    def is_bot():
        return key_ok("X-Bot-Key", app.config["BOT_KEY"])

    def audit(actor, action, ref="", detail=""):
        db().execute("INSERT INTO audit(at,actor,action,ref,detail) VALUES(?,?,?,?,?)",
                     (iso(now()), actor, action, ref, detail if isinstance(detail, str) else json.dumps(detail)))

    def device_auth():
        dev_id = request.headers.get("X-Device-ID", "")
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer ") or not dev_id:
            return None, err(401, "missing credentials")
        row = db().execute("SELECT * FROM devices WHERE id=?", (dev_id,)).fetchone()
        token_hash = hashlib.sha256(auth[7:].strip().encode()).hexdigest()
        stored = row["token_hash"] if row else "0" * 64
        if not hmac.compare_digest(token_hash, stored) or not row:
            return None, err(401, "invalid credentials")
        if row["revoked"]:
            return None, err(403, "device revoked")
        if limited("dev:" + dev_id):
            return None, err(429, "rate limited")
        if row["offline_alerted"]:
            notify(f"🟢 Payment phone **{row['name']}** is back online.")
        db().execute("UPDATE devices SET last_seen=?, offline_alerted=0 WHERE id=?", (iso(now()), dev_id))
        return row, None

    def expire_orders():
        db().execute("UPDATE orders SET status='expired' WHERE status='open' AND expires<?", (iso(now()),))

    def claim(order_id, tid, actor):
        """Atomically bind an unclaimed payment to an open order."""
        c = db()
        c.execute("BEGIN IMMEDIATE")
        try:
            p = c.execute("UPDATE payments SET order_id=?, status='matched' "
                          "WHERE tid=? AND order_id IS NULL AND status!='rejected'",
                          (order_id, tid)).rowcount
            o = c.execute("UPDATE orders SET status='paid', payment_tid=?, paid_at=?, approved_by=? "
                          "WHERE id=? AND status IN ('open','expired')",
                          (tid, iso(now()), actor, order_id)).rowcount
            if p == 1 and o == 1:
                c.execute("INSERT INTO audit(at,actor,action,ref,detail) VALUES(?,?,?,?,?)",
                          (iso(now()), actor, "order.paid", order_id, "tid=" + tid))
                c.execute("COMMIT")
                o = c.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
                who = f" for <@{o['discord_user_id']}>" if o["discord_user_id"] else ""
                notify(f"✅ Payment approved: Rs {rs(o['amount'])}{who} · order `{order_id}` · Trx `{tid}` · by {actor}")
                return True
            c.execute("ROLLBACK")
        except Exception:
            c.execute("ROLLBACK")
            raise
        return False

    def new_order(paisa, source, note="", discord_user_id=None):
        oid, t = secrets.token_urlsafe(9), now()
        db().execute("INSERT INTO orders(id,amount,note,source,discord_user_id,created,expires) "
                     "VALUES(?,?,?,?,?,?,?)",
                     (oid, paisa, note[:200], source, discord_user_id, iso(t), iso(t + ORDER_TTL)))
        base = os.getenv("PUBLIC_URL", "").rstrip("/") or request.host_url.rstrip("/")
        return {"id": oid, "amount": rs(paisa), "expires": iso(t + ORDER_TTL),
                "pay_url": f"{base}/?order={oid}"}

    def order_json(o):
        d = dict(o)
        d["amount"] = rs(o["amount"])
        return d

    # ------------------------------------------------------------ device (phone app)
    @app.post("/v1/device/heartbeat")
    def heartbeat():
        _, e = device_auth()
        return e or jsonify({"ok": True, "server_time": iso(now())})

    @app.post("/v1/device/payments")
    def ingest():
        dev, e = device_auth()
        if e:
            return e
        body = request.get_json(silent=True) or {}
        p = parse_payment(body.get("notification_text"))
        if not p:
            audit("device:" + dev["id"][:8], "payment.unrecognized", "", str(body.get("notification_text", ""))[:300])
            return err(422, "unrecognized payment text")
        try:
            observed = parse_iso(str(body.get("observed_at", "")))
        except ValueError:
            return err(400, "bad observed_at")
        if observed > now() + FUTURE_SKEW or observed < now() - MAX_AGE:
            return err(400, "observed_at outside allowed window; check phone clock")
        c = db()
        try:
            c.execute("INSERT INTO payments(tid,amount,sender,account,text,observed_at,received_at,device_id) "
                      "VALUES(?,?,?,?,?,?,?,?)",
                      (p["tid"], p["amount"], p["sender"], p["account"], p["text"],
                       iso(observed), iso(now()), dev["id"]))
            duplicate = False
            audit("device:" + dev["id"][:8], "payment.received", p["tid"], f"Rs {rs(p['amount'])} from {p['sender']}")
            notify(f"💰 Received Rs {rs(p['amount'])} from {p['sender']} ({p['account']}) · Trx `{p['tid']}`")
        except sqlite3.IntegrityError:
            old = c.execute("SELECT amount,account FROM payments WHERE tid=?", (p["tid"],)).fetchone()
            if old["amount"] != p["amount"] or old["account"] != p["account"]:
                audit("device:" + dev["id"][:8], "payment.conflict", p["tid"], p["text"])
                return err(409, "Trx ID already recorded with different data")
            duplicate = True
        matched = None
        if app.config["AUTO_APPROVE"] and not duplicate:
            expire_orders()
            rows = c.execute("SELECT id FROM orders WHERE status='open' AND amount=? AND created<=?",
                             (p["amount"], iso(observed + timedelta(minutes=2)))).fetchall()
            if len(rows) == 1 and claim(rows[0]["id"], p["tid"], "auto"):
                matched = rows[0]["id"]
        return jsonify({"accepted": True, "duplicate": duplicate, "order_id": matched})

    # ------------------------------------------------------------ public (customer)
    @app.get("/v1/public-config")
    def public_config():
        return jsonify({"pay_number": os.getenv("PAY_NUMBER", ""), "pay_name": os.getenv("PAY_NAME", ""),
                        "max_amount": int(os.getenv("PUBLIC_MAX", "50000")),
                        "min_amount": int(os.getenv("PUBLIC_MIN", "1"))})

    def check_amount(value):
        paisa = to_paisa(value)
        lo, hi = int(os.getenv("PUBLIC_MIN", "1")), int(os.getenv("PUBLIC_MAX", "50000"))
        if paisa is None or not lo * 100 <= paisa <= hi * 100:
            return None, err(400, f"Amount must be between Rs {lo} and Rs {hi}")
        return paisa, None

    def too_many_open():
        expire_orders()
        return db().execute("SELECT count(*) FROM orders WHERE status='open'").fetchone()[0] >= 500

    @app.post("/v1/orders")
    def create_public_order():
        if limited("ordip:" + client_ip(), limit=10):
            return err(429, "Too many requests, try again in a minute")
        paisa, e = check_amount((request.get_json(silent=True) or {}).get("amount"))
        if e:
            return e
        if too_many_open():
            return err(503, "Busy, try again shortly")
        return jsonify(new_order(paisa, "web")), 201

    @app.get("/v1/orders/<oid>")
    def order_status(oid):
        expire_orders()
        o = db().execute("SELECT id,amount,status,expires,source FROM orders WHERE id=?", (oid,)).fetchone()
        if not o:
            return err(404, "unknown order")
        return jsonify({"id": o["id"], "amount": rs(o["amount"]), "status": o["status"],
                        "expires": o["expires"], "source": o["source"]})

    @app.post("/v1/orders/<oid>/verify")
    def verify(oid):
        if limited("ip:" + client_ip(), limit=20):
            return err(429, "rate limited")
        body = request.get_json(silent=True) or {}
        tid = str(body.get("trx_id", "")).strip()
        if not re.fullmatch(r"\d{6,30}", tid):
            return err(400, "Enter the Transaction ID (digits only)")
        number = norm_number(body.get("sender"))
        if not number:
            return err(400, "Enter your Easypaisa number, e.g. 03001234567")
        if limited("ord:" + oid, limit=15, window=600):
            return err(429, "Too many attempts for this order")
        expire_orders()
        c = db()
        o = c.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
        if not o:
            return err(404, "unknown order")

        def fail(reason):
            audit("web:" + client_ip(), "verify.failed", oid, f"tid={tid} reason={reason}")
            return jsonify({"verified": False, "reason": reason})

        if o["status"] == "paid":
            same = o["payment_tid"] == tid
            return jsonify({"verified": same, "already": same, "reason": None if same else "order already paid"})
        if o["status"] != "open":
            return fail("order " + o["status"])
        p = c.execute("SELECT * FROM payments WHERE tid=?", (tid,)).fetchone()
        if not p:
            return fail("payment not received yet")
        if p["status"] == "rejected":
            return fail("this payment was rejected by admin")
        if p["order_id"]:
            return fail("transaction already used")
        if p["amount"] != o["amount"]:
            return fail("amount mismatch")
        if not mask_matches(p["account"], number):
            return fail("number does not match this payment")
        paid_at, ordered_at = parse_iso(p["observed_at"]), parse_iso(o["created"])
        if paid_at < ordered_at - LOOKBACK:
            mins = int((ordered_at - paid_at).total_seconds() // 60)
            return fail(f"payment is {mins} min older than this order; create a new order and pay again")
        if not claim(oid, tid, "customer"):
            return fail("could not claim; retry")
        return jsonify({"verified": True, "sender": p["sender"]})

    # ------------------------------------------------------------ bot (AYO Discord bot)
    @app.post("/v1/bot/orders")
    def bot_create_order():
        if not is_bot():
            return err(401, "bot key required")
        body = request.get_json(silent=True) or {}
        uid = str(body.get("discord_user_id", ""))
        if not re.fullmatch(r"\d{5,25}", uid):
            return err(400, "discord_user_id required")
        paisa, e = check_amount(body.get("amount"))
        if e:
            return e
        if too_many_open():
            return err(503, "Busy, try again shortly")
        if db().execute("SELECT count(*) FROM orders WHERE discord_user_id=? AND status='open'",
                        (uid,)).fetchone()[0] >= 3:
            return err(429, "You already have 3 open deposits; pay or wait for them to expire")
        o = new_order(paisa, "discord", str(body.get("note", "")), uid)
        audit("bot", "order.created", o["id"], f"user={uid} Rs {o['amount']}")
        return jsonify(o), 201

    @app.get("/v1/bot/credits")
    def bot_pending_credits():
        """Paid Discord orders the bot has not credited yet."""
        if not is_bot():
            return err(401, "bot key required")
        rows = db().execute("SELECT id,amount,discord_user_id,payment_tid,paid_at FROM orders "
                            "WHERE status='paid' AND credited=0 AND discord_user_id IS NOT NULL "
                            "ORDER BY paid_at LIMIT 50").fetchall()
        return jsonify([{**dict(r), "amount": rs(r["amount"]), "amount_paisa": r["amount"]} for r in rows])

    @app.post("/v1/bot/credits/<oid>/ack")
    def bot_ack(oid):
        if not is_bot():
            return err(401, "bot key required")
        n = db().execute("UPDATE orders SET credited=1, credited_at=? WHERE id=? AND status='paid'",
                         (iso(now()), oid)).rowcount
        if n:
            audit("bot", "order.credited", oid)
        return jsonify({"ok": bool(n)})

    @app.get("/v1/bot/users/<uid>/orders")
    def bot_user_orders(uid):
        if not is_bot():
            return err(401, "bot key required")
        expire_orders()
        rows = db().execute("SELECT id,amount,status,created,payment_tid,credited FROM orders "
                            "WHERE discord_user_id=? ORDER BY created DESC LIMIT 10", (uid,)).fetchall()
        return jsonify([order_json(r) for r in rows])

    # ------------------------------------------------------------ admin
    def admin_only(fn):
        def wrapped(*a, **kw):
            if not is_admin():
                return err(401, "admin key required")
            return fn(*a, **kw)
        wrapped.__name__ = fn.__name__
        return wrapped

    @app.post("/v1/admin/devices")
    @admin_only
    def register_device():
        name = str((request.get_json(silent=True) or {}).get("name", "")).strip()[:80]
        if not name:
            return err(400, "name required")
        dev_id, token = str(uuid.uuid4()), secrets.token_hex(32)
        db().execute("INSERT INTO devices(id,name,token_hash,created) VALUES(?,?,?,?)",
                     (dev_id, name, hashlib.sha256(token.encode()).hexdigest(), iso(now())))
        audit("admin", "device.created", dev_id, name)
        return jsonify({"id": dev_id, "device_token": token}), 201

    @app.get("/v1/admin/devices")
    @admin_only
    def list_devices():
        rows = db().execute("SELECT id,name,created,revoked,last_seen FROM devices ORDER BY created").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["online"] = bool(r["last_seen"]) and parse_iso(r["last_seen"]) > now() - OFFLINE_AFTER
            out.append(d)
        return jsonify(out)

    @app.post("/v1/admin/devices/<dev_id>/revoke")
    @admin_only
    def revoke_device(dev_id):
        n = db().execute("UPDATE devices SET revoked=1 WHERE id=?", (dev_id,)).rowcount
        if not n:
            return err(404, "unknown device")
        audit("admin", "device.revoked", dev_id)
        return jsonify({"ok": True})

    @app.post("/v1/admin/orders")
    @admin_only
    def create_order():
        body = request.get_json(silent=True) or {}
        paisa = to_paisa(body.get("amount"))
        if paisa is None or not 1 <= paisa <= MAX_PAISA:
            return err(400, "amount required, e.g. 8.00")
        o = new_order(paisa, "admin", str(body.get("note", "")))
        audit("admin", "order.created", o["id"], f"Rs {o['amount']}")
        return jsonify(o), 201

    @app.get("/v1/admin/orders")
    @admin_only
    def list_orders():
        expire_orders()
        status = request.args.get("status", "")
        q, args = "SELECT * FROM orders", []
        if status:
            q += " WHERE status=?"
            args.append(status)
        rows = db().execute(q + " ORDER BY created DESC LIMIT 200", args).fetchall()
        return jsonify([order_json(r) for r in rows])

    @app.post("/v1/admin/orders/<oid>/approve")
    @admin_only
    def admin_approve(oid):
        """Manually bind a received payment to an order (e.g. customer typed wrong number)."""
        tid = str((request.get_json(silent=True) or {}).get("trx_id", "")).strip()
        c = db()
        o = c.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
        p = c.execute("SELECT * FROM payments WHERE tid=?", (tid,)).fetchone()
        if not o or not p:
            return err(404, "unknown order or payment")
        if p["amount"] != o["amount"]:
            return err(400, f"amount mismatch: order Rs {rs(o['amount'])}, payment Rs {rs(p['amount'])}")
        if not claim(oid, tid, "admin"):
            return err(409, "order not open or payment already used/rejected")
        return jsonify({"ok": True})

    @app.post("/v1/admin/orders/<oid>/cancel")
    @admin_only
    def admin_cancel(oid):
        n = db().execute("UPDATE orders SET status='cancelled' WHERE id=? AND status='open'", (oid,)).rowcount
        if n:
            audit("admin", "order.cancelled", oid)
        return jsonify({"ok": bool(n)})

    def payment_filter():
        q, args = " WHERE 1=1", []
        a = request.args
        if a.get("status"):
            q += " AND status=?"
            args.append(a["status"])
        if a.get("q"):
            q += " AND (tid LIKE ? OR sender LIKE ? OR account LIKE ? OR order_id LIKE ?)"
            args += ["%" + a["q"] + "%"] * 4
        if a.get("from"):
            q += " AND received_at>=?"
            args.append(a["from"])
        if a.get("to"):
            q += " AND received_at<=?"
            args.append(a["to"])
        return q, args

    @app.get("/v1/admin/payments")
    @admin_only
    def list_payments():
        q, args = payment_filter()
        rows = db().execute("SELECT tid,amount,sender,account,observed_at,received_at,order_id,status,note "
                            "FROM payments" + q + " ORDER BY received_at DESC LIMIT 200", args).fetchall()
        return jsonify([{**dict(r), "amount": rs(r["amount"])} for r in rows])

    @app.post("/v1/admin/payments/<tid>/status")
    @admin_only
    def set_payment_status(tid):
        body = request.get_json(silent=True) or {}
        status = body.get("status")
        if status not in ("rejected", "unmatched", "refunded"):
            return err(400, "status must be rejected, unmatched or refunded")
        n = db().execute("UPDATE payments SET status=?, note=? WHERE tid=? AND order_id IS NULL",
                         (status, str(body.get("note", ""))[:200], tid)).rowcount
        if not n:
            return err(409, "unknown payment or already matched to an order")
        audit("admin", "payment." + status, tid, str(body.get("note", "")))
        return jsonify({"ok": True})

    @app.get("/v1/admin/export/payments.csv")
    @admin_only
    def export_csv():
        q, args = payment_filter()
        rows = db().execute("SELECT * FROM payments" + q + " ORDER BY received_at", args).fetchall()
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["trx_id", "amount_rs", "sender", "account", "paid_at_utc", "received_at_utc",
                    "status", "order_id", "note"])
        for r in rows:
            w.writerow([r["tid"], rs(r["amount"]), r["sender"], r["account"], r["observed_at"],
                        r["received_at"], r["status"], r["order_id"] or "", r["note"]])
        return Response(buf.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": "attachment; filename=payments.csv"})

    @app.get("/v1/admin/stats")
    @admin_only
    def stats():
        expire_orders()
        c = db()
        local_now = now().astimezone(TZ)
        day0 = local_now.replace(hour=0, minute=0, second=0, microsecond=0)

        def total(since):
            r = c.execute("SELECT count(*), coalesce(sum(amount),0) FROM payments "
                          "WHERE received_at>=? AND status!='rejected'", (iso(since.astimezone(timezone.utc)),)).fetchone()
            return {"count": r[0], "amount": rs(r[1])}
        days = []
        for i in range(6, -1, -1):
            a = day0 - timedelta(days=i)
            r = c.execute("SELECT count(*), coalesce(sum(amount),0) FROM payments WHERE received_at>=? "
                          "AND received_at<? AND status!='rejected'",
                          (iso(a.astimezone(timezone.utc)), iso((a + timedelta(days=1)).astimezone(timezone.utc)))).fetchone()
            days.append({"day": a.strftime("%a %d"), "count": r[0], "amount": rs(r[1])})
        devs = c.execute("SELECT name,last_seen,revoked FROM devices").fetchall()
        return jsonify({
            "today": total(day0), "week": total(day0 - timedelta(days=6)),
            "month": total(day0.replace(day=1)), "days": days,
            "unmatched": c.execute("SELECT count(*) FROM payments WHERE status='unmatched'").fetchone()[0],
            "open_orders": c.execute("SELECT count(*) FROM orders WHERE status='open'").fetchone()[0],
            "uncredited": c.execute("SELECT count(*) FROM orders WHERE status='paid' AND credited=0 "
                                    "AND discord_user_id IS NOT NULL").fetchone()[0],
            "devices": [{"name": d["name"], "revoked": bool(d["revoked"]), "last_seen": d["last_seen"],
                         "online": bool(d["last_seen"]) and parse_iso(d["last_seen"]) > now() - OFFLINE_AFTER}
                        for d in devs],
            "auto_approve": app.config["AUTO_APPROVE"],
        })

    @app.get("/v1/admin/audit")
    @admin_only
    def audit_log():
        rows = db().execute("SELECT * FROM audit ORDER BY id DESC LIMIT 200").fetchall()
        return jsonify([dict(r) for r in rows])

    # ------------------------------------------------------------ pages
    def page(name):
        with open(os.path.join(HERE, "static", name), encoding="utf-8") as f:
            return f.read(), 200, {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store",
                                   "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer"}

    @app.get("/")
    def pay_page():
        return page("pay.html")

    @app.get("/admin")
    def admin_page():
        return page("admin.html")

    @app.get("/health")
    def health():
        return jsonify({"service": "ayo-easypaisa-gateway", "version": 2, "ok": True,
                        "auto_approve": app.config["AUTO_APPROVE"]})

    # ------------------------------------------------------------ offline watcher
    def watch_devices():
        while True:
            time.sleep(60)
            try:
                with connect() as c:
                    cutoff = iso(now() - OFFLINE_AFTER)
                    for d in c.execute("SELECT id,name FROM devices WHERE revoked=0 AND offline_alerted=0 "
                                       "AND last_seen IS NOT NULL AND last_seen<?", (cutoff,)).fetchall():
                        notify(f"🔴 Payment phone **{d['name']}** offline for {OFFLINE_AFTER.seconds // 60}+ min. "
                               "Payments may be delayed: check internet, battery settings, Notification Access.")
                        c.execute("UPDATE devices SET offline_alerted=1 WHERE id=?", (d["id"],))
            except Exception as e:
                print("watcher error:", e)

    if start_watcher:
        threading.Thread(target=watch_devices, daemon=True).start()
    return app


if __name__ == "__main__":
    if not os.getenv("ADMIN_KEY"):
        os.environ["ADMIN_KEY"] = secrets.token_urlsafe(24)
        print(f"\n*** ADMIN_KEY not set. Temporary key for this run: {os.environ['ADMIN_KEY']}\n")
    host, port = os.getenv("HOST", "127.0.0.1"), int(os.getenv("PORT", "8080"))
    application = create_app()
    try:
        from waitress import serve   # production-grade server, works on Windows
        print(f"AYO gateway on http://{host}:{port}  (admin: /admin)")
        serve(application, host=host, port=port, threads=8)
    except ImportError:
        application.run(host=host, port=port)
