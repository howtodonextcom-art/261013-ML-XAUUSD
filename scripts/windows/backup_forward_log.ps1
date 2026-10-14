# Copies the V2 forward evidence log (not reproducible: the past cannot be re-observed) to a timestamped backup with a SHA-256 manifest.
# Usage (repo root):  .\scripts\windows\backup_forward_log.ps1 [-Destination D:\xau-backup]
param([string]$Destination = "")
$root = (Resolve-Path "$PSScriptRoot\..\..").Path
if (-not $Destination) { $Destination = Join-Path $root "data\backup" }
$src = Join-Path $root "data\shadow\v2_events.jsonl"
if (-not (Test-Path $src)) { Write-Host "NOT FOUND: $src (nothing logged yet)"; exit 3 }
New-Item -ItemType Directory -Force -Path $Destination | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$dst = Join-Path $Destination "v2_events-$stamp.jsonl"
Copy-Item $src $dst
$h = (Get-FileHash $dst -Algorithm SHA256).Hash
"$h  v2_events-$stamp.jsonl" | Add-Content (Join-Path $Destination "MANIFEST.sha256")
$lines = (Get-Content $dst | Measure-Object -Line).Lines
Write-Host "BACKUP OK: $dst ($lines lines, sha256 $h)"
