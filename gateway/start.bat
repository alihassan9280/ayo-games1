@echo off
title AYO Easypaisa Gateway
cd /d "%~dp0"
where python >nul 2>nul || (echo Install Python 3.11+ from python.org and tick "Add to PATH". & pause & exit /b 1)
if not exist .venv ( python -m venv .venv )
call .venv\Scripts\activate.bat
pip install -q -r requirements.txt
if not exist .env ( copy .env.example .env >nul & echo Created .env - fill it in, then run start.bat again. & notepad .env & exit /b 0 )
python app.py
pause
