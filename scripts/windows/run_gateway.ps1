# Starts the read-only XAUUSD gateway + dashboard on loopback only.
# Usage (PowerShell, from repo root):  .\scripts\windows\run_gateway.ps1
param(
  [string]$TerminalPath = "C:\Program Files\MetaTrader 5\terminal64.exe",  # set explicitly: several MT5 terminals may be installed
  [int]$Port = 8765
)
$root = Resolve-Path "$PSScriptRoot\..\.."
$env:MT5_TERMINAL_PATH = $TerminalPath
$env:PYTHONPATH = "$root\services\gateway"
& "$root\.venv\Scripts\python.exe" -m uvicorn xau_gateway.app:app --host 127.0.0.1 --port $Port
