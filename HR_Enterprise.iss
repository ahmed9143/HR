#define MyAppName "HR Enterprise"
#define MyAppVersion "11.1.3"
#define MyAppExeName "HR Enterprise.exe"

[Setup]
AppId={{D9BFAE9E-2D53-4C67-A7A7-1A2B3C4D5E6F}}
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
Source: "dist\network\HR Enterprise Network Server.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "VERSION.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "HR_Enterprise.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autodesktop}\HR Enterprise"; Filename: "{app}\HR Enterprise.exe"; WorkingDir: "{app}"; IconFilename: "{app}\HR_Enterprise.ico"
Name: "{group}\HR Enterprise"; Filename: "{app}\HR Enterprise.exe"; WorkingDir: "{app}"; IconFilename: "{app}\HR_Enterprise.ico"
Name: "{group}\HR Enterprise Network Server"; Filename: "{app}\HR Enterprise Network Server.exe"; WorkingDir: "{app}"; IconFilename: "{app}\HR_Enterprise.ico"

[Run]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""HR Enterprise Network TCP"" dir=in action=allow protocol=TCP localport=8899-8920 profile=private"; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""HR Enterprise Discovery UDP"" dir=in action=allow protocol=UDP localport=8898 profile=private"; Flags: runhidden
Filename: "{app}\HR Enterprise.exe"; Description: "Launch HR Enterprise"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""HR Enterprise Network TCP"""; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""HR Enterprise Discovery UDP"""; Flags: runhidden
