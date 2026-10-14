"""End-to-end checks for the gateway: python selftest.py"""
import os, sys, tempfile
from datetime import datetime, timedelta, timezone
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app import create_app  # noqa: E402

A = {"X-Admin-Key": "adm"}; B = {"X-Bot-Key": "bot"}; NUM = "0300 4123413"


def stamp(d=0):
    return (datetime.now(timezone.utc) + timedelta(seconds=d)).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def text(tid, amt="8.00"):
    return f"Trx ID {tid}. You have Received Rs {amt} from TEST SENDER with Easypaisa Account 923004****13."


def run(auto):
    c = create_app(os.path.join(tempfile.mkdtemp(), "t.db"), "adm", auto, "bot", start_watcher=False).test_client()
    dev = c.post("/v1/admin/devices", json={"name": "phone"}, headers=A).get_json()
    H = {"Authorization": "Bearer " + dev["device_token"], "X-Device-ID": dev["id"]}
    pay = lambda t, ts=None: c.post("/v1/device/payments", headers=H, json={"notification_text": t, "observed_at": ts or stamp()})
    ver = lambda o, t, n=NUM: c.post(f"/v1/orders/{o}/verify", json={"trx_id": t, "sender": n}).get_json()
    assert c.post("/v1/device/heartbeat", headers=H).get_json()["ok"]
    assert c.post("/v1/admin/devices", json={"name": "x"}).status_code == 401
    assert c.post("/v1/device/heartbeat", headers={**H, "Authorization": "Bearer " + "0" * 64}).status_code == 401
    # pages
    assert b"AYO PAY" in c.get("/").data and b"Gateway" in c.get("/admin").data and c.get("/health").get_json()["ok"]
    # web order + verify
    o = c.post("/v1/orders", json={"amount": "8"}).get_json()
    assert pay(text("11111111111")).get_json()["accepted"]
    if not auto:
        assert ver(o["id"], "99999999999")["verified"] is False
        assert "number" in ver(o["id"], "11111111111", "03111111199")["reason"]
        assert ver(o["id"], "11111111111")["verified"] is True
    assert c.get("/v1/orders/" + o["id"]).get_json()["status"] == "paid"
    o2 = c.post("/v1/orders", json={"amount": "8"}).get_json()
    assert "already used" in ver(o2["id"], "11111111111")["reason"]
    assert pay(text("11111111111")).get_json()["duplicate"] is True
    assert pay(text("11111111111", "9.00")).status_code == 409
    assert pay("hello").status_code == 422
    assert pay(text("22222222222"), stamp(3600)).status_code == 400
    o3 = c.post("/v1/orders", json={"amount": "50"}).get_json(); pay(text("33333333333", "10.00"))
    assert ver(o3["id"], "33333333333")["reason"] == "amount mismatch"
    o4 = c.post("/v1/admin/orders", json={"amount": "7"}, headers=A).get_json(); pay(text("44444444444", "7.00"), stamp(-3600))
    assert "older" in ver(o4["id"], "44444444444")["reason"]
    # discord bot flow
    assert c.post("/v1/bot/orders", json={"discord_user_id": "123456789", "amount": "100"}).status_code == 401
    bo = c.post("/v1/bot/orders", json={"discord_user_id": "123456789", "amount": "100"}, headers=B).get_json()
    assert "?order=" + bo["id"] in bo["pay_url"]
    assert c.get("/v1/bot/credits", headers=B).get_json() == []
    pay(text("55555555555", "100.00"))
    if not auto:
        assert ver(bo["id"], "55555555555")["verified"] is True
    cr = c.get("/v1/bot/credits", headers=B).get_json()
    assert len(cr) == 1 and cr[0]["discord_user_id"] == "123456789" and cr[0]["amount_paisa"] == 10000
    assert c.post(f"/v1/bot/credits/{bo['id']}/ack", headers=B).get_json()["ok"]
    assert c.get("/v1/bot/credits", headers=B).get_json() == []
    assert len(c.get("/v1/bot/users/123456789/orders", headers=B).get_json()) == 1
    # admin: manual approve, reject, stats, csv, audit
    o5 = c.post("/v1/admin/orders", json={"amount": "10"}, headers=A).get_json()
    assert c.post(f"/v1/admin/orders/{o5['id']}/approve", json={"trx_id": "33333333333"}, headers=A).status_code == 200
    pay(text("66666666666", "5.00"))
    assert c.post("/v1/admin/payments/66666666666/status", json={"status": "rejected", "note": "x"}, headers=A).status_code == 200
    o6 = c.post("/v1/orders", json={"amount": "5"}).get_json()
    assert "rejected" in ver(o6["id"], "66666666666")["reason"]
    s = c.get("/v1/admin/stats", headers=A).get_json()
    assert s["today"]["count"] >= 4 and len(s["days"]) == 7 and s["devices"][0]["online"]
    csvd = c.get("/v1/admin/export/payments.csv", headers=A).data.decode()
    assert csvd.startswith("trx_id") and "55555555555" in csvd
    assert len(c.get("/v1/admin/payments?q=5555", headers=A).get_json()) == 1
    assert any(a["action"] == "order.paid" for a in c.get("/v1/admin/audit", headers=A).get_json())
    assert c.post(f"/v1/admin/devices/{dev['id']}/revoke", headers=A).status_code == 200
    assert c.post("/v1/device/heartbeat", headers=H).status_code == 403
    print(f"auto_approve={auto}: all gateway checks passed")


run(False)
run(True)
