param([Parameter(Mandatory=$true)][string]$Artifact)
$ErrorActionPreference = 'Stop'
$OutputEncoding = [Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
try {
  $file = Get-Item -LiteralPath $Artifact -ErrorAction Stop
  if ($file.PSIsContainer -or ($file.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Ordinary file required' }
  $signature = Get-AuthenticodeSignature -LiteralPath $file.FullName -ErrorAction Stop
  $certificate = $signature.SignerCertificate
  if ($signature.Status -ne 'Valid' -or $null -eq $certificate) { throw 'Invalid signature' }
  $hasCodeSigning = @($certificate.Extensions | Where-Object { $_ -is [Security.Cryptography.X509Certificates.X509EnhancedKeyUsageExtension] } | ForEach-Object { $_.EnhancedKeyUsages } | Where-Object { $_.Value -eq '1.3.6.1.5.5.7.3.3' }).Count -gt 0
  $digest = [Security.Cryptography.SHA256]::Create()
  try { $fingerprint = ([BitConverter]::ToString($digest.ComputeHash($certificate.RawData))).Replace('-','').ToLowerInvariant() }
  finally { $digest.Dispose() }
  [ordered]@{status='Valid';certificateSha256=$fingerprint;timestamped=($null -ne $signature.TimeStamperCertificate);codeSigning=$hasCodeSigning} | ConvertTo-Json -Compress
} catch {
  # No path, certificate subject, environment, artifact body or exception is echoed.
  Write-Output '{"status":"Rejected"}'
  exit 1
}
