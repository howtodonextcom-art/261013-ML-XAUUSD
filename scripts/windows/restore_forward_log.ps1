# Restores the V2 forward evidence log from a backup made by backup_forward_log.ps1, after verifying its SHA-256 against MANIFEST.sha256.
# STOP THE GATEWAY FIRST. The current log is kept as v2_events.jsonl.before-restore-<stamp>.
# Usage:  .\scripts\windows\restore_forward_log.ps1 -Backup .\data\backup\v2_events-YYYYMMDD-HHMMSS.jsonl
param([Parameter(Mandatory = $true)][string]$Backup, [int]$Port = 8765)
$root = (Resolve-Path "$PSScriptRoot\..\..").Path
if (-not (Test-Path $Backup)) { Write-Host "NOT FOUND: $Backup"; exit 3 }
$Backup = (Resolve-Path $Backup).Path
$manifest = Join-Path (Split-Path $Backup) "MANIFEST.sha256"
$name = Split-Path $Backup -Leaf
$line = if (Test-Path $manifest) { Get-Content $manifest | Where-Object { $_ -match [regex]::Escape($name) } | Select-Object -Last 1 } else { $null }
if (-not $line) { Write-Host "REFUSED: no SHA-256 entry for $name in $manifest"; exit 4 }
$expected = ($line -split "\s+")[0]
$actual = (Get-FileHash $Backup -Algorithm SHA256).Hash
if ($expected -ne $actual) { Write-Host "REFUSED: SHA-256 mismatch (expected $expected, got $actual)"; exit 4 }
$listening = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($listening) { Write-Host "REFUSED: the gateway is running (port $Port; use -Port if it listens elsewhere). Stop it first."; exit 2 }
$dst = Join-Path $root "data\shadow\v2_events.jsonl"
if (Test-Path "$dst.lock") { Write-Host "REFUSED: a writer holds $dst.lock (a gateway may be running on another port)"; exit 2 }
New-Item -ItemType Directory -Force -Path (Split-Path $dst) | Out-Null
if (Test-Path $dst) { Copy-Item $dst "$dst.before-restore-$(Get-Date -Format yyyyMMdd-HHmmss)" }
Copy-Item $Backup $dst -Force
Write-Host "RESTORED: $dst from $name (sha256 verified: $actual)"
exit 0
