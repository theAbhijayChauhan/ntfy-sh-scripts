# Windows Task Scheduler Backup for Trophy Games Alerts
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonPath = (Get-Command python).Source
$runnerScript = Join-Path $scriptDir "run_all_alerts.py"
$taskName = "TrophyGames_PriceAlerts"

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " Trophy Games Local Backup Scheduler Setup" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "Python Path   : $pythonPath"
Write-Host "Runner Script : $runnerScript"
Write-Host "Task Name     : $taskName"
Write-Host ""

if (-not $pythonPath) {
    Write-Host "[!] Error: Python not found in system PATH." -ForegroundColor Red
    exit 1
}

# Create Scheduled Task Action: run pythonw (or python) with run_all_alerts.py
$action = New-ScheduledTaskAction -Execute $pythonPath -Argument "`"$runnerScript`"" -WorkingDirectory $scriptDir

# Trigger: Runs daily at 06:00 AM and repeats every 15 minutes throughout the day
# - 06:00 to 07:00 AM: Delivers Train & Truck Morning Briefing + Schedules Alerts
# - 06:30 to 07:30 AM: Delivers Energy Manager Morning Briefing
# - Rest of Day: Performs silent hourly price checks for Energy Manager (zero spam)
$trigger = New-ScheduledTaskTrigger -Daily -At "06:00 AM"
$trigger.RepetitionInterval = (New-TimeSpan -Minutes 15)
$trigger.RepetitionDuration = (New-TimeSpan -Days 1)

# Settings: Allow start on battery, run when available
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

try {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Description "Automated 24/7 price alert tracker and ntfy notifier for Trophy Games (Train, Truck, Energy Manager)." | Out-Null
    Write-Host "[OK] Task '$taskName' successfully registered in Windows Task Scheduler!" -ForegroundColor Green
    Write-Host "     It will run daily starting at 06:00 AM and repeat every 15 minutes." -ForegroundColor Green
    Write-Host "     Because of built-in deduplication, it will NEVER send duplicate alerts if GitHub Actions already did." -ForegroundColor Green
} catch {
    Write-Host "[!] Failed to register scheduled task: $_" -ForegroundColor Red
}
