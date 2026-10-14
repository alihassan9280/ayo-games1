@echo off
rem Downloads/updates the gateway into D:\AYO BACKENDS\EASYPAISA PAYMENT GATEWAY
set "DEST=D:\AYO BACKENDS\EASYPAISA PAYMENT GATEWAY"
set "REPO=%TEMP%\ayo-games1"
where git >nul 2>nul || (echo Install Git: winget install --id Git.Git & pause & exit /b 1)
if exist "%REPO%\.git" ( git -C "%REPO%" pull ) else ( git clone -b ccr-8aff8cfe-4w1p8c https://github.com/alihassan9280/ayo-games1 "%REPO%" )
if not exist "%DEST%" mkdir "%DEST%"
robocopy "%REPO%\gateway" "%DEST%" /E /XD data .venv /XF .env >nul
echo Done: %DEST%
pause
