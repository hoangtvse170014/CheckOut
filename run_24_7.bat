@echo off
REM ============================================================
REM People Counter - 24/7 Auto-Run Script
REM ============================================================
REM This script runs the people counter application continuously.
REM If the app crashes, it will automatically restart after 5 seconds.
REM
REM To stop: Press Ctrl+C or close this window
REM ============================================================

echo ============================================================
echo People Counter - 24/7 Auto-Run
echo ============================================================
echo.
echo Starting application...
echo The app will automatically restart if it crashes.
echo Press Ctrl+C to stop.
echo ============================================================
echo.

:loop
python scripts/run.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ============================================================
    echo Application crashed or exited with error code %ERRORLEVEL%
    echo Waiting 5 seconds before restarting...
    echo ============================================================
    timeout /t 5 /nobreak >nul
    echo.
    echo Restarting application...
    echo.
    goto loop
) else (
    echo.
    echo ============================================================
    echo Application exited normally.
    echo Press any key to exit...
    echo ============================================================
    pause >nul
)
