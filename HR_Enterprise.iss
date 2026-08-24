#define MyAppName "HR Enterprise"
#define MyAppVersion "10.0"
#define MyAppExeName "HR Enterprise.exe"

[Setup]
AppId={{D9BFAE9E-2D53-4C67-A7A7-HR-ENTERPRISE-100}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={autopf}\HR Enterprise
DefaultGroupName=HR Enterprise
OutputDir=installer
OutputBaseFilename=HR Enterprise Setup
Compression=lzma
SolidCompression=yes
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64

[Files]
Source: "dist\HR Enterprise.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "README_V100_AR.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "VERSION.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autodesktop}\HR Enterprise"; Filename: "{app}\HR Enterprise.exe"; WorkingDir: "{app}"
Name: "{group}\HR Enterprise"; Filename: "{app}\HR Enterprise.exe"; WorkingDir: "{app}"

[Run]
Filename: "{app}\HR Enterprise.exe"; Description: "Launch HR Enterprise"; Flags: nowait postinstall skipifsilent
