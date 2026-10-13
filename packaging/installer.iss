; Inno Setup script for Análisis de Acciones (per-user install, no admin rights needed).
; Build: iscc /DAppVersion=0.1.0 packaging\installer.iss  (after the PyInstaller build)

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6F1C2E7A-4B3D-4C2E-9A51-3D2B7E8F1A10}
AppName=Análisis de Acciones
AppVersion={#AppVersion}
AppPublisher=Análisis de Acciones
DefaultDirName={localappdata}\Programs\AnalisisAcciones
DefaultGroupName=Análisis de Acciones
PrivilegesRequired=lowest
OutputDir=..\dist\installer
OutputBaseFilename=AnalisisAcciones-{#AppVersion}-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName=Análisis de Acciones
LicenseFile=..\packaging\AVISO.txt

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear un acceso directo en el escritorio"; GroupDescription: "Accesos directos:"

[Files]
Source: "..\dist\AnalisisAcciones\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Análisis de Acciones"; Filename: "{app}\AnalisisAcciones.exe"
Name: "{group}\Desinstalar Análisis de Acciones"; Filename: "{uninstallexe}"
Name: "{userdesktop}\Análisis de Acciones"; Filename: "{app}\AnalisisAcciones.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\AnalisisAcciones.exe"; Description: "Abrir Análisis de Acciones"; Flags: nowait postinstall skipifsilent

; User data (database, logs) lives in %LOCALAPPDATA%\AnalisisAcciones and is kept on uninstall
; and on upgrades.
