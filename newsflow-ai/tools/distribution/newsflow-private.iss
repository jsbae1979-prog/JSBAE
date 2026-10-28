; Installer definition only: ISCC is not installed/compiled in the current run.
; Never run on the operating profile. No application launch/autorun or data deletion.
#ifndef AppBundle
  #error AppBundle must point to the inventoried private onedir bundle
#endif
#ifndef PrivateOutput
  #error PrivateOutput must be a separate test output directory
#endif
[Setup]
AppId=NewsFlowAI-PrivateCandidate
AppName=NewsFlow AI Private Candidate
AppVersion=0.6.0b1
VersionInfoVersion=0.6.0.1
DefaultDirName={localappdata}\Programs\NewsFlowAI-PrivateCandidate
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#PrivateOutput}
OutputBaseFilename=NewsFlowAI-Private-Setup
UninstallDisplayName=NewsFlow AI Private Candidate
Compression=lzma2
SolidCompression=yes
UsePreviousAppDir=yes
DisableProgramGroupPage=yes
CloseApplications=no
RestartApplications=no
[Files]
Source: "{#AppBundle}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; No [Run], [Icons], startup registration, shared ACL grants or [UninstallDelete].
; User DB/key/media outside {app} are not installer-owned and must be preserved.
