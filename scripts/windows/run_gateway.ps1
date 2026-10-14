# Starts the read-only XAUUSD gateway + dashboard. Loopback only by default; authentication is ON.
# Usage (PowerShell, from repo root):  .\scripts\windows\run_gateway.ps1
# The dashboard URL with the ONE-TIME token is printed below; open it once (the browser keeps an HttpOnly session cookie).
# Remote access (e.g. a MacBook) is NOT enabled by default; see docs/architecture/THREAT_MODEL.md (SSH tunnel or a private VPN, never a public bind).
param(
  [string]$TerminalPath = "C:\Program Files\MetaTrader 5\terminal64.exe",  # set explicitly: several MT5 terminals may be installed
  [int]$Port = 8765,
  [string]$BindHost = "127.0.0.1",
  [string]$AllowedHosts = ""   # extra Host names/IPs accepted ONLY with authentication on, e.g. "100.64.1.2" for a private VPN address
)
$root = Resolve-Path "$PSScriptRoot\..\.."
$env:MT5_TERMINAL_PATH = $TerminalPath
$env:PYTHONPATH = "$root\services\gateway;$root\services\intelligence"
$env:XAU_HOST = $BindHost
if ($AllowedHosts) { $env:XAU_ALLOWED_HOSTS = $AllowedHosts }
if ($BindHost -notin @("127.0.0.1", "localhost", "::1") -and $env:XAU_AUTH -eq "off") { throw "refusing: a non-loopback binding needs authentication" }
$tokenFile = Join-Path $root "configs\api_token"
if (-not (Test-Path $tokenFile)) {
  $bytes = New-Object byte[] 32; [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
  [Convert]::ToBase64String($bytes).TrimEnd("=").Replace("+","-").Replace("/","_") | Set-Content -Path $tokenFile -Encoding ascii
}
if ($BindHost -notin @("127.0.0.1", "localhost", "::1")) { Write-Warning "Non-loopback binding: plain HTTP. Use only on a private network you control (VPN); prefer an SSH tunnel with the default loopback binding." }
$tok = (Get-Content $tokenFile -Raw).Trim()
if ($env:XAU_AUTH -ne "off") { Write-Host "Dashboard: http://127.0.0.1:$Port/?token=$tok   (token file: configs\api_token, git-ignored)" -ForegroundColor Cyan }
& "$root\.venv\Scripts\python.exe" -m uvicorn xau_gateway.app:app --host $BindHost --port $Port
