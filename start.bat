@echo off
chcp 65001 >nul 2>&1
title Dashboard

echo Starting Dashboard...
cd /d "%~dp0"

:: kill existing
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8850 ^| findstr LISTENING') do (
    taskkill /F /PID %%a >nul 2>&1
)

start /b python app.py
echo Dashboard running on http://localhost:8850
timeout /t 2 >nul
start http://localhost:8850
