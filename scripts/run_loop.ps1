# Runs LevelUpCorp continuously: one full cycle (scripts\run_once.ps1), then a short pause, forever.
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\run_loop.ps1 [-Minutes 15]
# Stop:   close this window, or:  Stop-Process -Id (Get-Content data\loop.pid)
param([int]$Minutes = 15)
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$Host.UI.RawUI.WindowTitle = "LevelUpCorp - running continuously (close this window to stop)"
$PID | Out-File -Encoding ascii (Join-Path $root "data\loop.pid")
while ($true) {
    Write-Host ("[{0}] starting cycle" -f (Get-Date -Format "dd MMM HH:mm"))
    try { & (Join-Path $PSScriptRoot "run_once.ps1") } catch { Write-Host "cycle error: $_" }
    Write-Host ("[{0}] cycle done; next in {1} min" -f (Get-Date -Format "dd MMM HH:mm"), $Minutes)
    Start-Sleep -Seconds ($Minutes * 60)
}
