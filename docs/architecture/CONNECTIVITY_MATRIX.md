# CONNECTIVITY MATRIX

Status values: **PASS** = executed here with evidence, **NOT_TESTED**, **NOT_IMPLEMENTED**. Nothing is PASS by assumption.

| Path | Status | Evidence / note |
|---|---|---|
| Windows native MT5 + Python (Mode A) | **PASS** (read-only) | `scripts/windows/probe_mt5.py`; gateway ran live, ~3-5 Hz XAUUSD ticks |
| Windows MQL5 EA + local TCP (Mode B) | NOT_IMPLEMENTED | next step; needs manual "Allow WebRequest/socket" address config in MT5 |
| Benchmark A vs B | NOT_IMPLEMENTED | only Mode A latency inside gateway measured |
| Dashboard in Windows browser (Chrome) | **PASS** | screenshot: live bid/ask, M1 candles, CONNECTED |
| macOS ARM64 frontend (browser to Windows host) | NOT_TESTED | no Mac device available in this session; gateway binds 127.0.0.1 only, so LAN access needs explicit config |
| macOS research backend | NOT_TESTED | |
| macOS MT5/Wine + EA | NOT_TESTED | not assumed to work |
| Secure LAN / VPN | NOT_IMPLEMENTED | auth and TLS not yet built |
| Connection recovery | PARTIAL | reconnect/backoff coded; failure injection not yet tested |
