# KNOWN LIMITATIONS (updated after Phase 1A/1B)

- **Parity:** certified on ~48 h of MetaQuotes-Demo (2399/2399 eligible bars exact, 1 bar quarantined, see M1_BAR_MISMATCH_RCA.md). One bar unexplained; 19:08 case only partly explained. Rollover-window bars could not be tested: this server has no bars 22:59-01:00 (daily break).
- **Live vs history:** one 417 s capture matched exactly. Longer and market-open/close captures not yet done.
- **Seams:** backfill skips the last 15 min (history may be revised); live capture started after the last backfilled hour leaves a gap until backfill is rerun. Gaps are reported by data_qa.py, not filled.
- **Latency:** only receipt->publish inside the gateway is measured (p50 about 3.5 ms in the latest run). Terminal->gateway polling delay, browser and render stages are NOT measured; no end-to-end claim.
- **Tick identity:** MT5 gives no tick id; bit-identical ticks in one ms are distinguished only by count.
- **Mode B (MQL5 EA), A/B benchmark, strategy engines, risk, replay/backtest, ML, auth/TLS, Mac testing:** not implemented / NOT TESTED.
- **Dashboard** is a static page; M1 history is seeded from persisted MT5 bars labelled MT5_HISTORY, M5-H4 charts still start from live ticks only.
- Data dir is `data/store` (git-ignored). `data/qa_latest.json` is a generated artifact.
