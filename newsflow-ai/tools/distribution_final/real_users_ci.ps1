param([Parameter(Mandatory=$true)][string]$Workspace)
$ErrorActionPreference='Stop'
if ($env:GITHUB_ACTIONS -ne 'true' -or $env:RUNNER_OS -ne 'Windows') { throw 'Disposable Windows CI only; never forge CI flags' }
$runner=[IO.Path]::GetFullPath($env:RUNNER_TEMP).TrimEnd('\')+'\'
$root=[IO.Path]::GetFullPath($Workspace)
if (-not $root.StartsWith($runner,[StringComparison]::OrdinalIgnoreCase) -or (Test-Path -LiteralPath $root)) { throw 'Fresh Runner TEMP workspace required' }
New-Item -ItemType Directory -Path $root | Out-Null
'{"kind":"NewsFlow-disposable-real-sid"}' | Set-Content -LiteralPath (Join-Path $root 'owned-real-sid.json') -Encoding utf8
$project=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$python=(Get-Command python -ErrorAction Stop).Source
$users=@();$processes=@();$forced=$false;$succeeded=$false
try {
  foreach ($alias in @('A','B')) {
    $name='NFQA'+$alias+([guid]::NewGuid().ToString('N').Substring(0,8))
    $password=ConvertTo-SecureString ('Nf!9'+[Convert]::ToBase64String([Security.Cryptography.RandomNumberGenerator]::GetBytes(32))) -AsPlainText -Force
    $account=New-LocalUser -Name $name -Password $password -AccountNeverExpires -Description 'Disposable NewsFlow CI standard user'
    $users+=@{alias=$alias;name=$name;sid=$account.SID;credential=[pscredential]::new(($env:COMPUTERNAME+'\'+$name),$password)}
    $group=Get-LocalGroup -SID 'S-1-5-32-545'
    Add-LocalGroupMember -Group $group -Member $account
  }
  # Read-only code access + root-only CreateDirectories. No peer DeleteChild/write.
  $security=[Security.AccessControl.DirectorySecurity]::new()
  $security.SetAccessRuleProtection($true,$false)
  $owner=[Security.Principal.WindowsIdentity]::GetCurrent().User
  $security.SetOwner($owner)
  foreach ($sid in @($owner,[Security.Principal.SecurityIdentifier]::new('S-1-5-18'),[Security.Principal.SecurityIdentifier]::new('S-1-5-32-544'))) {
    $security.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($sid,'FullControl','ContainerInherit,ObjectInherit','None','Allow'))
  }
  foreach ($u in $users) {
    $security.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($u.sid,'ReadAndExecute','ContainerInherit,ObjectInherit','None','Allow'))
    $security.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($u.sid,'CreateDirectories','None','None','Allow'))
  }
  Set-Acl -LiteralPath $root -AclObject $security
  $code=Join-Path $root 'code';New-Item -ItemType Directory -Path (Join-Path $code 'src') | Out-Null
  Copy-Item -LiteralPath (Join-Path $project 'src\newsflow') -Destination (Join-Path $code 'src\newsflow') -Recurse
  Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'sid_worker.py') -Destination (Join-Path $code 'sid_worker.py')
  function Start-OwnedUser($u,$context) {
    $inputFile=Join-Path $root ('input-'+$u.alias+'.json')
    $context | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $inputFile -Encoding utf8NoBOM
    $saved=@{};Get-ChildItem Env: | ForEach-Object {$saved[$_.Name]=$_.Value}
    try {
      $keep=@('SYSTEMROOT','WINDIR','COMSPEC','PATHEXT','PATH','OS','PROCESSOR_ARCHITECTURE','NUMBER_OF_PROCESSORS','COMPUTERNAME','GITHUB_ACTIONS','RUNNER_OS','RUNNER_TEMP')
      Get-ChildItem Env: | Where-Object {$_.Name.ToUpperInvariant() -notin $keep} | ForEach-Object {Remove-Item -LiteralPath ('Env:\'+$_.Name)}
      $env:PYTHONDONTWRITEBYTECODE='1'
      $arguments='-I -B "'+(Join-Path $code 'sid_worker.py')+'" --input "'+$inputFile+'"'
      $child=Start-Process -FilePath $python -ArgumentList $arguments -Credential $u.credential -LoadUserProfile -WindowStyle Hidden -PassThru -WorkingDirectory $code -RedirectStandardOutput (Join-Path $root ('stdout-'+$u.alias+'.txt')) -RedirectStandardError (Join-Path $root ('stderr-'+$u.alias+'.txt'))
      return $child
    } finally {
      Get-ChildItem Env: | ForEach-Object {Remove-Item -LiteralPath ('Env:\'+$_.Name)}
      foreach ($item in $saved.GetEnumerator()) {[Environment]::SetEnvironmentVariable($item.Key,$item.Value,'Process')}
    }
  }
  $a=$users[0];$b=$users[1]
  $pa=Start-OwnedUser $a @{root=$root;alias='A';expected_sid=$a.sid.Value};$processes+=$pa
  $aData=Join-Path $root 'profile-A\NewsFlowAI-Desktop\v1'
  $deadline=(Get-Date).AddSeconds(45)
  while (-not (Test-Path -LiteralPath (Join-Path $aData 'ready.json')) -and (Get-Date) -lt $deadline -and -not $pa.HasExited) {Start-Sleep -Milliseconds 150}
  if (-not (Test-Path -LiteralPath (Join-Path $aData 'ready.json'))) {
    if (Test-Path -LiteralPath (Join-Path $root 'stderr-A.txt')) {Get-Content -LiteralPath (Join-Path $root 'stderr-A.txt') -Tail 8}
    throw 'User A initialization blocked; no automatic privilege expansion'
  }
  $peer=Get-Content -LiteralPath (Join-Path $aData 'ready.json') -Raw | ConvertFrom-Json -AsHashtable
  Copy-Item -LiteralPath $peer.cipher -Destination (Join-Path $root 'cipher-A-for-negative-test.bin')
  $pb=Start-OwnedUser $b @{root=$root;alias='B';expected_sid=$b.sid.Value;peer=$peer};$processes+=$pb
  if (-not $pb.WaitForExit(45000) -or $pb.ExitCode -ne 0) {
    if (Test-Path -LiteralPath (Join-Path $root 'stderr-B.txt')) {Get-Content -LiteralPath (Join-Path $root 'stderr-B.txt') -Tail 8}
    throw 'User B probe failed or blocked'
  }
  'stop' | Set-Content -LiteralPath (Join-Path $aData 'stop')
  if (-not $pa.WaitForExit(20000) -or $pa.ExitCode -ne 0) {throw 'User A normal cleanup failed'}
  $ar=Get-Content -LiteralPath (Join-Path $aData 'result.json') -Raw | ConvertFrom-Json
  $br=Get-Content -LiteralPath (Join-Path $root 'profile-B\NewsFlowAI-Desktop\v1\result.json') -Raw | ConvertFrom-Json
  if ($ar.sid_fingerprint -eq $br.sid_fingerprint -or $ar.port -eq $br.port) {throw 'Windows users or ports not distinct'}
  $summary=[ordered]@{status='PASS';scope='Two actual standard Windows CI users; not Windows11 consumer GUI';a=$ar;b=$br;actual_windows_accounts=2;operating_account_used=$false;source_or_sample_originals_modified=$false;paid_calls=0;sns_calls=0}
  $summary | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $root 'real-user-results.json') -Encoding utf8
  $succeeded=$true
} finally {
  foreach ($p in $processes) {if (-not $p.HasExited) {Stop-Process -Id $p.Id -ErrorAction SilentlyContinue;$forced=$true}}
  foreach ($u in $users) {
    $current=Get-LocalUser -Name $u.name -ErrorAction SilentlyContinue
    if ($current -and $current.SID.Value -eq $u.sid.Value) {Remove-LocalUser -SID $u.sid}
  }
  $cleanup=[ordered]@{test_users_removed=@($users | Where-Object {Get-LocalUser -Name $_.name -ErrorAction SilentlyContinue}).Count -eq 0;forced_cleanup=$forced;normal_test_success=$succeeded;production_processes_touched=$false;synthetic_profiles='Retained only until disposable Runner destruction; no C:\Users recursive deletion'}
  $cleanup | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $root 'cleanup-results.json') -Encoding utf8
  if ($forced) {throw 'Owned process required forced cleanup; not a normal-exit PASS'}
}
