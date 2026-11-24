# Shared helpers for the FlipDial Windows scripts. Works in Windows PowerShell 5.1 and PowerShell 7.
$ErrorActionPreference = 'Stop'
# Windows PowerShell 5.1 may default to old TLS versions that GitHub refuses.
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

$Root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Backend = Join-Path $Root 'backend'
$Web = Join-Path $Root 'web'
$EnvFile = Join-Path $Backend '.env'

function Write-Step([string]$Text) { Write-Host "==> $Text" -ForegroundColor Cyan }

function Stop-WithError([string]$Text) {
    Write-Host $Text -ForegroundColor Red
    exit 1
}

function Get-FlipDialSetting([string]$Name, [string]$Default) {
    # Same order FlipDial itself uses: environment variable, then backend\.env, then default.
    $value = [Environment]::GetEnvironmentVariable($Name)
    if ($value) { return $value }
    if (Test-Path $EnvFile) {
        foreach ($line in Get-Content $EnvFile) {
            $t = $line.Trim()
            if ($t -eq '' -or $t.StartsWith('#')) { continue }
            $i = $t.IndexOf('=')
            if ($i -gt 0 -and $t.Substring(0, $i).Trim() -eq $Name) {
                return $t.Substring($i + 1).Trim().Trim('"').Trim("'")
            }
        }
    }
    return $Default
}

function Resolve-FromBackend([string]$Path) {
    if ([System.IO.Path]::IsPathRooted($Path)) { return $Path }
    return [System.IO.Path]::GetFullPath((Join-Path $Backend $Path))
}

$DataDir = Resolve-FromBackend (Get-FlipDialSetting 'FLIPDIAL_DATA_DIR' './data')
$LogDir = Join-Path $DataDir 'logs'
$RunDir = Join-Path $DataDir 'run'
$PidFile = Join-Path $RunDir 'flipdial.pids.json'
$HostName = Get-FlipDialSetting 'FLIPDIAL_HOST' '127.0.0.1'
if ($HostName -eq '0.0.0.0' -or $HostName -eq '::') { $HostName = '127.0.0.1' }
$Url = "http://${HostName}:$(Get-FlipDialSetting 'FLIPDIAL_PORT' '8080')"

function Invoke-Checked {
    # Run a program and stop if it fails (PowerShell doesn't do this for programs by itself).
    param([string]$What, [string]$Exe, [string[]]$Arguments, [string]$Dir = $Root)
    Push-Location $Dir
    try {
        & $Exe @Arguments
        if ($LASTEXITCODE -ne 0) { Stop-WithError "$What failed (exit code $LASTEXITCODE)." }
    } finally { Pop-Location }
}

function Get-FlipDialProcesses {
    # Processes recorded by start.ps1 that are still running and are really ours (a recycled
    # process ID belonging to some other program is ignored, never stopped).
    if (-not (Test-Path $PidFile)) { return @() }
    $ids = Get-Content $PidFile -Raw | ConvertFrom-Json
    $found = @()
    foreach ($name in 'server', 'worker') {
        $id = $ids.$name
        if (-not $id) { continue }
        $p = Get-Process -Id $id -ErrorAction SilentlyContinue
        if ($p -and @('uv', 'python', 'flipdial') -contains $p.ProcessName.ToLower()) {
            $found += [pscustomobject]@{ Role = $name; Process = $p }
        }
    }
    return $found
}

function Test-FlipDialUp {
    try {
        $r = Invoke-WebRequest "$Url/healthz" -UseBasicParsing -TimeoutSec 2
        return $r.StatusCode -eq 200
    } catch { return $false }
}

function Build-WebApp {
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
        Stop-WithError 'Node.js is needed to build the web app. Run: winget install OpenJS.NodeJS, then open a new window.'
    }
    Write-Step 'Building the web app'
    Invoke-Checked 'npm ci' 'npm' @('ci', '--no-audit', '--no-fund') $Web
    Invoke-Checked 'npm run build' 'npm' @('run', 'build') $Web
}
