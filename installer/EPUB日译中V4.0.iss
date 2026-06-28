#ifndef MyAppDisplayVersion
#define MyAppDisplayVersion "4.1"
#endif
#ifndef MyAppVersion
#define MyAppVersion "4.1.1"
#endif
#ifndef MyAppFileVersion
#define MyAppFileVersion "4.1.1.0"
#endif
#define MyAppName "AI日译中(EPUB) V" + MyAppDisplayVersion
#define MyAppPublisher "EPUB Translator"
#define MyAppExeName "AI日译中(EPUB)V" + MyAppVersion + ".exe"

[Setup]
AppId={{9A4E7C3B-155C-49D3-8D8C-A9B8A7423C40}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\AI日译中(EPUB) V{#MyAppDisplayVersion}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\dist\installer
OutputBaseFilename=AI日译中(EPUB)V{#MyAppVersion} 单文件安装程序
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupIconFile=..\experimental\qml_v4\assets\app_icon.ico
VersionInfoVersion={#MyAppFileVersion}
VersionInfoProductVersion={#MyAppVersion}
VersionInfoTextVersion={#MyAppVersion}
VersionInfoProductName={#MyAppName}

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务："; Flags: unchecked

[Files]
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent
