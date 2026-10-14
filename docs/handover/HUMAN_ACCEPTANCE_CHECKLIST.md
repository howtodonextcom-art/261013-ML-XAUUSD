# Human acceptance checklist (about 50 minutes in total)

Everything below is **NOT TESTED** until you do it and write the result in the right-hand column. Do not create or wait for a live BUY/SELL: it is not required. Nothing here places an order.

## 1. MT5 (about 40 minutes, MetaQuotes-Demo terminal only)
| Step | Action | Result |
|---|---|---|
| 1 | In MetaTrader 5 (title bar must show **MetaQuotes-Demo**) open an XAUUSD chart | |
| 2 | Navigator > Scripts > `xau_tmp_compile` > `DumpIndicators` onto that chart; wait for its alert | |
| 3 | Navigator > Expert Advisors > `xau_tmp_compile` > `XauTickLoggerModeB` onto ONE XAUUSD chart; allow algorithmic trading for the EA (it contains no trading code) | |
| 4 | PowerShell in the repo: `.\scripts\windows\verify_live_session.ps1 -Minutes 30` | |
| 5 | Copy the final SUMMARY line into docs/handover/MT5_VERIFICATION_REPORT.md | |

## 2. Chrome native zoom (about 5 minutes)
Open the dashboard with `.\scripts\windows\open_dashboard.ps1`. For each of 100%, 125%, 150%, 200% (Ctrl + plus, Ctrl+0 to reset): no horizontal scrollbar; the decision card text is not cut off; the chart pans and zooms with the mouse; an H-line you draw is still at the same price after a reload; the toolbar stays reachable.

## 3. Mac (about 5 minutes, only if you have one)
Follow docs/handover/MAC_ACCESS_GUIDE.md (SSH tunnel or a private VPN address with `-AllowedHosts`). Check you can log in with the token and see the decision card; confirm the dashboard is NOT reachable from a public address.

## 4. Routine
Weekly: `.\scripts\windows\backup_forward_log.ps1` and copy the backup off this PC. Around 2026-10-25 and 2026-11-01 (broker DST): leave the gateway running and tell the maintainer; do not evaluate V2 across the switch before reading A12.
