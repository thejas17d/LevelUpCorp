# Runs one LevelUpCorp cycle. Used by the scheduled task (scripts\schedule_task.ps1).
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
& .\.venv\Scripts\python.exe -m levelup run --once
