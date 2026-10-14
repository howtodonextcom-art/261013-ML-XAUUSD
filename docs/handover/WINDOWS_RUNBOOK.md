# Windows runbook (Windows 11, MetaTrader 5 on the same PC)

## One-time setup
See README.md (virtual environment, `configs\source.json` pinned to the MetaQuotes-Demo terminal with `pin_identity.py`, backfill). `configs\source.json` and `configs\api_token` are private and git-ignored.

## Start
1. Start MetaTrader 5 and make sure the **MetaQuotes-Demo** account is logged in (not FTMO).
2. `.\scripts\windows\run_gateway.ps1` (PowerShell, repository root). It prints the dashboard URL with the one-time token. Leave the window open; the gateway runs in it. Never start the gateway with a hand-written `uvicorn` command and never export `XAU_AUTH=off`.
3. Open the printed URL once, or later `.\scripts\windows\open_dashboard.ps1`.

## Verify the source (is this really MetaQuotes-Demo?)
- Dashboard > *Source provenance*: server `MetaQuotes-Demo`, symbol `XAUUSD`, demo `true`, build 6259, server UTC offset `10800 s (HIGH)`; connection `CONNECTED_ACTIVE`.
- A different server or account shows `SOURCE_MISMATCH` and the gateway refuses to publish prices.
- `GET /api/health` (with the bearer token) gives the same data; the account number is never shown.

## Stop
`Ctrl+C` in the gateway window. The tick writer drains its buffer before exit. If the window was killed, check for stray worker processes: PowerShell `Get-CimInstance Win32_Process | ? { $_.CommandLine -match 'multiprocessing.spawn' }`; an orphaned worker ends itself within seconds (parent watchdog), otherwise `Stop-Process` it.

## Recover after a restart or a crash
- Nothing to do: the gateway restores its cursor from the persisted ticks, re-fills recent bars from MT5 (read-only) and reports any gap under *Data quality* (`gaps`). A gap larger than 10 minutes is not replayed as live; fill it with the backfill: `$env:PYTHONPATH="services\gateway"; .\.venv\Scripts\python.exe -m xau_gateway.backfill --hours 48 --bars-days 70 --htf`.
- Check integrity: `.\.venv\Scripts\python.exe scripts\windows\data_qa.py --out data\qa_latest.json` (expect: verify `[]`, duplicates 0, coverage continuous).
- The browser reconnects by itself (back-off 1 s to 5 s); while disconnected it shows `DISCONNECTED` and STALE and removes every signal.

## Token
- Rotate: stop the gateway, delete `configs\api_token`, start it again, use the newly printed URL. Every old cookie stops working.
- Never paste the token into chats, tickets or screenshots.

## Backup and restore of data
- Backup (gateway stopped): copy the whole `data\store` folder (Parquet files plus `manifest.sqlite`) and `configs\source.json`. Forward shadow evidence is `data\shadow\v2_events.jsonl`: back it up too, it cannot be regenerated.
- Restore: stop the gateway, copy the folders back, run `data_qa.py`, start the gateway.
- Anything under `data\`, `configs\source.json`, `configs\api_token`, `.env` and `image\` must never be committed.

## Live MT5 verification (once)
Follow docs/qa/MT5_LIVE_VERIFICATION.md and run `.\scripts\windows\verify_live_session.ps1`.

## Troubleshooting
| Symptom | Meaning / action |
|---|---|
| "Authentication required" | open the URL printed at start-up or `open_dashboard.ps1` |
| `SOURCE_MISMATCH` | wrong terminal/account logged in; fix MT5, restart |
| `CONNECTED_IDLE` | terminal connected but no ticks (market closed or feed stalled) |
| `TRANSPORT_STALLED` | the browser stopped receiving frames; reload |
| `DEGRADED` | pipeline or persistence fault; read *Data quality*, restart if `persist hole` stays true |
| decision shows `INTEL_ENGINE_ERROR` | the analysis worker failed (type only is shown); it retries after 10 s; restart if it persists |
| 429 on the login URL | too many wrong tokens from this machine in a minute; wait one minute (the correct token still works) |
