; 智能打码工坊 安装脚本（Inno Setup 6）
#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif
#define MyAppName "智能打码工坊"
#define MyAppExe "MaskForge.exe"
#define MyRepo "https://github.com/berlin955/MaskForge-Studio"

[Setup]
AppId={{6C1E2B3A-8F4D-4E5B-9A21-5D3C7B9E0F11}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher=berlin955
AppPublisherURL={#MyRepo}
AppSupportURL={#MyRepo}/issues
AppUpdatesURL={#MyRepo}/releases
DefaultDirName={localappdata}\Programs\MaskForge Studio
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
OutputDir=..\dist-installer
OutputBaseFilename=MaskForge-Studio-Setup-{#MyAppVersion}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExe}
UninstallDisplayName={#MyAppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
CloseApplications=yes
RestartApplications=no
VersionInfoVersion={#MyAppVersion}
VersionInfoProductName={#MyAppName}

[Languages]
#ifdef ChineseIsl
Name: "chs"; MessagesFile: "{#ChineseIsl}"
#else
Name: "en"; MessagesFile: "compiler:Default.isl"
#endif

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\MaskForge\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall
