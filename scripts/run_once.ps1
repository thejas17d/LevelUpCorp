# Runs one LevelUpCorp cycle. Used by the scheduled task (scripts\schedule_task.ps1).
# Afterwards, if RESUME_REPO is set in .env, refreshes "Applications/applications on <today>.html"
# in that git repo and pushes only that file.
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
& .\.venv\Scripts\python.exe -m levelup run --once

$repoLine = Select-String -Path ".env" -Pattern '^RESUME_REPO=(.+)$' -ErrorAction SilentlyContinue
if ($repoLine) {
    $repo = $repoLine.Matches[0].Groups[1].Value.Trim()
    $git = "C:\Program Files\Git\cmd\git.exe"
    if ((Test-Path $repo) -and (Test-Path $git)) {
        $day = Get-Date -Format "yyyy-MM-dd"
        $rel = "Applications/applications on $day.html"
        New-Item -ItemType Directory -Force (Join-Path $repo "Applications") | Out-Null
        & .\.venv\Scripts\python.exe scripts\daily_summary.py $day (Join-Path $repo $rel)
        & $git -C $repo pull -q --rebase
        & $git -C $repo add -- $rel
        & $git -C $repo diff --cached --quiet
        if ($LASTEXITCODE -ne 0) {
            & $git -C $repo -c user.name="Thejas M" -c user.email="thejas17d@users.noreply.github.com" commit -q -m "applications: update log for $day"
            & $git -C $repo push -q
        }
    }
}
