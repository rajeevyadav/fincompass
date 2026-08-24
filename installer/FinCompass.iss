; Inno Setup script for FinCompass (Windows installer)
; Build:  compile with Inno Setup (iscc installer\FinCompass.iss) AFTER build_exe.bat
;         has produced dist\FinCompass.exe. Output: dist\FinCompass-1.0.0-Setup.exe
#define AppVersion "1.2.0"

[Setup]
AppName=FinCompass
AppVersion={#AppVersion}
AppPublisher=Rajeev Yadav
AppCopyright=Copyright (C) 2026 Rajeev Yadav. MIT License.
DefaultDirName={autopf}\FinCompass
DefaultGroupName=FinCompass
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\FinCompass.exe
OutputDir=..\dist
OutputBaseFilename=FinCompass-{#AppVersion}-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
Source: "..\dist\FinCompass.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\FinCompass"; Filename: "{app}\FinCompass.exe"
Name: "{group}\Uninstall FinCompass"; Filename: "{uninstallexe}"
Name: "{autodesktop}\FinCompass"; Filename: "{app}\FinCompass.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\FinCompass.exe"; Description: "Launch FinCompass now"; Flags: nowait postinstall skipifsilent

; User data lives in %LOCALAPPDATA%\FinCompass (kept on uninstall). Remove it too:
[UninstallDelete]
Type: filesandordirs; Name: "{localappdata}\FinCompass"
