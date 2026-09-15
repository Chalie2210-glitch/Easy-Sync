#ifndef AppVersion
  #error AppVersion must be supplied by build.ps1
#endif
#define AppName "Easy Sync"

[Setup]
AppId={{D59879B2-AD07-4DA2-89C3-C29B67228C56}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Chalie2210-glitch
AppPublisherURL=https://github.com/Chalie2210-glitch/Easy-Sync
AppSupportURL=https://github.com/Chalie2210-glitch/Easy-Sync/issues
AppUpdatesURL=https://github.com/Chalie2210-glitch/Easy-Sync/releases/latest
DefaultDirName={localappdata}\Programs\Easy Sync
DefaultGroupName=Easy Sync
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
OutputDir=..\dist\release
OutputBaseFilename=Easy-Sync-Setup-{#AppVersion}-x64
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\EasySync.exe
AppMutex=EasySync.Desktop.v1
CloseApplications=no
RestartApplications=no
UsePreviousAppDir=yes
UsePreviousTasks=yes
Uninstallable=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"
Name: "shellmenu"; Description: "Register Explorer audio/folder and Send to menus"
Name: "wwisemenu"; Description: "Register Wwise Easy Sync menus"

[Files]
Source: "..\dist\EasySync\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\build\ThirdPartyLicenses\*"; DestDir: "{app}\ThirdPartyLicenses"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Easy Sync"; Filename: "{app}\EasySync.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\Easy Sync"; Filename: "{app}\EasySync.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\EasySync.exe"; Parameters: "--register-integration shell"; Flags: runhidden waituntilterminated; Tasks: shellmenu
Filename: "{app}\EasySync.exe"; Parameters: "--register-integration wwise"; Flags: runhidden waituntilterminated; Tasks: wwisemenu
Filename: "{app}\EasySync.exe"; Description: "Launch Easy Sync"; Flags: nowait postinstall skipifsilent unchecked

[UninstallRun]
Filename: "{app}\EasySync.exe"; Parameters: "--unregister-integration"; Flags: runhidden waituntilterminated; RunOnceId: "UnregisterEasySync"

; Settings in APPDATA and logs in LOCALAPPDATA are intentionally retained.
