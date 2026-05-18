@echo off
chcp 65001 >nul 2>&1

echo Stopping Dashboard...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8850 ^| findstr LISTENING') do (
    taskkill /F /PID %%a >nul 2>&1
)
echo Dashboard stopped.
