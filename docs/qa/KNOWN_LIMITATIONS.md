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

## Level 5.2 additions
- **M1 Entry V2 (shadow):** no historical evidence is possible (all stored M1 lies inside the sealed holdout period); evaluation needs >= 100 triggers AND >= 30 days of forward data, likely many weeks. Events logged before the round-9 fix (2 at the time) have no `v1_target` and use the 2R fallback.
- **Stops level:** MetaQuotes-Demo XAUUSD requires >= 6.00 USD stops distance; M1-scale stops (about 3 USD) are BLOCKED (SL_TOO_CLOSE), so many V2 triggers can never become a research entry. Reported, not tuned away.
- V2 runs on its own worker process with a 10 s deadline; if it fails the shadow section disappears (error type recorded), V1 is unaffected; a failing job is retried once per closed bar.
- Accessibility: no screen-reader or tool-based contrast audit; native browser zoom not tested (CSS-zoom/viewport emulation only).
- Playwright: two timing-sensitive tests (drag-to-pan, gateway stop/restart) failed once in a full run and passed on re-run; cause not isolated.
- The peer guard trusts the socket address (see THREAT_MODEL): never combine a local proxy with `XAU_AUTH=off`.

## Level 5.4 additions
- V2 evaluation gap rules (amendment A8): entry bar must exist at trigger+60 s; 288 minutes of timeline; ANY hole in the position window that is not an evidenced recurring market closure (A12) is missing data and the trade is not counted, whatever its length (the earlier 15-bar and 119-bar thresholds are superseded). These counts are reported, never hidden.
- A real server DST switch: bars and events are evaluated on the UTC timeline (A12); every stamp that could belong to the unmeasured interval around a switch is EXCLUDED (up to about 1.5 h of bars either side with hourly evidence), never converted with a guess. The evaluator still refuses non-monotonic bar times as a last line of defence.
- Events that become knowable while the gateway is down are not logged afterwards (coverage, not bias).

## Level 5.5 additions
- UTC bar store (A12): only 688 of 66,018 stored M1 bars have a proven offset today (evidence starts 2026-10-13); older history is excluded, not guessed. Evaluation also needs the forward-period M1 bars to be backfilled first.
- Closure evidence needs three repeats per signature; a weekend-type closure needs three weekends.
- The repeated fall-back hour, if it occurs in live capture, is excluded from the UTC store rather than reconstructed.

## Level 6.2 additions
- V1 decision events exist only from the moment the gateway first ran this code: older BUY/SELL decisions are NOT reconstructed (setup markers are not decisions). The log keeps one event per (setup, action) for BUY/SELL and per (setup, blocking reason) for BLOCKED: a setup that becomes BUY, is blocked and becomes BUY again is recorded once as BUY.
- A BUY/SELL that persists keeps its marker on the candle of its FIRST publication (tagged NOW while it is still the current decision); it is not moved to the current candle. BLOCKED events are stored per distinct gate code, so a transient gate (for example a session or spread flicker) adds a record. `published_at` is the server-clock second of the last tick; `published_wall_ms` is the UTC key; `late_publication` marks an event first published more than 120 s after its setup became knowable (for instance after a gateway restart while a setup was already eligible). A moment that lies in a missing candle or after the last loaded one is not drawn at all (never on an earlier candle).
- Marker time resolution is the server second; a decision is placed on the candle containing its publication time, so on M1 a decision published in the last second of a bar sits on that bar.
- The progress stepper is a display of backend fields (setup state, action, reason); it shows no ATR or price distance because the backend does not provide a verified measure.
- The funnel numbers are a historical replay on development + validation data, not forward evidence; the policy being strict is a research question, not a finding of a bug.

## Level 6.3 additions
- Setup history is limited by the candles loaded for the chart (the newest 2000 per timeframe): older events are counted as "outside range", not fetched. The REPLAY part covers only the stored bars (from 2025-10-14); it is a deterministic replay, not a live recording, and it fills only the time BEFORE the live engine window (the two disagree inside that window because the state machine starts at a different bar).
- A setup event is drawn on the candle that closes when it became known (`known_at - 1`); on M1 that is the last minute of the confirming M15 bar. It is never drawn on an earlier candle.
- The history is fetched once per viewed candle window; a timeframe change refetches only if the new window reaches beyond what was fetched. If `/api/setup_events` fails, the card shows `history error`, the newest 12 events stay.
