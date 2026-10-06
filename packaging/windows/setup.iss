#ifndef BundleDir
  #error BundleDir is required
#endif
#ifndef ReleaseId
  #error ReleaseId is required
#endif
#ifndef OutputDir
  #error OutputDir is required
#endif
[Setup]
AppId={{E28E15A7-694D-4A82-9C59-8776F169FAB4}
AppName=WMS Desktop
AppVersion=0.1.0
AppVerName=WMS Desktop {#ReleaseId}
VersionInfoVersion=0.1.0.0
DefaultDirName={localappdata}\Programs\WMS\{#ReleaseId}
UsePreviousAppDir=no
DisableDirPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64os
ArchitecturesInstallIn64BitMode=x64os
MinVersion=10.0
AppMutex=Local\WMSDesktopRunning
SetupMutex=Local\WMSDesktopSetup
CloseApplications=no
RestartApplications=no
DisableProgramGroupPage=yes
OutputDir={#OutputDir}
OutputBaseFilename=WMS-Setup-{#ReleaseId}-x64
Compression=lzma2
SolidCompression=yes
UninstallDisplayIcon={app}\WMS.exe
WizardStyle=modern
#ifdef WmsSignedBuild
SignTool=WmsSign
SignedUninstaller=yes
#endif

[Files]
Source: "{#BundleDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userprograms}\WMS Desktop"; Filename: "{app}\WMS.exe"; WorkingDir: "{app}"
Name: "{userdesktop}\WMS Desktop"; Filename: "{app}\WMS.exe"; WorkingDir: "{app}"

[Run]
Filename: "{app}\WMS.exe"; Description: "Mở WMS Desktop"; Flags: postinstall nowait skipifsilent

; No UninstallDelete, cache reset, config overwrite, startup task or forced process kill.
; Old app versions and %LOCALAPPDATA%\wms-lan are intentionally preserved.
