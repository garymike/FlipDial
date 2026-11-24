# Stop FlipDial (web server and scan worker) started by start.ps1.
param([switch]$Quiet)
. (Join-Path $PSScriptRoot 'common.ps1')

$running = @(Get-FlipDialProcesses)
if ($running.Count -eq 0) {
    if (-not $Quiet) { Write-Host 'FlipDial is not running.' }
    if (Test-Path $PidFile) { Remove-Item $PidFile }
    exit 0
}
foreach ($r in $running) {
    if (-not $Quiet) { Write-Step "Stopping the $($r.Role)" }
    # /T also stops the Python process that uv started for it.
    & taskkill.exe /PID $r.Process.Id /T /F | Out-Null
}
Remove-Item $PidFile -ErrorAction SilentlyContinue
if (-not $Quiet) { Write-Host 'FlipDial stopped.' -ForegroundColor Green }
