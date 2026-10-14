@echo off
title AYO HTTPS tunnel
where cloudflared >nul 2>nul || (echo Install: winget install --id Cloudflare.cloudflared & pause & exit /b 1)
echo Copy the https://....trycloudflare.com link below into the phone app and PUBLIC_URL in .env
cloudflared tunnel --url http://localhost:8080
pause
