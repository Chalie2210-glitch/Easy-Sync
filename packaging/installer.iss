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
; An x64 in-process shell module requires native x64 Explorer (not ARM64).
ArchitecturesAllowed=x64os
ArchitecturesInstallIn64BitMode=x64os
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
Name: "shellmenu"; Description: "Register Explorer menus (Windows 11: Show more options)"
Name: "wwisemenu"; Description: "Register Wwise Easy Sync menus"

[Files]
Source: "..\dist\EasySync\*"; DestDir: "{app}"; Excludes: "_internal\EasySyncShell-*.dll"; Flags: ignoreversion recursesubdirs createallsubdirs
; Content-addressed DLL names let upgrades install without replacing a module
; loaded by Explorer. Identical modules are retained; uninstall can defer removal.
Source: "..\dist\EasySync\_internal\EasySyncShell-*.dll"; DestDir: "{app}\_internal"; Flags: onlyifdoesntexist uninsrestartdelete
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\build\ThirdPartyLicenses\*"; DestDir: "{app}\ThirdPartyLicenses"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Easy Sync"; Filename: "{app}\EasySync.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\Easy Sync"; Filename: "{app}\EasySync.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\EasySync.exe"; Description: "Launch Easy Sync"; Flags: nowait postinstall skipifsilent unchecked

[UninstallRun]
Filename: "{app}\EasySync.exe"; Parameters: "--unregister-integration"; Flags: runhidden waituntilterminated; RunOnceId: "UnregisterEasySync"

; Settings in APPDATA and logs in LOCALAPPDATA are intentionally retained.

[Code]
var
  IntegrationFailed: Boolean;

procedure RegisterIntegration(const Kind: String);
var
  ResultCode: Integer;
begin
  if not Exec(ExpandConstant('{app}\EasySync.exe'), '--register-integration ' + Kind,
              ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, ResultCode) then
    IntegrationFailed := True
  else if ResultCode <> 0 then
    IntegrationFailed := True;
  Log(Format('Easy Sync %s integration exit status: %d', [Kind, ResultCode]));
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then begin
    if WizardIsTaskSelected('shellmenu') then RegisterIntegration('shell');
    if WizardIsTaskSelected('wwisemenu') then RegisterIntegration('wwise');
    if IntegrationFailed then
      SuppressibleMsgBox('Easy Sync menu registration failed. Open Easy Sync > Options and register the menu again.' + #13#10 +
        'Details: %LOCALAPPDATA%\EasySync\Logs\integration-*.json', mbError, MB_OK, IDOK);
  end;
end;

function GetCustomSetupExitCode: Integer;
begin
  Result := 0;
  if IntegrationFailed then Result := 20;
end;
