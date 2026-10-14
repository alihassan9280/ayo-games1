"""Simulates the phone app against the backend: python backend/selftest.py"""
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(__file__))
from app import create_app  # noqa: E402

ADMIN = {"X-Admin-Key": "test-admin-key"}
NUM = "0300 4123413"   # matches masked 923004****13


def stamp(delta=0):
    t = datetime.now(timezone.utc) + timedelta(seconds=delta)
    return t.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def text(tid, amt="8.00", name="TEST SENDER"):
    return f"Trx ID {tid}. You have Received Rs {amt} from {name} with Easypaisa Account 923004****13."


def run(auto):
    d = tempfile.mkdtemp()
    c = create_app(os.path.join(d, "t.db"), "test-admin-key", auto).test_client()
    reg = c.post("/v1/admin/devices", json={"name": "phone"}, headers=ADMIN)
    assert reg.status_code == 201, reg.data
    dev = reg.get_json()
    assert len(dev["device_token"]) == 64 and len(dev["id"]) == 36
    H = {"Authorization": "Bearer " + dev["device_token"], "X-Device-ID": dev["id"]}
    pay = lambda t, ts=None: c.post("/v1/device/payments", headers=H,
                                    json={"notification_text": t, "observed_at": ts or stamp()})

    assert c.post("/v1/admin/devices", json={"name": "x"}).status_code == 401      # no admin key
    assert c.post("/v1/device/heartbeat", headers={**H, "Authorization": "Bearer " + "0" * 64}).status_code == 401
    r = c.post("/v1/device/heartbeat", headers=H)
    assert r.status_code == 200 and r.get_json()["ok"] is True

    order = c.post("/v1/admin/orders", json={"amount": "8.00"}, headers=ADMIN).get_json()
    r = pay(text("12345678901"))
    assert r.status_code == 200 and r.get_json()["accepted"] is True
    if auto:
        assert r.get_json()["order_id"] == order["id"]
        assert c.get("/v1/orders/" + order["id"]).get_json()["status"] == "paid"
    else:   # manual verify by Trx ID
        assert r.get_json()["order_id"] is None
        v = c.post(f"/v1/orders/{order['id']}/verify", json={"trx_id": "99999999999", "sender": NUM}).get_json()
        assert v["verified"] is False
        v = c.post(f"/v1/orders/{order['id']}/verify", json={"trx_id": "12345678901", "sender": NUM}).get_json()
        assert v["verified"] is True, v
    # wrong sender number is refused even with a real TID (checked on a fresh order below)
    # verifying again must not fulfil twice for another order
    o2 = c.post("/v1/admin/orders", json={"amount": "8.00"}, headers=ADMIN).get_json()
    v = c.post(f"/v1/orders/{o2['id']}/verify", json={"trx_id": "12345678901", "sender": NUM}).get_json()
    assert v["verified"] is False and "already used" in v["reason"], v

    r = pay(text("12345678901"))                                                    # retry = idempotent
    assert r.status_code == 200 and r.get_json()["duplicate"] is True
    assert pay(text("12345678901", "9.00")).status_code == 409                      # conflicting data
    assert pay("Trx ID 1. hello").status_code == 422                                # bad format
    assert pay(text("22222222222"), stamp(3600)).status_code == 400                 # future clock
    assert pay(text("33333333333"), stamp(-8 * 86400)).status_code == 400           # too old
    # wrong amount never verifies
    o3 = c.post("/v1/admin/orders", json={"amount": "50.00"}, headers=ADMIN).get_json()
    pay(text("44444444444", "10.00"))
    v = c.post(f"/v1/orders/{o3['id']}/verify", json={"trx_id": "44444444444", "sender": NUM}).get_json()
    assert v["verified"] is False and v["reason"] == "amount mismatch"
    # payment older than the order is rejected for verification
    o4 = c.post("/v1/admin/orders", json={"amount": "7.00"}, headers=ADMIN).get_json()
    pay(text("55555555555", "7.00"), stamp(-3600))
    v = c.post(f"/v1/orders/{o4['id']}/verify", json={"trx_id": "55555555555", "sender": NUM}).get_json()
    assert v["verified"] is False and "older" in v["reason"], v
    # pay-then-order within the lookback window is accepted
    o5 = c.post("/v1/admin/orders", json={"amount": "6.00"}, headers=ADMIN).get_json()
    pay(text("88888888888", "6.00"), stamp(-600))
    v = c.post(f"/v1/orders/{o5['id']}/verify", json={"trx_id": "88888888888", "sender": NUM}).get_json()
    assert v["verified"] is True, v

    # public "Pay now" flow: customer creates order, pays, enters number + TID
    assert b"Pay now" in c.get("/").data and c.get("/health").get_json()["ok"]
    pub = c.post("/v1/orders", json={"amount": "100"}).get_json()
    assert pub["amount"] == "100.00"
    assert c.post("/v1/orders", json={"amount": "abc"}).status_code == 400
    assert c.post("/v1/orders", json={"amount": "0"}).status_code == 400
    assert c.post("/v1/orders", json={"amount": "999999"}).status_code == 400
    pay(text("66666666666", "100.00"))
    if not auto:   # (auto mode approves a unique same-amount order straight away)
        bad = c.post(f"/v1/orders/{pub['id']}/verify", json={"trx_id": "66666666666", "sender": "03111111199"}).get_json()
        assert bad["verified"] is False and "number" in bad["reason"], bad
        assert c.post(f"/v1/orders/{pub['id']}/verify", json={"trx_id": "66666666666"}).status_code == 400  # number required
        ok = c.post(f"/v1/orders/{pub['id']}/verify", json={"trx_id": "66666666666", "sender": "+92 300 4123413"}).get_json()
        assert ok["verified"] is True, ok
    else:
        assert c.get("/v1/orders/" + pub["id"]).get_json()["status"] == "paid"
    fake = c.post("/v1/orders", json={"amount": "100"}).get_json()
    f = c.post(f"/v1/orders/{fake['id']}/verify", json={"trx_id": "77777777777", "sender": NUM}).get_json()
    assert f["verified"] is False and "not received" in f["reason"]   # fake TID is rejected

    assert c.post(f"/v1/admin/devices/{dev['id']}/revoke", headers=ADMIN).status_code == 200
    assert c.post("/v1/device/heartbeat", headers=H).status_code == 403
    print(f"auto_approve={auto}: all checks passed")


run(False)
run(True)
