"""Temporary test backend for AYO Payment Helper (Android app).

Implements the contract the app expects:
  POST /v1/admin/devices          (admin)  register a phone -> id + device_token
  POST /v1/device/heartbeat       (device) connection test, returns {"ok": true}
  POST /v1/device/payments        (device) notification text -> {"accepted": true}
Plus a tiny order/verify flow so you can test "payment verified/approved":
  POST /v1/admin/orders           (admin)  create an order for an amount
  POST /v1/orders/<id>/verify     (public) customer submits Trx ID -> verified or not
  GET  /v1/orders/<id>            (public) order status
  GET  /v1/admin/payments         (admin)  list received payments
  POST /v1/admin/devices/<id>/revoke (admin)

Run:  ADMIN_KEY=choose-a-long-secret python backend/app.py
"""
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from flask import Flask, g, jsonify, request

# Same format the app's PaymentParser accepts (app also pre-validates it).
FORMAT = re.compile(
    r"^Trx ID (\d{6,30})\. You have Received Rs "
    r"((?:\d+|\d{1,3}(?:,\d{3})+)\.\d{2}) from (.+?) "
    r"with Easypaisa Account (92[\d*]+)\.?$")
MAX_PAISA = 100_000_000          # Rs 1,000,000, same cap as the app
MAX_AGE = timedelta(days=7)      # app flags older items itself
FUTURE_SKEW = timedelta(minutes=5)
VERIFY_SKEW = timedelta(minutes=2)   # phone clock vs server clock
ORDER_TTL = timedelta(minutes=30)

SCHEMA = """
CREATE TABLE IF NOT EXISTS devices(
  id TEXT PRIMARY KEY, name TEXT NOT NULL, token_hash TEXT NOT NULL,
  created TEXT NOT NULL, revoked INTEGER NOT NULL DEFAULT 0, last_seen TEXT);
CREATE TABLE IF NOT EXISTS orders(
  id TEXT PRIMARY KEY, amount INTEGER NOT NULL, note TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'open', created TEXT NOT NULL, expires TEXT NOT NULL,
  payment_tid TEXT);
CREATE TABLE IF NOT EXISTS payments(
  tid TEXT PRIMARY KEY, amount INTEGER NOT NULL, sender TEXT NOT NULL,
  account TEXT NOT NULL, text TEXT NOT NULL, observed_at TEXT NOT NULL,
  received_at TEXT NOT NULL, device_id TEXT NOT NULL, order_id TEXT);
"""


def now():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_iso(s):
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timezone required")
    return dt.astimezone(timezone.utc)


def parse_payment(text):
    """Re-parse server side; never trust the phone's parsing."""
    if not isinstance(text, str) or len(text) > 2000:
        return None
    t = re.sub(r"\s+", " ", text.strip())
    m = FORMAT.match(t)
    if not m or len(m.group(4)) != 12:
        return None
    try:
        paisa = int((Decimal(m.group(2).replace(",", "")) * 100).to_integral_exact())
    except (InvalidOperation, ValueError):
        return None
    if not 1 <= paisa <= MAX_PAISA:
        return None
    return {"tid": m.group(1), "amount": paisa, "sender": m.group(3),
            "account": m.group(4), "text": t}


ADMIN_HTML = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>AYO test admin</title>
<style>body{font:16px system-ui;margin:16px;max-width:560px}input,button{font:inherit;padding:10px;margin:4px 0;width:100%;box-sizing:border-box}
button{background:#1a7f4b;color:#fff;border:0;border-radius:8px}pre{background:#f2f2f2;padding:10px;white-space:pre-wrap;word-break:break-all;border-radius:8px}
h3{margin:18px 0 4px}</style></head><body><h2>AYO test admin</h2>
<input id=key type=password placeholder="ADMIN_KEY" autocomplete=off>
<h3>1. New order</h3><input id=amt inputmode=decimal placeholder="Amount e.g. 8.00"><button onclick="mk()">Create order</button>
<h3>2. Verify payment</h3><input id=oid placeholder="Order id"><input id=tid inputmode=numeric placeholder="Transaction ID">
<button onclick="vf()">Verify</button><h3>3. Received payments</h3><button onclick="ls()">Refresh list</button><pre id=out>ready</pre>
<script>
const o=document.getElementById('out'),$=i=>document.getElementById(i).value.trim();
async function call(m,u,b,a){const r=await fetch(u,{method:m,headers:{'Content-Type':'application/json',...(a?{'X-Admin-Key':$('key')}:{})},body:b?JSON.stringify(b):undefined});
 const t=await r.text();let j;try{j=JSON.stringify(JSON.parse(t),null,1)}catch(e){j=t}o.textContent=r.status+'\n'+j;return t}
async function mk(){const t=await call('POST','/v1/admin/orders',{amount:$('amt')},1);try{document.getElementById('oid').value=JSON.parse(t).id||''}catch(e){}}
function vf(){call('POST','/v1/orders/'+encodeURIComponent($('oid'))+'/verify',{trx_id:$('tid')})}
function ls(){call('GET','/v1/admin/payments',null,1)}
</script></body></html>"""


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


PAY_HTML = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Pay now</title>
<style>*{box-sizing:border-box}body{font:16px system-ui;margin:0;background:#f4f6f5;color:#16231c}
.c{max-width:440px;margin:0 auto;padding:20px}.card{background:#fff;border-radius:14px;padding:18px;margin-top:14px;box-shadow:0 1px 4px #0001}
h2{margin:6px 0}input,button{font:inherit;width:100%;padding:13px;margin-top:10px;border-radius:10px;border:1px solid #bcc7c0}
button{background:#1a7f4b;color:#fff;border:0;font-weight:600}button.sec{background:#e6ece8;color:#16231c}
.big{font-size:26px;font-weight:700}.num{font-size:22px;font-weight:700;letter-spacing:.5px;word-break:break-all}
.ok{color:#116b3a}.bad{color:#b3261e}.muted{color:#5b6b62;font-size:14px}[hidden]{display:none}</style></head><body><div class=c>
<h2>Pay now</h2>
<div class=card id=s1><div>Enter amount (Rs)</div><input id=amt inputmode=decimal value="100">
<button id=ok1>OK</button><div id=m1 class="muted bad"></div></div>
<div class=card id=s2 hidden><div class=muted>Send exactly</div><div class=big id=pa></div>
<div class=muted style="margin-top:10px">via Easypaisa to <span id=pn></span></div><div class=num id=pnum></div>
<div class=muted>Order expires in <span id=left></span></div>
<hr style="border:0;border-top:1px solid #e3e8e5;margin:16px 0">
<div>After paying, enter your details</div>
<input id=num inputmode=tel placeholder="Your Easypaisa number (03xx xxxxxxx)">
<input id=tid inputmode=numeric placeholder="Transaction ID (Trx ID)">
<button id=ok2>OK</button><button class=sec id=cancel>Start over</button><div id=m2 class="muted"></div></div>
<div class=card id=s3 hidden><div class="big ok">&#10003; Payment approved</div>
<div id=done class=muted style="margin-top:8px"></div><button class=sec id=again>New payment</button></div>
</div><script>
const $=i=>document.getElementById(i),S=(i,on)=>$(i).hidden=!on;let order=null,cfg={},timer=null;
const store={get(){try{return JSON.parse(localStorage.getItem('ord')||'null')}catch(e){return null}},
 set(v){try{v?localStorage.setItem('ord',JSON.stringify(v)):localStorage.removeItem('ord')}catch(e){}}};
async function j(u,b){const r=await fetch(u,b?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)}:{});
 let d={};try{d=await r.json()}catch(e){}return{s:r.status,d}}
function show(o){order=o;store.set(o);$('pa').textContent='Rs '+o.amount;$('pn').textContent=cfg.pay_name?'('+cfg.pay_name+')':'';
 $('pnum').textContent=cfg.pay_number||'(merchant number not set)';S('s1',0);S('s2',1);S('s3',0);clearInterval(timer);
 const tick=()=>{const t=Math.max(0,Math.floor((new Date(o.expires)-Date.now())/1000));$('left').textContent=Math.floor(t/60)+':'+String(t%60).padStart(2,'0');
  if(!t){clearInterval(timer);$('m2').textContent='Order expired. Start over.';$('m2').className='muted bad'}};tick();timer=setInterval(tick,1000)}
function reset(){clearInterval(timer);order=null;store.set(null);S('s1',1);S('s2',0);S('s3',0);$('m1').textContent='';$('m2').textContent=''}
$('ok1').onclick=async()=>{$('m1').textContent='';const r=await j('/v1/orders',{amount:$('amt').value.trim()});
 if(r.s==201)show(r.d);else $('m1').textContent=r.d.error||'Could not create order'};
$('ok2').onclick=async()=>{const m=$('m2');m.className='muted';m.textContent='Checking...';
 const r=await j('/v1/orders/'+encodeURIComponent(order.id)+'/verify',{trx_id:$('tid').value.trim(),sender:$('num').value.trim()});
 if(r.d.verified){clearInterval(timer);store.set(null);S('s2',0);S('s3',1);$('done').textContent='Rs '+order.amount+' received. Thank you!'}
 else{m.className='muted bad';m.textContent=r.d.reason?({'payment not received yet':'Payment not received yet. Wait a few seconds after paying and try again.'}[r.d.reason]||r.d.reason):(r.d.error||'Not verified')}};
$('cancel').onclick=reset;$('again').onclick=reset;
(async()=>{cfg=(await j('/v1/public-config')).d;const o=store.get();
 if(o){const r=await j('/v1/orders/'+encodeURIComponent(o.id));
  if(r.s==200&&r.d.status==='open')show({...o,expires:r.d.expires});else reset()}})();
</script></body></html>"""


def create_app(db_path=None, admin_key=None, auto_approve=None):
    app = Flask(__name__)
    app.config["DB"] = db_path or os.getenv("DB_PATH", "backend/payments.sqlite3")
    app.config["ADMIN_KEY"] = admin_key or os.getenv("ADMIN_KEY") or ""
    if auto_approve is None:
        auto_approve = os.getenv("AUTO_APPROVE", "0") == "1"
    app.config["AUTO_APPROVE"] = auto_approve
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024
    hits = defaultdict(deque)

    def db():
        if "db" not in g:
            g.db = sqlite3.connect(app.config["DB"], timeout=10, isolation_level=None)
            g.db.row_factory = sqlite3.Row
            g.db.execute("PRAGMA journal_mode=WAL")
        return g.db

    @app.teardown_appcontext
    def close(_):
        d = g.pop("db", None)
        if d:
            d.close()

    with sqlite3.connect(app.config["DB"]) as c:
        c.executescript(SCHEMA)
        # Free hosts wipe the disk on restart: optionally pre-register one device from env.
        seed_id, seed_tok = os.getenv("DEVICE_ID", ""), os.getenv("DEVICE_TOKEN", "")
        if seed_id and seed_tok:
            if not (re.fullmatch(r"[0-9a-fA-F-]{36}", seed_id) and re.fullmatch(r"[0-9a-f]{64}", seed_tok)):
                raise SystemExit("DEVICE_ID must be a UUID and DEVICE_TOKEN 64 lowercase hex chars")
            c.execute("INSERT OR IGNORE INTO devices(id,name,token_hash,created) VALUES(?,?,?,?)",
                      (seed_id, "seeded-device", hashlib.sha256(seed_tok.encode()).hexdigest(), iso(now())))

    def client_ip():
        # behind a Cloudflare tunnel every request comes from localhost; use the real client IP
        fwd = request.headers.get("CF-Connecting-IP") or request.headers.get("X-Forwarded-For", "")
        return fwd.split(",")[0].strip() or request.remote_addr or ""

    def err(code, msg):
        return jsonify({"error": msg}), code

    def limited(key, limit=60, window=60):
        q, t = hits[key], time.monotonic()
        while q and q[0] < t - window:
            q.popleft()
        if len(q) >= limit:
            return True
        q.append(t)
        return False

    def is_admin():
        key = app.config["ADMIN_KEY"]
        got = request.headers.get("X-Admin-Key", "")
        return bool(key) and hmac.compare_digest(got.encode(), key.encode())

    def device_auth():
        """Returns (device_row, None) or (None, error_response)."""
        dev_id = request.headers.get("X-Device-ID", "")
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer ") or not dev_id:
            return None, err(401, "missing credentials")
        row = db().execute("SELECT * FROM devices WHERE id=?", (dev_id,)).fetchone()
        token_hash = hashlib.sha256(auth[7:].strip().encode()).hexdigest()
        # compare against a dummy hash when the device is unknown (constant-ish time)
        stored = row["token_hash"] if row else "0" * 64
        if not hmac.compare_digest(token_hash, stored) or not row:
            return None, err(401, "invalid credentials")
        if row["revoked"]:
            return None, err(403, "device revoked")
        if limited("dev:" + dev_id):
            return None, err(429, "rate limited")
        db().execute("UPDATE devices SET last_seen=? WHERE id=?", (iso(now()), dev_id))
        return row, None

    def expire_orders():
        db().execute("UPDATE orders SET status='expired' WHERE status='open' AND expires<?",
                     (iso(now()),))

    def claim(order_id, tid):
        """Atomically bind an unclaimed payment to an open order."""
        c = db()
        c.execute("BEGIN IMMEDIATE")
        try:
            p = c.execute("UPDATE payments SET order_id=? WHERE tid=? AND order_id IS NULL",
                          (order_id, tid)).rowcount
            o = c.execute("UPDATE orders SET status='paid',payment_tid=? "
                          "WHERE id=? AND status='open'", (tid, order_id)).rowcount
            if p == 1 and o == 1:
                c.execute("COMMIT")
                return True
            c.execute("ROLLBACK")
        except Exception:
            c.execute("ROLLBACK")
            raise
        return False

    # ---------- admin ----------
    @app.post("/v1/admin/devices")
    def register_device():
        if not is_admin():
            return err(401, "admin key required")
        body = request.get_json(silent=True) or {}
        name = str(body.get("name", "")).strip()[:80]
        if not name:
            return err(400, "name required")
        dev_id, token = str(uuid.uuid4()), secrets.token_hex(32)  # 64 hex chars
        db().execute("INSERT INTO devices(id,name,token_hash,created) VALUES(?,?,?,?)",
                     (dev_id, name, hashlib.sha256(token.encode()).hexdigest(), iso(now())))
        return jsonify({"id": dev_id, "device_token": token}), 201

    @app.post("/v1/admin/devices/<dev_id>/revoke")
    def revoke_device(dev_id):
        if not is_admin():
            return err(401, "admin key required")
        n = db().execute("UPDATE devices SET revoked=1 WHERE id=?", (dev_id,)).rowcount
        return (jsonify({"ok": True}), 200) if n else err(404, "unknown device")

    @app.post("/v1/admin/orders")
    def create_order():
        if not is_admin():
            return err(401, "admin key required")
        body = request.get_json(silent=True) or {}
        try:
            paisa = int((Decimal(str(body.get("amount"))) * 100).to_integral_exact())
        except (InvalidOperation, ValueError, TypeError):
            return err(400, "amount required, e.g. 8.00")
        if not 1 <= paisa <= MAX_PAISA:
            return err(400, "amount out of range")
        oid, t = secrets.token_urlsafe(9), now()
        db().execute("INSERT INTO orders(id,amount,note,created,expires) VALUES(?,?,?,?,?)",
                     (oid, paisa, str(body.get("note", ""))[:200], iso(t), iso(t + ORDER_TTL)))
        return jsonify({"id": oid, "amount": f"{paisa/100:.2f}", "expires": iso(t + ORDER_TTL)}), 201

    @app.get("/v1/admin/payments")
    def list_payments():
        if not is_admin():
            return err(401, "admin key required")
        rows = db().execute("SELECT tid,amount,sender,account,observed_at,received_at,order_id "
                            "FROM payments ORDER BY received_at DESC LIMIT 50").fetchall()
        return jsonify([{**dict(r), "amount": f"{r['amount']/100:.2f}"} for r in rows])

    # ---------- device (phone app) ----------
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
            return err(422, "unrecognized payment text")
        try:
            observed = parse_iso(str(body.get("observed_at", "")))
        except ValueError:
            return err(400, "bad observed_at")
        if observed > now() + FUTURE_SKEW or observed < now() - MAX_AGE:
            return err(400, "observed_at outside allowed window; check phone clock")
        c = db()
        try:
            c.execute("INSERT INTO payments(tid,amount,sender,account,text,observed_at,"
                      "received_at,device_id) VALUES(?,?,?,?,?,?,?,?)",
                      (p["tid"], p["amount"], p["sender"], p["account"], p["text"],
                       iso(observed), iso(now()), dev["id"]))
            duplicate = False
        except sqlite3.IntegrityError:
            old = c.execute("SELECT amount,account FROM payments WHERE tid=?", (p["tid"],)).fetchone()
            if old["amount"] != p["amount"] or old["account"] != p["account"]:
                return err(409, "Trx ID already recorded with different data")
            duplicate = True   # retry of the same notification: idempotent success
        matched = None
        if app.config["AUTO_APPROVE"] and not duplicate:
            expire_orders()
            rows = c.execute("SELECT id FROM orders WHERE status='open' AND amount=? AND created<=?",
                             (p["amount"], iso(observed + VERIFY_SKEW))).fetchall()
            if len(rows) == 1 and claim(rows[0]["id"], p["tid"]):   # ambiguous -> manual
                matched = rows[0]["id"]
        return jsonify({"accepted": True, "duplicate": duplicate, "order_id": matched})

    # ---------- customer / order flow ----------
    @app.get("/v1/public-config")
    def public_config():
        return jsonify({"pay_number": os.getenv("PAY_NUMBER", ""), "pay_name": os.getenv("PAY_NAME", ""),
                        "max_amount": int(os.getenv("PUBLIC_MAX", "50000"))})

    @app.post("/v1/orders")
    def create_public_order():
        """Customer 'Pay now': create an order for an amount (rate limited, capped)."""
        if limited("ordip:" + client_ip(), limit=10):
            return err(429, "Too many requests, try again in a minute")
        try:
            amount = Decimal(str((request.get_json(silent=True) or {}).get("amount")).strip())
            paisa = int((amount * 100).to_integral_exact())
        except (InvalidOperation, ValueError, TypeError):
            return err(400, "Enter a valid amount")
        top = int(os.getenv("PUBLIC_MAX", "50000"))
        if amount != amount.quantize(Decimal("0.01")) or not 1 <= paisa <= top * 100:
            return err(400, f"Amount must be between Rs 1 and Rs {top}")
        expire_orders()
        if db().execute("SELECT count(*) FROM orders WHERE status='open'").fetchone()[0] >= 500:
            return err(503, "Busy, try again shortly")
        oid, t = secrets.token_urlsafe(9), now()
        db().execute("INSERT INTO orders(id,amount,note,created,expires) VALUES(?,?,?,?,?)",
                     (oid, paisa, "public", iso(t), iso(t + ORDER_TTL)))
        return jsonify({"id": oid, "amount": f"{paisa/100:.2f}", "expires": iso(t + ORDER_TTL)}), 201

    @app.get("/v1/orders/<oid>")
    def order_status(oid):
        expire_orders()
        o = db().execute("SELECT id,amount,status,expires FROM orders WHERE id=?", (oid,)).fetchone()
        if not o:
            return err(404, "unknown order")
        return jsonify({"id": o["id"], "amount": f"{o['amount']/100:.2f}",
                        "status": o["status"], "expires": o["expires"]})

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
        if limited("ord:" + oid, limit=15, window=600):   # stop TID guessing per order
            return err(429, "Too many attempts for this order")
        expire_orders()
        c = db()
        o = c.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
        if not o:
            return err(404, "unknown order")
        if o["status"] == "paid":   # idempotent: same TID verifying twice does not re-fulfil
            same = o["payment_tid"] == tid
            return jsonify({"verified": same, "already": same,
                            "reason": None if same else "order already paid"})
        if o["status"] != "open":
            return jsonify({"verified": False, "reason": "order " + o["status"]})
        p = c.execute("SELECT * FROM payments WHERE tid=?", (tid,)).fetchone()
        if not p:
            return jsonify({"verified": False, "reason": "payment not received yet"})
        if p["order_id"]:
            return jsonify({"verified": False, "reason": "transaction already used"})
        if p["amount"] != o["amount"]:
            return jsonify({"verified": False, "reason": "amount mismatch"})
        if not mask_matches(p["account"], number):
            return jsonify({"verified": False, "reason": "number does not match this payment"})
        if parse_iso(p["observed_at"]) < parse_iso(o["created"]) - VERIFY_SKEW:
            return jsonify({"verified": False, "reason": "payment older than order"})
        if not claim(oid, tid):
            return jsonify({"verified": False, "reason": "could not claim; retry"})
        return jsonify({"verified": True, "sender": p["sender"]})

    @app.get("/admin")
    def admin_page():
        return ADMIN_HTML, 200, {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store"}

    @app.get("/")
    def pay_page():
        return PAY_HTML, 200, {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store"}

    @app.get("/health")
    def root():
        return jsonify({"service": "ayo-payment-test-backend", "ok": True,
                        "auto_approve": app.config["AUTO_APPROVE"]})

    return app


if __name__ == "__main__":
    key = os.getenv("ADMIN_KEY")
    if not key:
        key = secrets.token_urlsafe(24)
        os.environ["ADMIN_KEY"] = key
        print(f"\n*** No ADMIN_KEY set. Temporary one for this run: {key}\n")
    application = create_app()
    application.run(host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "8080")))
