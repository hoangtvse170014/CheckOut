@echo off
echo ============================================================
echo Starting People Counter Dashboard (Safe Mode)
echo ============================================================
echo.

REM Kill any existing Python process using port 8000
echo Checking for existing server on port 8000...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8000 ^| findstr LISTENING') do (
    echo Found process %%a using port 8000, killing it...
    taskkill /F /PID %%a >nul 2>&1
    timeout /t 2 /nobreak >nul
)

echo.
echo Starting new server...
echo Dashboard will be available at:
echo   - Local: http://localhost:8000
echo.
echo Press Ctrl+C to stop the server
echo ============================================================
echo.

python start_web_server.py

pause
