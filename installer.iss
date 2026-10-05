#define MyAppName "Mecatech Pointage"
#define MyAppVersion "2.2.3"
#define MyAppPublisher "MECA-TECH ATIA"
#define MyAppExeName "MecatechPointage.exe"

[Setup]
AppId={{D7F6F4F0-7D47-4E65-9D6A-5D3D5E3A2D10}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\Mecatech Pointage
DefaultGroupName={#MyAppName}
OutputDir=installer
OutputBaseFilename=MecatechPointage-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile=mecatech_pointage.ico
UninstallDisplayIcon={app}\{#MyAppExeName}

[Files]
Source: "dist\MecatechPointage\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autodesktop}\Mecatech Pointage"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"
Name: "{group}\Mecatech Pointage"; Filename: "{app}\{#MyAppExeName}"

[Run]
Filename: "netsh.exe"; Parameters: "advfirewall firewall add rule name=""Mecatech Pointage TCP 5001"" dir=in action=allow protocol=TCP localport=5001 profile=private,domain"; Flags: runhidden waituntilterminated
Filename: "netsh.exe"; Parameters: "advfirewall firewall add rule name=""Mecatech Pointage mDNS"" dir=in action=allow protocol=UDP localport=5353 profile=private,domain"; Flags: runhidden waituntilterminated
Filename: "{app}\{#MyAppExeName}"; Description: "Launch Mecatech Pointage"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "netsh.exe"; Parameters: "advfirewall firewall delete rule name=""Mecatech Pointage TCP 5001"""; Flags: runhidden waituntilterminated
Filename: "netsh.exe"; Parameters: "advfirewall firewall delete rule name=""Mecatech Pointage mDNS"""; Flags: runhidden waituntilterminated

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
