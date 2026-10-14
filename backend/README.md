# Temporary test backend for AYO Payment Helper

Not production-ready: single process, SQLite, in-memory rate limits, no HTTPS of its own.
Use it to test the Android app end to end.

## 1. Run it (PC / Termux / VPS)

    pip install -r backend/requirements.txt
    ADMIN_KEY="pick-a-long-random-secret" python backend/app.py      # listens on 127.0.0.1:8080
    # optional: AUTO_APPROVE=1 auto-marks an order paid when exactly one open order has the same amount

## 2. Get an HTTPS link (the app refuses http://)

    cloudflared tunnel --url http://localhost:8080
    # prints https://something.trycloudflare.com  <- paste this in the app (origin only, no path)

(ngrok `ngrok http 8080` works the same.) Anyone with the link can reach the server; admin
endpoints need your ADMIN_KEY, so keep it secret and stop the tunnel when done.

## 3. Register the phone

    curl -X POST https://YOUR-LINK/v1/admin/devices -H "X-Admin-Key: $ADMIN_KEY" \
         -H "Content-Type: application/json" -d '{"name":"My phone"}'

Copy `id` -> app "Device ID", `device_token` -> app "Device token", link -> "HTTPS server URL",
then Save & connect / Test connection. Then Trust installed Easypaisa + enable Notification Access.

## 4. Test a payment

    curl -X POST https://YOUR-LINK/v1/admin/orders -H "X-Admin-Key: $ADMIN_KEY" \
         -H "Content-Type: application/json" -d '{"amount":"8.00"}'      # -> order id
    # send exactly Rs 8.00 to your wallet, wait until the app shows "synced", then:
    curl -X POST https://YOUR-LINK/v1/orders/ORDER_ID/verify -H "Content-Type: application/json" \
         -d '{"trx_id":"<Transaction ID of the payment>"}'               # -> {"verified": true}
    curl https://YOUR-LINK/v1/admin/payments -H "X-Admin-Key: $ADMIN_KEY"

Verify rules: the Trx ID must have been received from the phone, the amount must match exactly,
the payment must not predate the order, and a Trx ID can fulfil only one order (replay -> "already used").

## Checks

    python backend/selftest.py     # simulates the phone against every endpoint
