# Reads signed comment bytes as DATA. Never execute/import/dot-source the input.
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
try {
  $request = [Console]::In.ReadToEnd() | ConvertFrom-Json
  if (@($request.PSObject.Properties).Count -ne 1 -or $request.content.Length -gt 90000) { throw 'Input' }
  [byte[]]$bytes = [Convert]::FromBase64String($request.content)
  if ($bytes.Length -lt 2 -or $bytes.Length -gt 65536 -or $bytes[0] -ne 255 -or $bytes[1] -ne 254) { throw 'Encoding' }
  # Windows PowerShell 5.1 ByContent requires UTF-16LE. Never reinterpret as code.
  $signature = Get-AuthenticodeSignature -Content $bytes -SourcePathOrExtension '.ps1'
  if ($signature.Status -ne 'Valid' -or $null -eq $signature.SignerCertificate -or $null -eq $signature.TimeStamperCertificate) { throw 'Signature' }
  $certificate = $signature.SignerCertificate
  $hasCode = @($certificate.Extensions | Where-Object { $_ -is [Security.Cryptography.X509Certificates.X509EnhancedKeyUsageExtension] } | ForEach-Object { $_.EnhancedKeyUsages } | Where-Object { $_.Value -eq '1.3.6.1.5.5.7.3.3' }).Count -gt 0
  $hasTime = @($signature.TimeStamperCertificate.Extensions | Where-Object { $_ -is [Security.Cryptography.X509Certificates.X509EnhancedKeyUsageExtension] } | ForEach-Object { $_.EnhancedKeyUsages } | Where-Object { $_.Value -eq '1.3.6.1.5.5.7.3.8' }).Count -gt 0
  if (-not $hasCode -or -not $hasTime) { throw 'Purpose' }
  $hash = [Security.Cryptography.SHA256]::Create()
  try {
    $pin = ([BitConverter]::ToString($hash.ComputeHash($certificate.RawData))).Replace('-','').ToLowerInvariant()
    $container = ([BitConverter]::ToString($hash.ComputeHash($bytes))).Replace('-','').ToLowerInvariant()
  } finally { $hash.Dispose() }
  [ordered]@{status='Valid'; certificateSha256=$pin; timestamped=$true; codeSigning=$true; containerSha256=$container} | ConvertTo-Json -Compress
} catch {
  Write-Output '{"status":"Rejected"}'
  exit 1
}
