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
