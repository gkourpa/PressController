; Inno Setup script for the lab's Windows installer (DAqReader's, adapted).
;
; Build it with `python tools/build_installer.py`, which runs PyInstaller first and
; passes the version in -- do not compile this by hand against a stale dist/.
;
; ONE INSTALLER FOR BOTH CASES. The fixed AppId below is what makes running a
; newer setup.exe an upgrade rather than a second copy. Never change the AppId.
;
; THE OPERATOR'S STATE IS NOT OURS. Settings live in %APPDATA%\PressController;
; the press file, the captures and the tests live wherever the operator put them.
; This script never names {userappdata} or {localappdata}: installing, upgrading
; and uninstalling all leave them exactly as they were.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\PressController"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist\installer"
#endif

[Setup]
AppId={{BAB1ABE9-48E7-40BE-B531-16AFCB08C162}
AppName=PressController
AppVersion={#AppVersion}
AppVerName=PressController {#AppVersion}
VersionInfoVersion={#AppVersion}
DefaultDirName={autopf}\PressController
DefaultGroupName=PressController
DisableProgramGroupPage=yes
; Asked on the first install only; an upgrade silently reuses the previous folder.
DisableDirPage=auto
PrivilegesRequired=admin
; `setup.exe /CURRENTUSER` installs for one account with no admin prompt.
PrivilegesRequiredOverridesAllowed=commandline
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename=PressController-{#AppVersion}-setup
SetupIconFile=..\presscontroller\app\resources\icon.ico
UninstallDisplayIcon={app}\PressController.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; An open app holds its DLLs; the Restart Manager asks to close it first.
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[InstallDelete]
; A PyInstaller build is a matched set: clear the old one before laying down the
; new. Only {app} is touched -- see the note at the top.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
; *.toml excluded: a press file names one lab's ports and ranges, and an
; installer must not carry one setup's identity to another.
Source: "{#SourceDir}\*"; DestDir: "{app}"; Excludes: "*.toml"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\PressController"; Filename: "{app}\PressController.exe"; \
    Parameters: "--control"
Name: "{group}\PressController monitor (listen-only)"; Filename: "{app}\PressController.exe"
Name: "{group}\Uninstall PressController"; Filename: "{uninstallexe}"
Name: "{autodesktop}\PressController"; Filename: "{app}\PressController.exe"; \
    Parameters: "--control"; Tasks: desktopicon

[Run]
Filename: "{app}\PressController.exe"; Parameters: "--control"; \
    Description: "Start PressController"; Flags: nowait postinstall skipifsilent
