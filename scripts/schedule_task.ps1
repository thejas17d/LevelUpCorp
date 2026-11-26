# Registers a Windows scheduled task that runs one LevelUpCorp cycle every N hours while you're logged in.
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\schedule_task.ps1 [-Hours 4]
#         powershell -ExecutionPolicy Bypass -File scripts\schedule_task.ps1 -Remove
param([int]$Hours = 4, [switch]$Remove)
$name = "LevelUpCorp"
if ($Remove) {
    Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Removed scheduled task '$name'."
    exit 0
}
$script = Join-Path $PSScriptRoot "run_once.ps1"
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$script`""
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) -RepetitionInterval (New-TimeSpan -Hours $Hours)
# Interactive (only when logged in) so the browser window is visible and you can solve a CAPTCHA if one appears.
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 3)
Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
Write-Host "Scheduled '$name': first run in 2 minutes, then every $Hours hours while you're logged in."
Write-Host "See it in Task Scheduler; remove with: scripts\schedule_task.ps1 -Remove"
