# Update FlipDial: stop it, get the latest code, refresh the Python and web parts, start it again.
#   update.ps1           update and start
#   update.ps1 -NoStart  update only
param([switch]$NoStart)
. (Join-Path $PSScriptRoot 'common.ps1')

foreach ($tool in 'git', 'uv') {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { Stop-WithError "$tool is not installed. See docs/windows.md." }
}

& (Join-Path $PSScriptRoot 'stop.ps1') -Quiet

Write-Step 'Getting the latest version'
$changes = & git -C $Root status --porcelain --untracked-files=no
if ($changes) {
    Stop-WithError "Files in $Root were changed by hand, so the update would overwrite them. Undo those changes (git -C `"$Root`" stash) and run update again."
}
$before = (& git -C $Root rev-parse HEAD).Trim()
Invoke-Checked 'git pull' 'git' @('-C', $Root, 'pull', '--ff-only')
$after = (& git -C $Root rev-parse HEAD).Trim()

Write-Step 'Updating the Python parts'
Invoke-Checked 'uv sync' $((Get-Command uv).Source) @('sync') $Backend

$webDir = Get-FlipDialSetting 'FLIPDIAL_WEB_DIR' ''
if ($webDir) { Build-WebApp }

if ($before -eq $after) { Write-Host 'Already up to date.' -ForegroundColor Green }
else { Write-Host "Updated $($before.Substring(0, 7)) -> $($after.Substring(0, 7))." -ForegroundColor Green }

if (-not $NoStart) { & (Join-Path $PSScriptRoot 'start.ps1') }
