#ifndef AppVersion
  #define AppVersion "2.3.2"
#endif

[Setup]
AppId={{93CB58AA-6D24-41A7-9446-A84EB15273F4}
AppName=OVA Exporter GUI
AppVersion={#AppVersion}
AppPublisher=OVA Exporter GUI contributors
DefaultDirName={localappdata}\Programs\OVA Exporter GUI
DefaultGroupName=OVA Exporter GUI
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
WizardStyle=modern
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
InfoAfterFile=installer-notes.txt
InfoBeforeFile=tool-requirement.txt
SetupIconFile=..\assets\app.ico
UninstallDisplayIcon={app}\OVAExporterGUI.exe
OutputDir=..\dist
OutputBaseFilename=OVA-Exporter-GUI-{#AppVersion}-Windows-x64-Setup
Compression=lzma2
SolidCompression=yes
CloseApplications=no
RestartApplications=no
UsePreviousAppDir=yes
UsePreviousGroup=yes
UsePreviousTasks=yes
Uninstallable=yes

[Tasks]
Name: "desktopicon"; Description: "Create a Desktop shortcut"; Flags: unchecked

[Files]
Source: "..\dist\OVAExporterGUI\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"
Source: "..\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"

[Icons]
Name: "{group}\OVA Exporter GUI"; Filename: "{app}\OVAExporterGUI.exe"
Name: "{autodesktop}\OVA Exporter GUI"; Filename: "{app}\OVAExporterGUI.exe"; Tasks: desktopicon
Name: "{group}\Uninstall OVA Exporter GUI"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\OVAExporterGUI.exe"; Description: "Open OVA Exporter GUI and check OVF Tool"; Flags: nowait postinstall skipifsilent; Check: not IsAppUpdate
Filename: "{app}\OVAExporterGUI.exe"; Flags: nowait runasoriginaluser; Check: IsAppUpdate
Filename: "https://developer.broadcom.com/tools/open-virtualization-format-ovf-tool/latest/"; Description: "Get VMware OVF Tool (required if not already installed)"; Flags: shellexec postinstall skipifsilent unchecked; Check: not IsAppUpdate

[Code]
function IsAppUpdate: Boolean;
begin
  Result := ExpandConstant('{param:OVAUPDATE|0}') = '1';
end;

function OpenProcess(Access: LongWord; InheritHandle: Integer; PID: LongWord): THandle;
  external 'OpenProcess@kernel32.dll stdcall';
function WaitForSingleObject(Handle: THandle; Milliseconds: LongWord): LongWord;
  external 'WaitForSingleObject@kernel32.dll stdcall';
function CloseHandle(Handle: THandle): Integer;
  external 'CloseHandle@kernel32.dll stdcall';

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  PID: Integer;
  ProcessHandle: THandle;
  WaitResult: LongWord;
begin
  Result := '';
  if not IsAppUpdate then Exit;
  if not FileExists(ExpandConstant('{app}\OVAExporterGUI.exe')) or
     not FileExists(ExpandConstant('{app}\unins000.exe')) then
  begin
    Result := 'No existing installation was found in the update folder. Run Setup normally to install the app.';
    Exit;
  end;
  PID := StrToIntDef(ExpandConstant('{param:OVAPID|0}'), 0);
  if PID <= 0 then
  begin
    Result := 'The update is missing its application process ID. Run Setup normally instead.';
    Exit;
  end;
  ProcessHandle := OpenProcess($00100000, 0, PID);
  if ProcessHandle <> 0 then
  begin
    WaitResult := WaitForSingleObject(ProcessHandle, 30000);
    CloseHandle(ProcessHandle);
    if WaitResult <> 0 then
      Result := 'The app has not finished closing. Close it and try the update again. No process was force-stopped.';
  end;
end;
