#ifndef AppVersion
  #define AppVersion "2.1.0"
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
SetupIconFile=..\assets\app.ico
UninstallDisplayIcon={app}\OVAExporterGUI.exe
OutputDir=..\dist
OutputBaseFilename=OVA-Exporter-GUI-{#AppVersion}-Windows-x64-Setup
Compression=lzma2
SolidCompression=yes
CloseApplications=no
RestartApplications=no
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
Filename: "{app}\OVAExporterGUI.exe"; Description: "Open OVA Exporter GUI"; Flags: nowait postinstall skipifsilent unchecked
Filename: "https://developer.broadcom.com/tools/open-virtualization-format-ovf-tool/latest/"; Description: "Get VMware OVF Tool (required if not already installed)"; Flags: shellexec postinstall skipifsilent unchecked
