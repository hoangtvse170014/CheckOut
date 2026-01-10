@echo off
echo ============================================================
echo Restarting People Counter Dashboard
echo ============================================================

REM Kill any existing Python process using port 8000
echo Killing existing server on port 8000...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8000 ^| findstr LISTENING') do (
    echo Found process %%a using port 8000, killing it...
    taskkill /F /PID %%a >nul 2>&1
)

timeout /t 2 /nobreak >nul

echo.
echo Starting new server...
echo ============================================================
echo.

python start_web_server.py

pause
