[CmdletBinding()]
param(
    [string]$ISCC = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    [string]$CertificateThumbprint,
    [ValidateSet('CurrentUser','LocalMachine')][string]$CertificateStore = 'CurrentUser',
    [string]$SignTool,
    [uri]$TimestampUrl = 'http://timestamp.digicert.com',
    [switch]$Unsigned
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($env:OS -ne 'Windows_NT' -or $env:PROCESSOR_ARCHITECTURE -ne 'AMD64') { throw 'Windows x64 build host required' }
if ([bool]$CertificateThumbprint -eq [bool]$Unsigned) { throw 'Choose a certificate thumbprint OR explicitly -Unsigned' }
if (!(Test-Path -LiteralPath $ISCC)) {
    throw 'Install reviewed Inno Setup 6.7.3 and pass -ISCC'
}
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Push-Location $repo
try {
    $env:PYTHONUTF8 = '1'
    $env:PYTHONPATH = $repo
    $commit = (& git rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or (& git status --porcelain)) { throw 'Clean committed checkout required' }
    $releaseId = '0.1.0-' + $commit.Substring(0,12)
    $work = Join-Path $repo ('build\windows-' + [guid]::NewGuid().ToString('N'))
    $output = Join-Path $repo ('dist\windows-' + $releaseId)
    if (Test-Path -LiteralPath $output) { throw 'Output already exists; preserve it and use a new release commit' }
    New-Item -ItemType Directory -Path $work, $output | Out-Null
    # ISCC PE FileVersion can be 0.0.0.0. Ask the actual compiler engine by
    # compiling a no-output probe, not by trusting file metadata or a path name.
    $probe = Join-Path $work 'compiler-probe.iss'
    [IO.File]::WriteAllText($probe, "[Setup]`nAppName=WMS Compiler Probe`nAppVersion=0`nCreateAppDir=no`nUninstallable=no`nOutput=no`n", [Text.UTF8Encoding]::new($false))
    $compilerOutput = & $ISCC /O- $probe 2>&1
    $compilerExit = $LASTEXITCODE
    $compilerOutput | ForEach-Object { Write-Host $_ }
    if ($compilerExit -ne 0 -or ($compilerOutput -join "`n") -notmatch '(?m)^Compiler engine version: Inno Setup 6\.7\.3(\s|$)') {
        throw 'Compiler engine must be exactly Inno Setup 6.7.3; no unpinned compiler fallback'
    }
    & py -3.12 -m venv (Join-Path $work 'venv')
    if ($LASTEXITCODE -ne 0) { throw 'CPython 3.12 x64 with Tk is required' }
    $python = Join-Path $work 'venv\Scripts\python.exe'
    & $python -c "import struct,sys,tkinter; assert struct.calcsize('P')==8 and sys.version_info[:2]==(3,12)"
    if ($LASTEXITCODE -ne 0) { throw 'Interpreter/Tk preflight failed' }
    & $python -m pip install --require-hashes --only-binary=:all: -r packaging/windows/requirements-build-lock.txt
    if ($LASTEXITCODE -ne 0) { throw 'Locked dependency install failed' }
    & $python -m pip check
    if ($LASTEXITCODE -ne 0) { throw 'Dependency consistency failed' }
    & $python -m PyInstaller --noconfirm --clean --distpath (Join-Path $work 'frozen') --workpath (Join-Path $work 'pyinstaller') packaging/windows/WMS.spec
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed' }
    $bundle = Join-Path $work 'frozen\WMS'
    $signing = 'unsigned'
    if (!$Unsigned) {
        if ($CertificateThumbprint -notmatch '^[0-9a-fA-F]{40}$') { throw 'Invalid certificate thumbprint' }
        $cert = Get-Item -LiteralPath "Cert:\$CertificateStore\My\$CertificateThumbprint"
        $codeSigning = @($cert.Extensions | Where-Object { $_.Oid.Value -eq '2.5.29.37' } |
            ForEach-Object { $_.EnhancedKeyUsages } | Where-Object { $_.Value -eq '1.3.6.1.5.5.7.3.3' })
        if (!$cert.HasPrivateKey -or $cert.NotAfter -le (Get-Date) -or $cert.NotBefore -gt (Get-Date) -or
            $codeSigning.Count -eq 0) { throw 'Valid code-signing certificate with private key required' }
        if (!$SignTool -or !(Test-Path -LiteralPath $SignTool)) { throw 'Pass Windows SDK signtool.exe explicitly' }
        if ($TimestampUrl.Scheme -notin @('http','https') -or $TimestampUrl.UserInfo -or $TimestampUrl.Fragment) {
            throw 'Explicit HTTP(S) RFC3161 timestamp endpoint required'
        }
        $signing = 'authenticode'
    }
    function Sign-ReleaseFile([string]$Path) {
        $signArgs = @('sign','/sha1',$CertificateThumbprint,'/s','My','/fd','SHA256','/tr',$TimestampUrl.AbsoluteUri,'/td','SHA256')
        if ($CertificateStore -eq 'LocalMachine') { $signArgs += '/sm' }
        & $SignTool @signArgs $Path
        if ($LASTEXITCODE -ne 0) { throw 'Signing failed' }
        & $SignTool verify /pa /all /tw $Path
        if ($LASTEXITCODE -ne 0) { throw 'Signature verification failed' }
        $signature = Get-AuthenticodeSignature -LiteralPath $Path
        if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Thumbprint -ne $CertificateThumbprint -or !$signature.TimeStamperCertificate) {
            throw 'Unexpected signer, invalid signature or missing timestamp'
        }
    }
    if (!$Unsigned) {
        Sign-ReleaseFile (Join-Path $bundle 'WMS.exe')
        Sign-ReleaseFile (Join-Path $bundle 'WMSHelper.exe')
    }
    & $python scripts/windows_release.py $bundle --signing $signing
    if ($LASTEXITCODE -ne 0) { throw 'Manifest generation failed' }
    # Outside repository cwd and without PYTHONPATH: probe the frozen resources, not source modules.
    $savedPath = $env:PYTHONPATH
    Remove-Item Env:PYTHONPATH
    Push-Location $env:TEMP
    try {
        & (Join-Path $bundle 'WMSHelper.exe') --self-test --report (Join-Path $output 'frozen-smoke.json')
        if ($LASTEXITCODE -ne 0) { throw 'Frozen installed-resource smoke failed' }
    } finally { Pop-Location; $env:PYTHONPATH = $savedPath }
    & $ISCC "/DBundleDir=$bundle" "/DReleaseId=$releaseId" "/DOutputDir=$output" packaging/windows/setup.iss
    if ($LASTEXITCODE -ne 0) { throw 'Installer compilation failed' }
    $setup = Join-Path $output "WMS-Setup-$releaseId-x64.exe"
    if (!$Unsigned) { Sign-ReleaseFile $setup }
    Compress-Archive -LiteralPath $bundle -DestinationPath (Join-Path $output "WMS-$releaseId-x64.zip")
    Copy-Item -LiteralPath (Join-Path $bundle 'manifest.json') -Destination (Join-Path $output 'manifest.json')
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'Test-Install.ps1') -Destination $output
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'Rollback.ps1') -Destination $output
    $checksums = Get-ChildItem -LiteralPath $output -File | Sort-Object Name | ForEach-Object {
        (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant() + '  ' + $_.Name
    }
    [IO.File]::WriteAllLines((Join-Path $output 'SHA256SUMS.txt'), $checksums, [Text.UTF8Encoding]::new($false))
    Write-Host "Built $output ($signing). Windows 10/11 acceptance and hardware remain separate gates."
} finally { Pop-Location }
