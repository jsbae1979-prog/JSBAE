#ifndef AppBundle
  #error AppBundle required
#endif
#ifndef Launcher
  #error Launcher required
#endif
#ifndef ReleaseManifest
  #error ReleaseManifest required
#endif
#ifndef PrivateOutput
  #error PrivateOutput required
#endif
[Setup]
AppId=NewsFlowAI-PrivateOffline-v1
AppName=NewsFlow AI (Private Verification Candidate)
AppVersion=1.0.0
VersionInfoVersion=1.0.0.0
DefaultDirName={localappdata}\Programs\NewsFlowAI-Private
DisableDirPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#PrivateOutput}
OutputBaseFilename=NewsFlowAI_Setup_v1.0.0
Compression=lzma2/fast
SolidCompression=yes
DisableProgramGroupPage=yes
UsePreviousAppDir=no
CloseApplications=no
RestartApplications=no
AllowNoIcons=yes
UninstallDisplayName=NewsFlow AI Private Candidate (user data retained)
[Files]
Source: "{#Launcher}"; Flags: dontcopy
Source: "{#Launcher}"; DestDir: "{app}"; DestName: "NewsFlowAI.exe"; Flags: ignoreversion
Source: "{#ReleaseManifest}"; DestDir: "{app}"; DestName: "initial-release.json"; Flags: ignoreversion
Source: "{#AppBundle}\*"; DestDir: "{app}\slots\1.0.0"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{userprograms}\NewsFlow AI (Private)"; Filename: "{app}\NewsFlowAI.exe"
[UninstallDelete]
Type: files; Name: "{app}\install.lock"
Type: dirifempty; Name: "{app}\slots"
[Code]
var FinalizationFailed: Boolean;
function InitializeSetup(): Boolean;
var V: TWindowsVersion;
begin
  GetWindowsVersionEx(V);
  Result := (V.NTPlatform and (V.Major = 10) and (V.Build >= 22000) and (V.ProductType = 1));
  if not Result then MsgBox('This private candidate requires Windows 11.', mbError, MB_OK);
end;
function PrepareToInstall(var NeedsRestart: Boolean): String;
var Code: Integer;
begin
  Result := '';
  if DirExists(ExpandConstant('{app}')) then begin
    Result := 'Existing installation/directory found. Use a signed offline update. Nothing was replaced.';
    exit;
  end;
  ExtractTemporaryFile('NewsFlowAI.exe');
  if not Exec(ExpandConstant('{tmp}\NewsFlowAI.exe'), '--prepare-install "' + ExpandConstant('{app}') + '"', '', SW_HIDE, ewWaitUntilTerminated, Code) or (Code <> 0) then
    Result := 'Private user directory initialization failed. Installation stopped.';
end;
procedure CurStepChanged(CurStep: TSetupStep);
var Code: Integer;
begin
  if CurStep = ssPostInstall then begin
    if not Exec(ExpandConstant('{app}\NewsFlowAI.exe'), '--finalize-install "' + ExpandConstant('{app}') + '"', '', SW_HIDE, ewWaitUntilTerminated, Code) or (Code <> 0) then begin
      FinalizationFailed := True;
      RaiseException('Private profile initialization failed. Do not launch; retain data and inspect.');
    end;
  end;
end;
function GetCustomSetupExitCode(): Integer;
begin
  if FinalizationFailed then Result := 2 else Result := 0;
end;
function InitializeUninstall(): Boolean;
var Code: Integer;
begin
  Result := Exec(ExpandConstant('{app}\NewsFlowAI.exe'), '--uninstall-programs', '', SW_HIDE, ewWaitUntilTerminated, Code) and (Code = 0);
  if not Result then MsgBox('Close NewsFlow AI normally; recover any incomplete update before uninstalling. User data was retained.', mbError, MB_OK);
end;
// No user-data deletion, scheduler/task registration or automatic app launch.
