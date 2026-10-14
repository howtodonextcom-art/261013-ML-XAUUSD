# RED TEAM / INDEPENDENT REVIEW FINDINGS

Reviewer: one real subagent in a separate context (read-only, no MT5 access, instructed to refute the implementer's claims). It ran the offline tests (54 passed at that time). Gate F6 stays **PARTIAL**: one review round happened; the fixes were verified by the implementer's own regression runs (71 pytest + 30 Chrome tests), **not re-reviewed independently**.

| # | Severity (reviewer) | Finding | Disposition |
|---|---|---|---|
| 1 | High | Pipeline thread had no exception handling or heartbeat; health could stay CONNECTED_ACTIVE while nothing was processed | FIXED: `process_tick` contains and counts errors, heartbeat, state `DEGRADED`; tests in `test_review_findings.py` |
| 2 | High | Writer dropped ticks on a failed flush without retry; the persisted watermark could skip the hole; drops not visible in the UI | FIXED: retry with backoff, bounded buffer, permanent `hole` flag, `DEGRADED`, UI shows persistence drops/hole |
| 3 | Medium | `restore_cursor` keyed by the symbol hint, not the resolved symbol (for example XAUUSD.r) | FIXED: restore runs after connect with the terminal's real server/symbol |
| 4 | Medium | The quarantine row had empty server/symbol and applied everywhere | FIXED: strict scoping, real row updated, test |
| 5 | Medium | `continuous=true` only meant "some tick in the hour" | FIXED: minute-level check against MT5 bars; *_PARTIAL statuses; the current store is still continuous (222 active hours) |
| 6 | Medium | README called replay-on-history "parity" and mixed it with live verification | FIXED: wording separates the two |
| 7 | Medium | Partial/quarantined bars drawn like normal bars; no warning on the seam | PARTLY FIXED: such bars are grey (deterministic e2e). No UI warning for the backfill/live seam yet |
| 8 | Medium | Paint loop could die on a library exception; an update could hit the previous timeframe's series | FIXED: try/catch with reload; updates applied only when the data timeframe equals the current one (e2e injects a bad update) |
| 9 | Medium | Vacuous or weak tests: a `toBeDefined()` assertion, only a coarse-to-fine timeframe check, an MQL5 scan on a missing folder, safety scan only on `services/` | FIXED: removed; median spacing must equal the timeframe exactly; the MQL5 test now SKIPS visibly; scan covers services/scripts/benchmarks/apps. NOT fixed: the HTF aggregation test self-skips without a local store |
| 10 | Low | Supersede does not check completeness; byte-hash identity superseded 40 chunks on a metadata change | PARTLY FIXED: content-based identity (219 identical on re-run); a re-fetch with FEWER rows is a visible supersede (tested) but still replaces the active file |
| 11 | Low | `received_at_ns` is process-monotonic; shutdown did not drain; `image/` not ignored; innerHTML unescaped | FIXED: documented, writer joined on shutdown, `image/` ignored, strings escaped |

Unverified assumptions listed by the reviewer that remain open: DST behaviour, frequency of late ticks beyond the 2 s window, a crash between Parquet and manifest, power loss, other servers/symbols. `crash_recovery_test.sh` kills any process listening on port 8765.
No order path was found anywhere (static analysis); there is no runtime guard if someone adds one later.


# Review round 2: P3 intelligence package (independent subagent, read-only, 2026-10-14)
It could not refute: causality of indicators and structure (40 random seeds with fat tails, cut-and-compare), no repaint, level confirmed before the breaking bar opened, closed-bar snapshot rule, absence of BUY/SELL in outputs, ATR definition.
| # | Sev | Finding | Disposition |
|---|---|---|---|
| 1 | High (verified) | `sma` turned NaN into 0: MACD signal valid from index 8 with fake values, hist/cross-age wrong for bars 25-32 | FIXED (NaN when the window holds a NaN); tests: first valid signal index 33, NaN hist/cross-age before it |
| 2 | Medium (verified) | `atr_ratio50` same cause, inflated first values (index 63-76) | FIXED; first valid index 77 asserted |
| 3 | High (verified by simulation) | MT5 comparator would report FAIL on correct definitions: MT5 seeds on the whole history, the CSV has the last 3000 bars; the earlier fake-dump test was vacuous | FIXED: verdict on the late zone only, early shown as informational; new test simulates a longer reference history |
| 4 | Low | `bar_idx` relative to the truncated window | FIXED: events carry `bar_open_time` (absolute) |
| 5 | Low | `max_bars` truncation | no defect found (30 cut points at 600 bars: identical trend/regime/labels); convergence is empirical, not proven |
| 6 | Medium | Pre-registration unverifiable (not committed before the run; file also holds the result); both candidates failed the density band | DOCUMENTED in the decision file and wording changed ("chosen by the fallback clause"); process change: pre-register by commit before running |
| 7 | Low | weak tests (`<= known_at - 900 + 900`, 3-regime assertion, oracle shares code) | FIXED the first; added a hand-computed zig-zag case; limits of the oracle documented; the 3-regime assertion kept deliberately broad (documented) |
| 8 | Suspicion | only the latest level per kind is breakable | DOCUMENTED as a design choice |
Gate F6 remains PARTIAL: P3 fixes were verified by the implementer's tests, not re-reviewed.

# Review round 3: P3 closure (independent subagent, read-only, 2026-10-14)
Confirmed as truly fixed (it ran experiments): NaN-as-zero `sma` and everything derived from it; late-zone verdict of the MT5 comparator (EMA200 seed error after 2000 bars about 2e-9; a simulated MT5 seeded on 30 000 bars vs a 3 000-bar dump: late difference 1.4e-8, PASS); absolute event times; no causality or repaint violation in zig-zag, fractal, structure events or liquidity events (300 seeds, many cut points); no trading call in `DumpIndicators.mq5`.
| # | Sev | Finding | Disposition |
|---|---|---|---|
| 1 | Medium | The comparator verdict is only valid for CSVs of at least about 2800 bars; nothing enforced it (N=2500 and below gave false FAIL) | FIXED: `MIN_BARS = 2800` in the provenance check; the MQL5 script refuses to write a dump shorter than InpBars-50 |
| 2 | Medium | Provenance failed OPEN: an empty store skipped the OHLC cross-check; an unpinned account_ref skipped the account check | FIXED: fail closed (`UNVERIFIED_FEED`, `NO_PINNED_ACCOUNT_REF`); tests for None/empty store and empty account_ref |
| 3 | Low | Overlap did not have to cover the late zone; 0.1% mismatch tolerated anywhere; dumps dated in the future accepted | FIXED: overlap must cover >= 900 of the last 1000 bars, any mismatch in the late zone rejects, future-dated dump rejected |
| 4 | Low-Medium | A swept level was dead for liquidity but still breakable for structure (34% of break events were on swept levels) | FIXED/DOCUMENTED: one lifecycle: a sweep never consumes a level; one break per level in both modules; consistency tests |
| 5 | Low | Early `return false` in the MQL5 script leaked indicator handles; it continued after an incomplete calculation | FIXED: wrapper releases on every path; fails if not calculated within 20 s |
| 6 | Medium | Pre-registration claims overstated (implementation after, not with, the pre-registration; extra degrees of freedom; k=2.5 reused on untested timeframes) | DOCUMENTED in an addendum to SWING_K_PREREGISTRATION.md; commit ordering verified: pre-registration d01eca2 < implementation 49527a5 < result |
| 7 | Low | Weak tests (liquidity prefix only 4 seeds/16 cuts, store-empty case untested, same data used as dump and store) | PARTLY FIXED: full-length prefix, artifact, empty/None store, late-zone cases added; the dump and the store in the provenance tests still derive from the same generator (documented) |
Not independently re-reviewed after these fixes: gate F6 stays PARTIAL.

# Review round 4: P4 setup lifecycle (independent subagent, read-only, 2026-10-14)
It could not refute: prefix == full (also through the whole H1 -> M15 pipeline, 3 seeds), BUY/SELL mirror (by construction; 39 random markets turned upside down twice gave 0 differences), no duplicate setups, legal transitions, `known_at` = bar close on every event, no BUY/SELL decision emitted by the machine.
| # | Sev | Finding | Disposition |
|---|---|---|---|
| 1 | Medium (verified) | A confirmation bar did not have to touch the zone: a strong bullish bar entirely above it confirmed with entry 3.1 above the zone | FIXED (`low <= zone.high` required); regression test + mutation check |
| 2 | Low (verified) | SELL evidence strings printed mirrored (negative) prices | FIXED: evidence formatted in real prices; test uses a positive-price mirrored market |
| 3 | Low (verified) | First event had `prev_state = SETUP_FORMING` instead of None | FIXED; chain-consistency test |
| 4 | Low | Test count in SETUP_LIFECYCLE.md wrong (31 vs 30) | FIXED (docs now state the real count) |
| 5 | Low-Medium (measured) | Setups could be created long after the impulse (p99 19 bars, max 47) and age was counted from creation | FIXED: creation allowed only within 20 bars of the impulse high becoming known; age counted from it |
| 6 | Low-Medium | `current_status` ignored an H4 conflict once a setup was active | FIXED: eligible + conflict => WAIT / SIGNAL_CONFLICT |
| 7 | Low | Mirror test only on one hand-built scenario | FIXED: 8 random markets upside down with price offset |
| 8 | Low | Prefix test sliced the context instead of recomputing the pipeline | FIXED: full-pipeline prefix test |
Unverified suspicions: confirm-window boundary (confirmed bars up to touch+5, timeout on touch+6) matches the specification text as now written; chase check uses the bar high by design (documented).
Not independently re-reviewed after these fixes: gate F6 stays PARTIAL.
