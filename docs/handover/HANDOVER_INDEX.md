# Handover index: the ten questions

What is still yours to do: docs/handover/HUMAN_ACCEPTANCE_CHECKLIST.md (MT5, native zoom, Mac; all NOT TESTED until done).

| # | Question | Answer in |
|---|---|---|
| 1 | What can the product do? | USER_GUIDE.md ("What it shows"): near-real-time XAUUSD M1-H4 chart, market direction (H1/H4), M15 zones and setups, M5 confirmation, M1 shadow observations, a research decision (BUY/SELL/WAIT/BLOCKED) with Entry/SL/TP/R:R on a reference account, history and research status |
| 2 | What can it NOT do? | No orders of any kind, no profit claim, no validated edge (RESEARCH_STATUS.md), no TLS, no Mac verification yet (docs/qa/KNOWN_LIMITATIONS.md) |
| 3 | How do I open it on Windows? | WINDOWS_RUNBOOK.md: `scripts\windows\run_gateway.ps1`, then `scripts\windows\open_dashboard.ps1` |
| 4 | How do I reach it from a Mac safely? | MAC_ACCESS_GUIDE.md: SSH tunnel to the loopback port (or a private VPN address with `-AllowedHosts`); never a public bind |
| 5 | What do BUY / SELL / WAIT / BLOCKED mean? | USER_GUIDE.md: research eligibility only. WAIT names the missing event; BLOCKED names the failed gate and is not a signal; STALE/DISCONNECTED disable everything |
| 6 | Why is the M1 shadow not an order? | USER_GUIDE.md and RESEARCH_STATUS.md: separate panel, `execution_authorized: false`, no performance claim until the pre-registered gate (100 triggers AND 30 days) is met |
| 7 | How do I run the MT5 verification? | MT5_VERIFICATION_REPORT.md: one checklist, then `scripts\windows\verify_live_session.ps1 -Minutes 30` |
| 8 | How do I recognise stale data? | USER_GUIDE.md: red DISCONNECTED/STALE banner, decision shown as STALE, overlays cleared, "data age" in the quality panel |
| 9 | How do I back up data and the V2 forward log? | SECURITY_AND_ROLLBACK.md; `scripts\windows\backup_forward_log.ps1` (the forward log cannot be re-created: the past cannot be re-observed) |
| 10 | How do I roll back or recover? | SECURITY_AND_ROLLBACK.md (git tag/commit checkout, token rotation, restart recovery) |

UTC bar store and V2 evaluation prerequisites: docs/research/M1_ENTRY_V2_AMENDMENTS.md A12 (`python -m xau_gateway.backfill ...`, then `python benchmarks/v2_shadow_eval.py`; roll back the derived store with `python benchmarks/utc_migrate.py --rollback`).
