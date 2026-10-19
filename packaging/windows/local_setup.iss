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
AppId={{013D7DE4-2088-4684-A97A-00B20B977D67}
AppName=WMS MySQL Local
AppVersion=0.1.0
AppVerName=WMS MySQL Local {#ReleaseId}
DefaultDirName={localappdata}\Programs\WMSLocal\{#ReleaseId}
UsePreviousAppDir=no
DisableDirPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64os
ArchitecturesInstallIn64BitMode=x64os
MinVersion=10.0
AppMutex=Local\WMSDesktopRunning,Local\WMSLocalRunning
CloseApplications=no
RestartApplications=no
DisableProgramGroupPage=yes
OutputDir={#OutputDir}
OutputBaseFilename=WMS-MySQL-Setup-{#ReleaseId}-x64
Compression=lzma2
SolidCompression=yes
UninstallDisplayIcon={app}\server\WMSLocal.exe
WizardStyle=modern
SetupIconFile=..\..\apps\desktop\assets\wms-app-icon.ico
#ifdef WmsSignedBuild
SignTool=WmsSign
SignedUninstaller=yes
#endif
[Files]
Source: "{#BundleDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{userprograms}\WMS MySQL Local"; Filename: "{app}\server\WMSLocal.exe"; WorkingDir: "{app}\server"
Name: "{userdesktop}\WMS MySQL Local"; Filename: "{app}\server\WMSLocal.exe"; WorkingDir: "{app}\server"
[Run]
Filename: "{app}\server\WMSLocal.exe"; Description: "Mở WMS và kiểm tra MySQL"; Flags: postinstall nowait skipifsilent
; Server data and existing LAN client configuration are outside {app}; never removed.
