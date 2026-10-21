# Install the specific project's MITM root CA into the current user's
# Windows trust store only after an explicit interactive confirmation.
# This does not disable TLS certificate verification.
$ErrorActionPreference = 'Stop'
$certPath = Join-Path $PSScriptRoot 'mitm-ca\mitmproxy-ca-cert.cer'
if (-not (Test-Path -LiteralPath $certPath -PathType Leaf)) {
  Write-Host 'Certificate not found. Start start-proxy-windows.bat first.'
  Write-Host $certPath
  exit 1
}
$cert = [System.Security.Cryptography.X509Certificates.X509Certificate2]::new($certPath)
$thumbprint = $cert.Thumbprint.ToUpperInvariant()
$installed = Get-ChildItem Cert:\CurrentUser\Root | Where-Object { $_.Thumbprint -eq $thumbprint }
Write-Host "Project CA certificate: $certPath"
Write-Host "Subject: $($cert.Subject)"
Write-Host "SHA1 thumbprint: $thumbprint"
if ($installed) {
  Write-Host 'This exact CA is already trusted in CurrentUser\Root.'
  exit 0
}
Write-Warning 'A trusted root CA can issue certificates for arbitrary domains.'
Write-Warning 'Use this only in your isolated experiment Windows VM/user profile.'
Write-Warning 'Remove it from CurrentUser\Root after your research is complete.'
$answer = Read-Host "Type TRUST to install THIS certificate for the CURRENT WINDOWS USER ONLY"
if ($answer -cne 'TRUST') {
  Write-Host 'No changes made.'
  exit 2
}
$null = Import-Certificate -FilePath $certPath -CertStoreLocation 'Cert:\CurrentUser\Root'
$verified = Get-ChildItem Cert:\CurrentUser\Root | Where-Object { $_.Thumbprint -eq $thumbprint }
if (-not $verified) {
  Write-Error 'Import returned but this exact CA was not found in CurrentUser\Root.'
  exit 1
}
Write-Host 'Trusted this project CA for the current user.'
Write-Host 'Close all windows of the dedicated experiment Chrome profile and reopen.'
Write-Host 'Then run check-mock-https-windows.bat to verify the HTTPS handshake.'
