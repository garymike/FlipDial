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
    # A child can exit on its own while the tree is being stopped; taskkill then reports
    # an error for it even though everything stopped. Check what's left instead.
    & taskkill.exe /PID $r.Process.Id /T /F 2>$null | Out-Null
}
Remove-Item $PidFile -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 500
$left = @(Get-FlipDialProcesses)
if ($left.Count) {
    Write-Host "Couldn't stop: $(($left | ForEach-Object { $_.Role }) -join ', ')" -ForegroundColor Red
    exit 1
}
$global:LASTEXITCODE = 0
if (-not $Quiet) { Write-Host 'FlipDial stopped.' -ForegroundColor Green }
