# One live MT5 verification session (Level 5.1 P1): Mode A/B capture benchmark + indicator parity. READ-ONLY: nothing here sends, modifies or cancels an order.
# Manual prerequisites (once, in the MetaQuotes-Demo terminal; see docs/qa/MT5_LIVE_VERIFICATION.md):
#   1. Navigator > Expert Advisors > xau_tmp_compile > XauTickLoggerModeB  -> drag onto ONE XAUUSD chart, allow algorithmic trading for it.
#   2. Navigator > Scripts > xau_tmp_compile > DumpIndicators              -> drag onto an XAUUSD chart (runs once and writes the CSV files).
# Usage:  .\scripts\windows\verify_live_session.ps1 [-Minutes 30]
param([double]$Minutes = 30)
$root = Resolve-Path "$PSScriptRoot\..\.."
$py = "$root\.venv\Scripts\python.exe"
$env:PYTHONPATH = "$root\services\gateway;$root\services\intelligence"
$words = @{ 0 = "VERIFIED PASS (report written)"; 1 = "FAILED"; 2 = "REFUSED (configuration)"; 3 = "NOT TESTED"; 4 = "FAILED (identity mismatch)" }
Set-Location $root

Write-Host "== Indicator parity (DumpIndicators -> mt5_indicator_parity.py)" -ForegroundColor Cyan
& $py benchmarks/mt5_indicator_parity.py
$parity = $LASTEXITCODE
Write-Host ("   -> " + $(if ($parity -eq 4) { "REJECTED (provenance)" } else { $words[$parity] }))

Write-Host "== Mode A/B capture benchmark ($Minutes min)" -ForegroundColor Cyan
& $py benchmarks/ab_capture.py --minutes $Minutes
$ab = $LASTEXITCODE
Write-Host ("   -> " + $words[$ab])

Write-Host ""
Write-Host "SUMMARY  indicator parity: exit $parity   A/B capture: exit $ab" -ForegroundColor Yellow
Write-Host "Results: results/p2/ab_capture.json (A/B), docs/qa/INDICATOR_PARITY_REPORT.md (parity, if written). Update docs/qa/IMPLEMENTATION_STATE.md and PRODUCT_ACCEPTANCE_MATRIX.md with the REAL outcome."
exit ([Math]::Max($parity, $ab))
