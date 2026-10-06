[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Bundle,
    [Parameter(Mandatory)][string]$MakeAppx,
    [Parameter(Mandatory)][string]$Python,
    [Parameter(Mandatory)][string]$OutputDirectory,
    [string]$IdentityFile,
    [string]$Version = '2.1.0.0',
    [switch]$TestIdentity
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($env:OS -ne 'Windows_NT') { throw 'Windows SDK build host required' }
if ([bool]$IdentityFile -eq [bool]$TestIdentity) { throw 'Provide Partner Center identity OR explicit TestIdentity' }
if (Test-Path -LiteralPath $OutputDirectory) { throw 'Use a new output directory' }
if (!(Test-Path -LiteralPath $MakeAppx)) { throw 'Windows SDK MakeAppx.exe required' }
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$Bundle = (Resolve-Path -LiteralPath $Bundle).Path
$MakeAppx = (Resolve-Path -LiteralPath $MakeAppx).Path
$Python = (Resolve-Path -LiteralPath $Python).Path
if ($IdentityFile) { $IdentityFile = (Resolve-Path -LiteralPath $IdentityFile).Path }
New-Item -ItemType Directory -Path $OutputDirectory | Out-Null
$output = (Resolve-Path -LiteralPath $OutputDirectory).Path
$stage = Join-Path $output 'stage'
$report = Join-Path $output 'store-package.json'
$savedPythonPath = $env:PYTHONPATH
Push-Location $repo
try {
    $env:PYTHONPATH = $repo
    $argsStage = @('scripts/store_package.py','--bundle',$Bundle,'--stage',$stage,'--report',$report,'--version',$Version)
    if ($TestIdentity) { $argsStage += '--test-identity' } else { $argsStage += @('--identity',$IdentityFile) }
    & $Python @argsStage
    if ($LASTEXITCODE -ne 0) { throw 'Store staging failed' }
    $suffix = if ($TestIdentity) { '-TEST-IDENTITY' } else { '' }
    $package = Join-Path $output "WMS-Store-$Version-x64$suffix.msix"
    & $MakeAppx pack /d $stage /p $package
    if ($LASTEXITCODE -ne 0) { throw 'MakeAppx validation/pack failed' }
    $unpacked = Join-Path $output 'unpacked'
    & $MakeAppx unpack /p $package /d $unpacked
    if ($LASTEXITCODE -ne 0) { throw 'MakeAppx unpack failed' }
    $verifyCode = 'from pathlib import Path; from apps.desktop.bundle import verify_manifest; import sys; verify_manifest(Path(sys.argv[1])); print("PASS MSIX payload hashes")'
    & $Python -c $verifyCode (Join-Path $unpacked 'App')
    if ($LASTEXITCODE -ne 0) { throw 'MSIX payload changed' }
    $record = Get-Content -LiteralPath $report -Raw | ConvertFrom-Json
    $record | Add-Member -NotePropertyName sdk_pack_unpack -NotePropertyValue 'PASS'
    $record | Add-Member -NotePropertyName sha256 -NotePropertyValue (Get-FileHash -LiteralPath $package).Hash.ToLowerInvariant()
    $record | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $report -Encoding utf8
    $record.sha256 + '  ' + (Split-Path $package -Leaf) | Set-Content (Join-Path $output 'SHA256SUMS.txt') -Encoding ascii
    Write-Host 'MSIX created for Partner Center. Not Store-signed, not certified, not a public sideload installer.'
} finally {
    Pop-Location
    $env:PYTHONPATH = $savedPythonPath
}
