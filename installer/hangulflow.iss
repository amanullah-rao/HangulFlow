; Inno Setup script for the HangulFlow installer.
;
;   1. Build the app:   .venv\Scripts\python.exe -m PyInstaller hangulflow.spec --noconfirm --clean
;   2. Build setup:     "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" installer\hangulflow.iss
;
; Produces dist\HangulFlow-Setup-<version>.exe. It installs for the current user
; only (no administrator rights needed), so it works on any Windows 10/11 PC.
; Words and progress live in %LOCALAPPDATA%\HangulFlow and are kept on uninstall.

#define AppVersion "0.3.2"

[Setup]
AppId={{6F1C2A4E-8B37-4D5A-9E2F-4A7C1B3D5E60}
AppName=HangulFlow
AppVersion={#AppVersion}
AppPublisher=Amanullah
AppPublisherURL=https://github.com/amanullah-rao/HangulFlow
DefaultDirName={localappdata}\Programs\HangulFlow
DefaultGroupName=HangulFlow
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=HangulFlow-Setup-{#AppVersion}
SetupIconFile=..\assets\hangulflow.ico
UninstallDisplayIcon={app}\HangulFlow.exe
LicenseFile=..\LICENSE
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
; Close a running copy before files are replaced (Restart Manager).
CloseApplications=force
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "startup"; Description: "Start HangulFlow when I sign in to Windows"; GroupDescription: "Start-up:"

[Files]
Source: "..\dist\HangulFlow\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; Remove files from an older version that the new build no longer has.
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{group}\HangulFlow"; Filename: "{app}\HangulFlow.exe"
Name: "{group}\Uninstall HangulFlow"; Filename: "{uninstallexe}"
Name: "{userdesktop}\HangulFlow"; Filename: "{app}\HangulFlow.exe"; Tasks: desktopicon

[Registry]
; Same value the app's own "Start with Windows" option writes, so both stay in sync.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "HangulFlow"; \
    ValueData: """{app}\HangulFlow.exe"""; Tasks: startup; Flags: uninsdeletevalue
; Without the task, still remove the value on uninstall if the app set it.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueName: "HangulFlow"; \
    Flags: uninsdeletevalue dontcreatekey; Check: not WizardIsTaskSelected('startup')

[Run]
Filename: "{app}\HangulFlow.exe"; Description: "Start HangulFlow now"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/IM HangulFlow.exe /F"; Flags: runhidden; RunOnceId: "StopHangulFlow"
