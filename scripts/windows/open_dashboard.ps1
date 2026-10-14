# Opens the dashboard in the default browser with the one-time token from configs\api_token (HttpOnly session cookie afterwards).
param([int]$Port = 8765)
$root = Resolve-Path "$PSScriptRoot\..\.."
$tokenFile = Join-Path $root "configs\api_token"
if (-not (Test-Path $tokenFile)) { throw "no token yet: start the gateway once with scripts\windows\run_gateway.ps1" }
$tok = (Get-Content $tokenFile -Raw).Trim()
Start-Process "http://127.0.0.1:$Port/?token=$tok"
