[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Installer,
    [Parameter(Mandatory)][ValidatePattern('^[0-9a-fA-F]{64}$')][string]$ExpectedSha256,
    [Parameter(Mandatory)][string]$VersionDirectory,
    [string]$ExpectedSigner,
    [switch]$AllowUnsigned,
    [string]$PreviousInstaller,
    [string]$PreviousSha256
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($env:OS -ne 'Windows_NT') { throw 'Run on a clean Windows 10/11 x64 test account' }
if (Get-Process -Name WMS -ErrorAction SilentlyContinue) { throw 'Close WMS normally first' }
$data = if ($env:WMS_LOCAL_DATA_DIR) { $env:WMS_LOCAL_DATA_DIR } else { Join-Path $env:LOCALAPPDATA 'wms-lan' }
function Data-Inventory {
    $result = @{}
    if (Test-Path -LiteralPath $data) {
        Get-ChildItem -LiteralPath $data -File -Recurse | ForEach-Object {
            $result[$_.FullName] = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
        }
    }
    return $result
}
function Install-Verified([string]$Path, [string]$Hash) {
    if ((Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash -ne $Hash) { throw 'Installer hash mismatch' }
    $signature = Get-AuthenticodeSignature -LiteralPath $Path
    if ($ExpectedSigner) {
        if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Thumbprint -ne $ExpectedSigner) { throw 'Installer signer mismatch' }
    } elseif (!$AllowUnsigned -or $signature.Status -ne 'NotSigned') { throw 'Specify expected signer, or explicitly permit unsigned test build' }
    $process = Start-Process -FilePath $Path -ArgumentList '/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART' -Wait -PassThru
    if ($process.ExitCode -ne 0) { throw "Installer failed: $($process.ExitCode)" }
}
if ($PreviousInstaller) {
    if (!$PreviousSha256) { throw 'Previous installer checksum required' }
    Install-Verified $PreviousInstaller $PreviousSha256
    Write-Host 'Baseline installed. Seed drafts and UNKNOWN/SENDING using the acceptance procedure before upgrade.'
    Read-Host 'Close baseline app after preparing test data; press Enter to upgrade' | Out-Null
}
$before = Data-Inventory
Install-Verified $Installer $ExpectedSha256
$after = Data-Inventory
if ($before.Count -ne $after.Count) { throw 'Installer altered local-data file inventory' }
foreach ($name in $before.Keys) { if (!$after.ContainsKey($name) -or $before[$name] -ne $after[$name]) { throw 'Installer changed local data' } }
$helper = Join-Path $VersionDirectory 'WMSHelper.exe'
& $helper --check-cache $data
if ($LASTEXITCODE -ne 0) { throw 'Cache compatibility check failed; preserve original data' }
& $helper --self-test --report (Join-Path $env:TEMP 'wms-installed-smoke.json')
if ($LASTEXITCODE -ne 0) { throw 'Installed smoke failed' }
Write-Host 'PASS installation preserved bytes; resources and cache preflight passed. Login/MFA/API recovery/printing/scanner/reboot/DPI still require acceptance steps.'
