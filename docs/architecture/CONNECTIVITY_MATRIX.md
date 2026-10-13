# CONNECTIVITY MATRIX

Status values: **VERIFIED PASS** = executed with evidence, **PARTIAL**, **NOT TESTED**, **NOT IMPLEMENTED**. Nothing is PASS by assumption. Updated 2026-10-14.

| Path | Status | Evidence / note |
|---|---|---|
| Windows native MT5 + Python (Mode A) | VERIFIED PASS | live capture matches MT5 history exactly (1806/1806 over 417 s; 541/541 over a 3-session crash experiment); identity-isolated to MetaQuotes-Demo |
| Windows MQL5 EA + local TCP (Mode B) | NOT IMPLEMENTED | needs manual "Allow WebRequest/socket" address configuration in MT5 |
| Benchmark A vs B | NOT IMPLEMENTED | only Mode A receipt->publish inside the gateway has been measured; no end-to-end figure |
| Dashboard in Windows Chrome | VERIFIED PASS | 30 Playwright tests in Chrome 155 (docs/qa/BROWSER_TEST_MATRIX.md) |
| Connection recovery (gateway restart, browser reconnect) | VERIFIED PASS | e2e connection.spec; hard-kill x2 recovery experiment |
| Terminal failover to another terminal | by design never | SOURCE_MISMATCH stops collection, tested on the real terminal |
| macOS ARM64 frontend (browser to Windows host) | NOT TESTED | no Mac in this session; gateway is loopback-only and unauthenticated, so remote access is not enabled |
| macOS research backend | NOT TESTED | |
| macOS MT5/Wine + EA | NOT TESTED | not assumed to work |
| Secure LAN / VPN / auth / TLS | NOT IMPLEMENTED | |
