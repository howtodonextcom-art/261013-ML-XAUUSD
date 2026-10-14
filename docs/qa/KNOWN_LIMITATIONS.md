# KNOWN LIMITATIONS (2026-10-14)

- **Scope:** this release is a verified data foundation plus a live chart. No indicators, market structure, BUY/SELL/WAIT, risk, replay, backtest or ML exist.
- **Latency:** only receipt-to-publish inside the gateway has been measured. Terminal-to-gateway polling delay, WebSocket-to-browser and paint are NOT measured; no end-to-end claim. A tick-age residual of about 0.1 s was observed while estimating the server offset, but local-clock versus server-clock sync is unknown, so it is not a latency figure.
- **Mode B (MQL5 EA) and A/B benchmark:** NOT IMPLEMENTED.
- **M1 parity:** 13 258/13 258 eligible bars exact, but only 20.1% of stored M1 bars have tick coverage (ticks backfilled for 14 days, M1 bars for 70). It certifies the candle engine on settled history; the live path has two short verifications (417 s and 181 s).
- **Unexplained data:** M1 bar 2026-10-13 16:58 (quarantined). A history revision was seen once (19:08), cause unknown. 1 780 abnormal-spread and 969 spike candidates are not examined.
- **Time/DST:** server offset +3 h measured live (HIGH confidence); behaviour across a real DST switch is NOT TESTED (next ones: EU 2026-10-25, US 2026-11-01).
- **Tick identity:** MT5 has no tick id; identical ticks in one ms are distinguished by count only. A tick inserted later than 2 s behind the watermark is not seen by the overlap re-read (frequency unmeasured).
- **Crash safety:** one real hard-kill experiment (n=1, 181 s window) plus unit cases. A crash between the Parquet write and the manifest insert leaves an ignored orphan file (no sweeper); power loss and disk-full are untested; Parquet files are not fsynced.
- **Writer losses:** a failed flush is retried; if the bounded buffer overflows, ticks are dropped and the feed is flagged DEGRADED (PERSISTENCE_HOLE) until restart. This is loud, not recovered.
- **Dashboard:** static page. 6 controls (5 timeframes plus the library attribution link). No drawing tools, indicator toggles, replay/risk/strategy panels, authentication or TLS; the gateway is loopback-only and unauthenticated. Browser zoom is emulated (viewport plus DPR). Visual regression is not automated. DevTools performance, tick-burst replay, sleep/resume: NOT TESTED.
- **Mac M1 / other browsers:** NOT TESTED.
- **One e2e failure** was seen once (BUG_FIX_LOG O1) and not reproduced since.
- Data lives in `data/store` (git-ignored); `configs/source.json` is private and git-ignored.

- **Equity inference:** a published rounded lot plus the risk fraction approximately bounds the account size (RISK_GOVERNANCE.md). The API has no authentication: loopback only.
- **M1 history holes:** MT5's M1 history has real holes (293 minutes on 2026-08-05, 4 minutes on 2026-09-24); they are reported and excluded from the aggregation parity, never filled. Older M1 history may contain more.
- **Hot path:** the intelligence thread shares the GIL with the tick pipeline. Receipt-to-publish p99 was 5.5 ms (n=320) in one sample and 29 ms in another right after a restart; not measured systematically under sustained heavy compute.
- **Decision freshness:** setup state changes only at bar closes; between closes only gates and risk plan are refreshed (about every 2 s).
- **No demonstrated edge:** all thresholds are unvalidated design parameters; no replay/backtest, ML, Mode B or drawing tools exist yet.

- **Equity/free-margin oracles (review 6b):** observing an eligible lot at several loss distances, and the instants at which BLOCKED reasons flip, narrows equity and free margin to about 0.2%. Only the loopback binding and the Host/Origin guard protect it; any local process can still read the API (no authentication yet).
- **Expiry times are approximate:** `expires_at` / `entry_window_ends_at` project a bar-count rule onto the clock; across the daily break or a weekend the real expiry is later.
- **Mode B (P2):** EA compiled, reader tested, A/B benchmark NOT TESTED (needs the EA attached manually); no live Mode B source exists in the gateway.
- **Backtest (P6):** INSUFFICIENT_EVIDENCE; the pre-registered holdout threshold (100 trades) is unreachable with this data; stored M5 spread is mostly 0.04/0.00 so spread-floor sensitivity must be read (docs/research/BACKTEST_AMENDMENTS.md).
