# ENVIRONMENT AUDIT (Phase 0) — measured 2026-10-13

| Item | Finding | Evidence |
|---|---|---|
| OS | Windows 11 Pro 10.0.26300, x64 | Win32_OperatingSystem |
| CPU | i5-13400, 10C/16T | Win32_Processor |
| Python | 3.14.4 (only interpreter); project venv `.venv` | `py -0p` |
| MetaTrader5 pkg | 5.0.6231 installs and runs on Python 3.14 | `pip`, `probe_mt5.py` |
| Node / pnpm / Git | 24.14.1 / 10.13.1 / 2.50.0 | `--version` |
| Workspace | Was empty except `image/`, `prompts/`. Not a git repo. | `Get-ChildItem` |
| Drive Z: | NTFS, DriveType 3 (local fixed), ~80 GB free | Win32_LogicalDisk |
| MT5 terminals running | **Two**: `C:\Program Files\MetaTrader 5` (MetaQuotes-Demo) and `C:\Program Files\FTMO Global Markets MT5 Terminal` | process list |
| Terminal used | MetaQuotes-Demo, build 6259, connected, account is demo (`trade_mode=0`), `trade_allowed=False` | `probe_mt5.py` |
| Symbol | `XAUUSD` (digits 2, point 0.01, tick size 0.01, contract 100, vol min/max/step 0.01/100/0.01) | `symbol_info` |
| MetaEditor | present at `C:\Program Files\MetaTrader 5\metaeditor64.exe` | Test-Path |
| Server time | Tick time is server time, UTC+3 (10800 s) at probe time; estimated at runtime, rounded to 15 min | `symbol_info_tick` |

Login, account number and password are never printed or stored.

**Important:** with two terminals installed, `mt5.initialize()` without `path` could attach to the wrong one (FTMO).
The gateway therefore always passes `MT5_TERMINAL_PATH` (default MetaQuotes-Demo in `run_gateway.ps1`).
Prices from MetaQuotes-Demo must not be assumed equal to FTMO.
