@echo off
:: ==============================================================
:: Windows Task Scheduler Setup for Trophy Games Alerts
:: Sets up a silent local background task to check prices hourly
:: and send morning briefings as a 100% fail-safe backup!
:: ==============================================================

echo [*] Registering Trophy Games Alert Backup Task in Windows Task Scheduler...

set SCRIPT_DIR=%~dp0
set RUNNER_SCRIPT=%SCRIPT_DIR%run_all_alerts.py

powershell -ExecutionPolicy Bypass -File "%SCRIPT_DIR%setup_windows_backup.ps1"

echo [OK] Setup script completed.
pause
