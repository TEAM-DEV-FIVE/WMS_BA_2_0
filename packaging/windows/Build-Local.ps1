[CmdletBinding()]
param(
    [string]$ISCC = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    [switch]$Unsigned
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
if (!$Unsigned) { throw 'This build path requires explicit -Unsigned for testing. A trusted release signer is still required for public distribution.' }
if ($env:OS -ne 'Windows_NT') { throw 'Native Windows x64 required' }
$repo=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Push-Location $repo
try {
    $env:PYTHONUTF8='1'
    $env:PYTHONPATH=$repo
    $commit=(& git rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or (& git status --porcelain)) { throw 'Clean committed checkout required' }
    $releaseId='0.1.0-'+$commit.Substring(0,12)
    & "$PSScriptRoot\Build.ps1" -ISCC $ISCC -Unsigned
    if ($LASTEXITCODE -ne 0) { throw 'Original desktop build failed' }
    $output=Join-Path $repo ('dist\windows-local-'+$releaseId)
    if (Test-Path $output) { throw 'Preserve existing output; use a new release commit' }
    $work=Join-Path $repo ('build\local-'+[guid]::NewGuid().ToString('N'))
    $payload=Join-Path $work 'payload'
    New-Item -ItemType Directory -Path $output,$work,$payload | Out-Null
    & py -3.12 -m venv (Join-Path $work 'venv')
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 x64 required' }
    $python=Join-Path $work 'venv\Scripts\python.exe'
    & $python -m pip install --require-hashes --only-binary=:all: -r packaging/windows/requirements-local-lock.txt
    if ($LASTEXITCODE -ne 0) { throw 'Locked local dependencies failed' }
    & $python -m pip check
    if ($LASTEXITCODE -ne 0) { throw 'Dependency consistency failed' }
    & $python -m pytest tests/foundation/test_local_launcher.py -m 'not gui' -q
    if ($LASTEXITCODE -ne 0) { throw 'Local launcher regression failed' }
    & $python scripts/check_windows_local.py (Join-Path $output 'native-local-mysql.json')
    if ($LASTEXITCODE -ne 0) { throw 'Native MySQL launcher acceptance failed' }
    & $python -m PyInstaller --noconfirm --clean --distpath (Join-Path $work 'frozen') --workpath (Join-Path $work 'pyinstaller') packaging/windows/Local.spec
    if ($LASTEXITCODE -ne 0) { throw 'Frozen local server build failed' }
    Move-Item (Join-Path $work 'frozen\WMSLocal') (Join-Path $payload 'server')
    $desktopRelease=Join-Path $repo ('dist\windows-'+$releaseId)
    Expand-Archive -LiteralPath (Join-Path $desktopRelease "WMS-$releaseId-x64.zip") -DestinationPath $payload
    Move-Item (Join-Path $payload 'WMS') (Join-Path $payload 'desktop')
    & $python scripts/local_release.py (Join-Path $payload 'server')
    if ($LASTEXITCODE -ne 0) { throw 'Local manifest failed' }
    $savedPath=$env:PYTHONPATH
    Remove-Item Env:PYTHONPATH
    Push-Location $env:TEMP
    try {
        $p=Start-Process (Join-Path $payload 'server\WMSLocal.exe') -ArgumentList '--self-test','--report',("`""+(Join-Path $output 'local-smoke.json')+"`"") -Wait -PassThru
        if ($p.ExitCode -ne 0) { throw 'Frozen backend resource smoke failed' }
    } finally { Pop-Location; $env:PYTHONPATH=$savedPath }
    & $ISCC "/DBundleDir=$payload" "/DReleaseId=$releaseId" "/DOutputDir=$output" packaging/windows/local_setup.iss
    if ($LASTEXITCODE -ne 0) { throw 'Local installer failed' }
    $installer=Join-Path $output "WMS-MySQL-Setup-$releaseId-x64.exe"
    $install=Start-Process $installer -ArgumentList '/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/CURRENTUSER' -Wait -PassThru
    if ($install.ExitCode -ne 0) { throw 'Local installer silent install failed' }
    $installed=Join-Path $env:LOCALAPPDATA "Programs\WMSLocal\$releaseId"
    $installedExe=Join-Path $installed 'server\WMSLocal.exe'
    if (!(Test-Path $installedExe) -or !(Test-Path (Join-Path $installed 'desktop\WMS.exe'))) { throw 'Installed payload missing' }
    $smoke=Start-Process $installedExe -ArgumentList '--self-test','--report',("`""+(Join-Path $output 'installed-local-smoke.json')+"`"") -Wait -PassThru
    if ($smoke.ExitCode -ne 0) { throw 'Installed backend smoke failed' }
    $uninstall=Start-Process (Join-Path $installed 'unins000.exe') -ArgumentList '/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART' -Wait -PassThru
    if ($uninstall.ExitCode -ne 0) { throw 'Local uninstaller failed' }
    Copy-Item packaging/windows/LOCAL_MYSQL.md (Join-Path $output 'HUONG_DAN.md')
    @{ product='WMS'; commit=$commit; signing='unsigned'; database='fresh only; no business/demo data'; native_install_uninstall='PASS'; native_source_mysql='PASS'; native_resource_smoke='PASS'; windows_10_11_uac='NOT_RUN' } | ConvertTo-Json | Set-Content (Join-Path $output 'release-evidence.json') -Encoding utf8
    $checksums=Get-ChildItem $output -File | Sort-Object Name | ForEach-Object {
        (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()+'  '+$_.Name
    }
    [IO.File]::WriteAllLines((Join-Path $output 'SHA256SUMS.txt'),$checksums,[Text.UTF8Encoding]::new($false))
    Write-Host "Built $output. Unsigned test build; native MySQL and UAC acceptance reported separately."
} finally { Pop-Location }
