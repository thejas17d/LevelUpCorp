# LevelUpCorp one-time setup (safe to re-run).
# Usage (from the project folder):  powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host "1/4 Checking Python..."
$py = (Get-Command python -ErrorAction SilentlyContinue)
if (-not $py) { Write-Host "Python not found. Install Python 3.10+ from https://www.python.org/downloads/ (tick 'Add to PATH') and re-run."; exit 1 }
python --version

Write-Host "2/4 Creating virtual environment (.venv) and installing packages..."
if (-not (Test-Path ".venv\Scripts\python.exe")) { python -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install --quiet --upgrade pip
& .\.venv\Scripts\python.exe -m pip install --quiet -r requirements.txt

Write-Host "3/4 Installing the browser used to fill application forms (~150 MB, first time only)..."
& .\.venv\Scripts\python.exe -m playwright install chromium

Write-Host "4/4 Creating your settings files..."
if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env"; Write-Host "   created .env  -> add your API key and email app password" }
else { Write-Host "   .env already exists (kept)" }
if (-not (Test-Path "config.yaml")) { Copy-Item "config.example.yaml" "config.yaml"; Write-Host "   created config.yaml -> fill the applicant section" }
else { Write-Host "   config.yaml already exists (kept)" }

Write-Host ""
Write-Host "Done. Next (see HANDOFF.md):"
Write-Host "  notepad .env"
Write-Host "  notepad config.yaml"
Write-Host "  .\.venv\Scripts\python -m levelup setup --resume `"C:\path\to\resume.pdf`""
Write-Host "  .\.venv\Scripts\python -m levelup doctor"
