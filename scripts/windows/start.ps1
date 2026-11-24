# Start FlipDial in the background (web server and scan worker), then open it in the browser.
#   start.ps1             start and open the browser
#   start.ps1 -NoBrowser  start only
param([switch]$NoBrowser)
. (Join-Path $PSScriptRoot 'common.ps1')

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Stop-WithError 'uv is not installed. Run: winget install --id astral-sh.uv -e, then open a new window.'
}
if (-not (Test-Path $EnvFile)) {
    Stop-WithError "No settings file at $EnvFile. See docs/windows.md to create one."
}
if (@(Get-FlipDialProcesses).Count -gt 0 -and (Test-FlipDialUp)) {
    Write-Host "FlipDial is already running at $Url"
    if (-not $NoBrowser) { Start-Process $Url }
    exit 0
}
if (Test-FlipDialUp) {
    Stop-WithError "Something else is already answering at $Url. Run stop, or change FLIPDIAL_PORT."
}

$webDir = Get-FlipDialSetting 'FLIPDIAL_WEB_DIR' ''
if ($webDir -and -not (Test-Path (Join-Path (Resolve-FromBackend $webDir) 'index.html'))) { Build-WebApp }

$modelUrl = Get-FlipDialSetting 'FLIPDIAL_MODEL_URL' 'http://127.0.0.1:11434'
try {
    Invoke-WebRequest "$modelUrl/api/tags" -UseBasicParsing -TimeoutSec 3 | Out-Null
} catch {
    Write-Warning "Ollama isn't answering at $modelUrl. FlipDial will start, but cards wait unread until Ollama runs."
}

New-Item -ItemType Directory -Force -Path $LogDir, $RunDir | Out-Null
$uv = (Get-Command uv).Source

function Start-Part([string]$Command, [string]$Name) {
    $out = Join-Path $LogDir "$Name.log"
    $err = Join-Path $LogDir "$Name.errors.log"
    foreach ($f in $out, $err) { if (Test-Path $f) { Move-Item $f "$f.previous" -Force } }
    Start-Process -FilePath $uv -ArgumentList @('run', 'flipdial', $Command) -WorkingDirectory $Backend `
        -WindowStyle Hidden -RedirectStandardOutput $out -RedirectStandardError $err -PassThru
}

Write-Step 'Starting FlipDial'
$server = Start-Part 'serve' 'server'
$worker = Start-Part 'worker' 'worker'
@{ server = $server.Id; worker = $worker.Id } | ConvertTo-Json | Set-Content $PidFile

$deadline = (Get-Date).AddSeconds(90)  # the first start can take a while
while (-not (Test-FlipDialUp)) {
    if ($server.HasExited -or (Get-Date) -gt $deadline) {
        Write-Host "FlipDial didn't start. Last lines of its logs ($LogDir):" -ForegroundColor Red
        foreach ($f in 'server.errors.log', 'server.log') {
            Get-Content (Join-Path $LogDir $f) -Tail 15 -ErrorAction SilentlyContinue
        }
        & (Join-Path $PSScriptRoot 'stop.ps1') -Quiet
        exit 1
    }
    Start-Sleep -Seconds 1
}

Write-Host "FlipDial is running at $Url" -ForegroundColor Green
Write-Host "Logs: $LogDir"
if (-not $NoBrowser) { Start-Process $Url }
