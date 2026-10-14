# KNOWN LIMITATIONS (2026-10-14, Level 5.1)

## Strategy and research
- **No demonstrated edge.** Thresholds of regime/setup/risk/gate are unvalidated design parameters. P6 (cand-1) is INSUFFICIENT_EVIDENCE: 7 validation trades (minimum 20), all intervals include zero, holdout sealed and never opened. The pre-registered 100-trade holdout rule is unreachable with this data (about 7 expected holdout trades). P7 (ML shadow): validation AUC 0.499 [0.474, 0.525]: no predictive skill; it is not wired into the UI or the decision.
- **Backtest realism:** the stored M5 `spread` is mostly 0.04 or 0.00 (monthly medians 0.13-0.16 in Oct-Nov 2025, constant 0.04 Jan-May 2026, 52% zeros in June 2026): spread-floor sensitivity (0.2 / 0.4 USD) must be read; bar-level fills (stop/target ambiguity resolved against the trade); one instrument, one broker feed, demo data, about 8 months of development+validation. Walk-forward blocks overlap the dev/val segments; exposure and trades-per-week metrics were not computed (docs/research/BACKTEST_AMENDMENTS.md).
- The structure experiments (swing k, setup lifecycle design) looked at the whole year including the sealed holdout for structure only, never for P/L.

## Data
- **M1 history holes** exist in MT5 itself (293 minutes on 2026-08-05, 4 minutes on 2026-09-24): reported and excluded from aggregation parity, never filled. Older M1 history may contain more.
- M1 parity: 13 258/13 258 eligible bars exact, but only about 20% of stored M1 bars have tick coverage; one bar (2026-10-13 16:58) is quarantined and unexplained; one history revision was seen once (cause unknown); 1 780 abnormal-spread and 969 spike candidates are not examined.
- **Tick identity:** MT5 has no tick id; identical ticks in one millisecond are distinguished by count only. A tick inserted later than 2 s behind the watermark is not seen by the overlap re-read (frequency unmeasured).
- **Crash safety:** one real hard-kill experiment (n=1) plus unit cases; a crash between the Parquet write and the manifest insert leaves an ignored orphan file; power loss and disk-full untested; Parquet files not fsynced. A failed flush is retried; if the bounded buffer overflows, ticks are dropped and the feed is flagged DEGRADED until restart (loud, not recovered).
- **Time/DST:** server offset +3 h measured live (HIGH). A synthetic DST switch is tested (a mixed window is reported LOW, never a confident wrong offset); a REAL broker DST switch is NOT TESTED (next: EU 2026-10-25, US 2026-11-01).

## MT5 verification
- **Indicator parity with MT5: NOT TESTED** (needs the DumpIndicators script run on a chart).
- **Mode A vs Mode B: LIVE_AB_NOT_TESTED.** EA v1.1, reader and benchmark are tested offline only; no Mode B source exists in the gateway. Behaviour with two terminals sharing the Common files folder is only protected by the account_ref in the file name (not tested live).

## Latency
- Measured (this machine, Chrome foreground): gateway p99 about 6.8 ms, delivery p99 about 7 ms, render p99 about 17 ms; a hidden tab renders late by design (about 1 s). The broker-to-PC leg cannot be measured: the broker clock differs from this PC by about 0.3 s. Live confirmation that the worker-process layout removes the old p99 spike across several bar closes: one bar close observed (max 10.2 ms), not a systematic series.
- Heavy analysis runs in a separate process (spawn); a hung or dead worker produces INTEL_ENGINE_ERROR and a new worker, never an old decision.

## Security and privacy
- Authenticated (token), loopback-only, Host/Origin allow-list. **Plain HTTP:** the cookie/token can be sniffed on an untrusted network; use an SSH tunnel or a private VPN. Any process of the same Windows user can read `configs/api_token`.
- **Privacy mode** hides the lot and sizes the research plan on a hypothetical reference account (`risk.reference_equity`, default 10 000): the public decision does not depend on the real account at all, so affordability of the REAL account is not evaluated in this mode (the plan is hypothetical). `XAU_REVEAL_SIZE=1` sizes on the live account, publishes the lot and then equity is inferable to well under 1%.
- No TLS, no per-user accounts, no audit log. The bind is declared (`XAU_HOST`), not observed: start only with `run_gateway.ps1` and never export `XAU_AUTH=off` (docs/architecture/THREAT_MODEL.md).
- Narrow layout: the decision card is placed before the chart visually only; DOM and tab order still put the chart first (WCAG 1.3.2 / 2.4.3 gap).

## UI
- Static page. Drawing tools are client-side only (browser localStorage, per profile, lost in a private window; two tabs: last writer wins; 500-drawing cap; invalid stored items are dropped on load after a `.bak` copy of the raw store); a point between two bars of a coarser timeframe adds one extra slot to that timeframe's axis; clicks right of the last bar clamp to the last bar; trendlines are segments; no ray/Fibonacci/text/zone-corner dragging; touch gestures NOT TESTED.
- `expires_at` / `entry_window_ends_at` project a bar-count rule onto the clock: later across market breaks (shown with `~`).
- Below 900 px width the decision card is placed before the chart (visible at 200% emulated zoom, 720x450); native browser zoom (100/125/150/200%) is **NOT TESTED** (emulation only: the DevTools protocol cannot trigger the browser's own zoom). Mac / other browsers: NOT TESTED. No pixel-level visual regression.
- While the gateway is down the browser logs a connection-refused error per reconnect attempt (back-off 1 s to 5 s).
- A BUY/SELL on **live** data has not been observed: no eligible setup occurred during the QA sessions (live ENTRY_ELIGIBLE NOT OBSERVED); BUY/SELL display is verified with explicitly labelled synthetic fixtures only.

## Process
- Independent reviews found real defects in every round; the final pass over the Level 5.1 changes is recorded in RED_TEAM_FINDINGS.md. One e2e failure was seen once (BUG_FIX_LOG O1) and not reproduced.
- Data lives in `data/store` (git-ignored); `configs/source.json` and `configs/api_token` are private and git-ignored.
