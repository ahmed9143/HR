; ============================================================================
; HR Enterprise — Windows installer (Inno Setup 6)
;
; Built by GitHub Actions (.github/workflows/windows-build.yml) or locally with
; BUILD_WINDOWS.bat. The version is injected on the command line:
;     iscc /DMyAppVersion=18.0.0 HR_Enterprise.iss
;
; Changes from the previous script:
;   * Packages the ONEDIR build (dist\HR Enterprise\*), which starts instantly;
;     the old script shipped a onefile EXE that unpacked itself to %TEMP% on
;     every launch.
;   * No longer references "dist\network\HR Enterprise Network Server.exe",
;     which no build step produced — the installer could not compile.
;   * Version comes from VERSION.txt instead of a stale hard-coded 11.2.6.
;   * User data in %PROGRAMDATA%\HR Enterprise\Data is NEVER removed by an
;     uninstall or an upgrade. Removing an HR database on uninstall would be a
;     data-loss event.
; ============================================================================

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0-dev"
#endif
#define MyAppName "HR Enterprise"
#define MyAppExeName "HR Enterprise.exe"
#define MyAppPublisher "HR Enterprise"

[Setup]
; Keep this AppId unchanged forever: it is how Windows recognises an upgrade
; of the same product instead of a second installation side by side.
AppId={{D9BFAE9E-2D53-4C67-A7A7-1A2B3C4D5E6F}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
VersionInfoVersion={#MyAppVersion}
DefaultDirName={autopf}\HR Enterprise
DefaultGroupName=HR Enterprise
DisableProgramGroupPage=yes
OutputDir=installer
OutputBaseFilename=HR-Enterprise-Setup-{#MyAppVersion}
SetupIconFile=HR_Enterprise.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/max
SolidCompression=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
; Close a running copy before overwriting its files during an upgrade.
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "arabic"; MessagesFile: "compiler:Languages\Arabic.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "lanfirewall"; Description: "Allow other PCs on the private network to connect (network server mode)"; GroupDescription: "Network:"; Flags: unchecked

[Dirs]
; Create the data directory with users-modify rights so the app can write its
; database when launched by a standard (non-admin) user.
Name: "{commonappdata}\HR Enterprise\Data"; Permissions: users-modify; Flags: uninsneveruninstall

[Files]
Source: "dist\HR Enterprise\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "VERSION.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "docs\RUNBOOK.md"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "README_FIRST_AR.md"; DestDir: "{app}\docs"; Flags: ignoreversion

[Icons]
Name: "{group}\HR Enterprise"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{group}\Uninstall HR Enterprise"; Filename: "{uninstallexe}"
Name: "{autodesktop}\HR Enterprise"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
; Firewall rules only when the user opts into network mode, and only on the
; Private profile — never Public.
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""HR Enterprise HTTPS"" dir=in action=allow protocol=TCP localport=8899-8920 profile=private"; Flags: runhidden; Tasks: lanfirewall
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""HR Enterprise Discovery"" dir=in action=allow protocol=UDP localport=8898 profile=private"; Flags: runhidden; Tasks: lanfirewall
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,HR Enterprise}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""HR Enterprise HTTPS"""; Flags: runhidden; RunOnceId: "fw_tcp"
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""HR Enterprise Discovery"""; Flags: runhidden; RunOnceId: "fw_udp"

[Messages]
FinishedLabel=Setup has finished installing HR Enterprise.%n%nFirst login:%n    user: admin%n    password: Admin@12345%nYou will be asked to change the password immediately.%n%nYour data is stored in C:\ProgramData\HR Enterprise\Data and is kept when you uninstall or upgrade.
