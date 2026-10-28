#ifndef AppBundle
  #error AppBundle required
#endif
#ifndef PrivateOutput
  #error PrivateOutput required
#endif
#ifndef Slot
  #error Slot required
#endif
[Setup]
AppId=NewsFlowAI-RecoveryEvidence
AppName=NewsFlow AI Recovery Evidence
AppVersion={#CandidateVersion}
DefaultDirName={localappdata}\Programs\NewsFlowAI-RecoveryEvidence
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#PrivateOutput}
OutputBaseFilename=Recovery-Setup
Compression=none
SolidCompression=no
UsePreviousAppDir=no
DisableProgramGroupPage=yes
CloseApplications=no
RestartApplications=no
[Files]
Source: "{#AppBundle}\*"; DestDir: "{app}\slots\{#Slot}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Private CI candidate only. Never launches app or owns user data.
#ifdef InjectFailure
[Code]
procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    RaiseException('SYNTHETIC_POST_COPY_FAILURE');
end;
#endif
