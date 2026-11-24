# Update FlipDial to the newest published release, then start it again.
#   update.ps1                 newest published release (or the latest code, if none is published yet)
#   update.ps1 -Tag v1.2.0     a specific release
#   update.ps1 -Main           the latest code on main (for development)
#   update.ps1 -NoStart        update only
# A release is installed only if its Sigstore signature proves it was built by this repository's
# Release workflow from the exact commit being installed. If the new version doesn't start, the
# previous one is put back.
param([string]$Tag, [switch]$Main, [switch]$NoStart, [switch]$FromApp, [switch]$Detached)
. (Join-Path $PSScriptRoot 'common.ps1')

if ($FromApp -and -not $Detached) {
    # Started by the app: relaunch outside the app's process tree so stopping the app
    # doesn't stop this updater too.
    Start-Process powershell.exe -WindowStyle Hidden -ArgumentList @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$PSCommandPath`"", '-Tag', $Tag, '-FromApp', '-Detached'
    )
    exit 0
}

New-Item -ItemType Directory -Force -Path $LogDir, $RunDir | Out-Null
if ($FromApp) { Start-Transcript -Path (Join-Path $LogDir 'update.log') -Force | Out-Null }
$lock = Join-Path $RunDir 'update.lock'
if ((Test-Path $lock) -and ((Get-Item $lock).LastWriteTime -gt (Get-Date).AddMinutes(-15))) {
    Stop-WithError 'An update is already running.'
}
Set-Content $lock (Get-Date -Format o)

function Get-LatestReleaseTag([string]$Repo) {
    try {
        $r = Invoke-RestMethod "https://api.github.com/repos/$Repo/releases/latest" -Headers @{ Accept = 'application/vnd.github+json' } -TimeoutSec 15
        return [string]$r.tag_name
    } catch {
        if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq 404) { return $null }
        Stop-WithError "Couldn't reach GitHub to check for releases: $($_.Exception.Message)"
    }
}

function Test-ReleaseSignature([string]$Repo, [string]$Release, [string]$Commit) {
    Write-Step "Checking the signature of $Release"
    $dir = Join-Path $RunDir "verify-$Release"
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    foreach ($f in 'SHA256SUMS', 'SHA256SUMS.sigstore.json') {
        try {
            Invoke-WebRequest "https://github.com/$Repo/releases/download/$Release/$f" -OutFile (Join-Path $dir $f) -UseBasicParsing -TimeoutSec 60
        } catch {
            Stop-WithError "Couldn't download $f for $Release, so it can't be verified. Nothing was changed."
        }
    }
    $uv = (Get-Command uv).Source
    & $uv tool run --from sigstore==4.6.0 sigstore verify github `
        --bundle (Join-Path $dir 'SHA256SUMS.sigstore.json') --repository $Repo --sha $Commit --name Release `
        (Join-Path $dir 'SHA256SUMS')
    if ($LASTEXITCODE -ne 0) {
        Stop-WithError "The signature of $Release doesn't match this repository's release workflow and commit. Nothing was changed."
    }
}

function Install-Version([string]$Commit) {
    Invoke-Checked 'git checkout' 'git' @('-C', $Root, 'checkout', '--quiet', '--detach', $Commit)
    Write-Step 'Updating the Python parts'
    Invoke-Checked 'uv sync' $((Get-Command uv).Source) @('sync', '--frozen') $Backend
    if (Get-FlipDialSetting 'FLIPDIAL_WEB_DIR' '') { Build-WebApp }
}

try {
    foreach ($tool in 'git', 'uv') {
        if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { Stop-WithError "$tool is not installed. See docs/windows.md." }
    }
    $repo = Get-FlipDialSetting 'FLIPDIAL_UPDATE_REPO' 'garymike/FlipDial'
    $changes = & git -C $Root status --porcelain --untracked-files=no
    if ($changes) {
        Stop-WithError "Files in $Root were changed by hand, so updating would overwrite them. Undo those changes (git -C `"$Root`" stash) and try again."
    }

    Write-Step 'Checking for updates'
    Invoke-Checked 'git fetch' 'git' @('-C', $Root, 'fetch', '--quiet', '--tags', '--force', 'origin', 'main')
    if (-not $Main -and -not $Tag) {
        $Tag = Get-LatestReleaseTag $repo
        if (-not $Tag) {
            Write-Host 'No release has been published yet, so updating to the latest code instead.'
            $Main = $true
        }
    }
    if ($Main) {
        $target = 'origin/main'
    } else {
        if ($Tag -notmatch '^v\d+\.\d+\.\d+([-.]?(rc|a|b)\.?\d+)?$') { Stop-WithError "Not a release version: $Tag" }
        $target = $Tag
    }
    $commit = (& git -C $Root rev-parse "$target^{commit}").Trim()
    if ($LASTEXITCODE -ne 0 -or -not $commit) { Stop-WithError "Couldn't find $target." }
    $before = (& git -C $Root rev-parse HEAD).Trim()

    if ($commit -eq $before) {
        Write-Host 'Already up to date.' -ForegroundColor Green
    } else {
        if (-not $Main) { Test-ReleaseSignature $repo $Tag $commit }
        & (Join-Path $PSScriptRoot 'stop.ps1') -Quiet
        $label = if ($Main) { 'the latest code' } else { $Tag }
        Write-Step "Installing $label"
        Install-Version $commit
        Write-Host "Updated $($before.Substring(0, 7)) -> $($commit.Substring(0, 7))." -ForegroundColor Green
    }

    if (-not $NoStart) {
        & (Join-Path $PSScriptRoot 'start.ps1') -NoBrowser:$FromApp
        if ($LASTEXITCODE -ne 0 -and $commit -ne $before) {
            Write-Host 'The new version did not start. Putting the previous version back.' -ForegroundColor Yellow
            Install-Version $before
            & (Join-Path $PSScriptRoot 'start.ps1') -NoBrowser:$FromApp
            Stop-WithError "Update rolled back. Details are in $LogDir."
        }
    }
} finally {
    Remove-Item $lock -ErrorAction SilentlyContinue
    if ($FromApp) { Stop-Transcript | Out-Null }
}
