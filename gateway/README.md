# AYO Easypaisa Payment Gateway v2

Phone app (AYO Payment Helper) -> this gateway -> "Pay now" page + admin dashboard + AYO Discord bot credits.

## Install on Windows PC (D:\AYO BACKENDS\EASYPAISA PAYMENT GATEWAY)
1. Install **Python 3.11+** (python.org, tick "Add to PATH"), **Git** (`winget install Git.Git`) and
   **cloudflared** (`winget install Cloudflare.cloudflared`).
2. Download `get.bat` from this folder and run it: it copies the gateway to
   `D:\AYO BACKENDS\EASYPAISA PAYMENT GATEWAY` (run again later to update; your `.env` and `data\` are kept).
3. In that folder double-click **start.bat**. First time it creates `.env` and opens Notepad:
   set ADMIN_KEY, BOT_KEY, PAY_NUMBER, PAY_NAME. Save, run start.bat again.
4. Double-click **tunnel.bat** -> copy the `https://....trycloudflare.com` link.
   Put it in `.env` as PUBLIC_URL (restart start.bat) and in the phone app as server URL.
5. Open `<link>/admin`, enter ADMIN_KEY -> Devices -> Register phone -> paste ID + token in the app.

Links: `/` customer Pay page (`/?order=<id>` from Discord) · `/admin` dashboard · `/health` status.

## Dashboard
Today / 7 days / month totals, daily chart, phone online/offline, payments search + CSV export,
reject / refunded marking, orders (create, approve manually with Trx ID, cancel), devices (register/revoke),
full audit log of every action.

## Discord bot
Bot `.env`/environment: `GATEWAY_URL=<link or http://127.0.0.1:8080>`, `GATEWAY_BOT_KEY=<BOT_KEY>`,
`COINS_PER_RS=1000`. Commands: `ayo deposit <rupees>` (DMs a Pay now link), `ayo deposits`.
Paid orders are credited automatically within ~20 s, never twice.

## Alerts
Set `DISCORD_WEBHOOK_URL` (channel -> Integrations -> Webhooks) for: payment received, approved,
payment phone offline 20+ min / back online.

## Safety rules built in
Server re-parses the notification; Trx ID usable once; amount must match; sender number must match the
masked number; payment can't be older than order (30 min grace); rate limits; admin/bot keys;
AUTO_APPROVE off by default. A notification is not bank proof: reconcile with Easypaisa history regularly.

Tests: `python selftest.py`
