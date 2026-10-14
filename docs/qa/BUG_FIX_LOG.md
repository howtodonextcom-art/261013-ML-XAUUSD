# BUG FIX LOG

Severity: P0 data loss/corruption, P1 wrong data shown or integrity risk, P2 functional/UX, P3 cosmetic. "Test" = regression test that reproduces it.

| # | Sev | Bug | Root cause | Fix | Test |
|---|---|---|---|---|---|
| 1 | P0 | Live cursor re-emitted old ticks (104 826 live vs 3 925 in history) | occurrence state pruned earlier than the second-granular re-read window | prune exactly to the next fetch floor | `test_long_polling_simulation_emits_each_tick_exactly_once`, `test_prune_never_drops_state_the_next_read_can_return` |
| 2 | P0 | Restart (bridge_seq reset) could supersede an earlier live chunk (audit risk A) | chunk id `live-<first>-<last>` not unique across runs | `capture_session_id` in identity, `allow_supersede=False` for live | `test_A_restart_with_reset_bridge_seq_does_not_supersede_earlier_session` |
| 3 | P0 | Ticks consumed but not yet flushed were lost after a crash (audit risk B) | restart trusted an in-memory checkpoint that ran ahead of disk | `Store.restore_cursor` from persisted ticks; checkpoint file removed | `test_B_restart_recovers_ticks_consumed_but_not_persisted`; live crash experiment EXACT |
| 4 | P1 | Parity mixed history, live and other servers (risks C, D) | unfiltered `read_table` | filters on source/server/symbol/session | `test_CD_...`, `test_D_...` |
| 5 | P1 | A MT5 bar in a fully fetched hour with no local ticks was *excluded* instead of failing (risk E) | `c is None` treated as "open bar" | mismatch `NO_LOCAL_TICKS_FOR_EXISTING_MT5_BAR`; only the last minute counts as open | `test_E_covered_minute_without_local_ticks_is_mismatch_not_excluded` |
| 6 | P1 | Tick-size check hard-coded 0.01 (risk J) | constant | symbol metadata, `UNKNOWN_NO_SYMBOL_METADATA` when absent | `test_J_tick_size_check_uses_symbol_metadata` |
| 7 | P1 | Chart seeded without symbol/server isolation or quarantine state (risk G) | `seed_from_store` read everything | filtered by server/symbol; quarantined bars labelled | e2e `timeframes.spec` (data == API) |
| 8 | P1 | Backfill and live source used different identity checks (risk F) | duplicated logic | shared `identity.verify_identity` | `test_live_identity.py` |
| 9 | P1 | Rollover bars looked at a fixed 23:50-00:05 window; this server breaks 23:00-01:00 | wrong assumption | session boundaries derived from gaps in data | `test_session_boundaries_are_derived_from_real_gaps_not_a_fixed_clock_window` |
| 10 | P1 | UTC offset trusted from one (possibly stale) tick; catch-up depended on it (risk I) | single-sample estimate | multi-sample estimator with confidence; catch-up/gaps use server time only | `test_single_sample_is_never_more_than_provisional`, `test_fresh_arrival_samples_...` |
| 11 | P1 | M5-H4 charts had only bars since gateway start | no HTF history | native HTF backfill + merge; aggregation parity proven | e2e `click M5..H4: real history` (>=1000/500/250 bars), `test_aggregate_equals_native` |
| 12 | P1 | Failed candle request left the previous timeframe's bars under the new label | no error path | clear chart + visible error; stale responses dropped | e2e `failed candle request clears the chart...` |
| 13 | P1 | Last price stayed displayed as normal after DISCONNECTED | no stale marking | `data-stale`, strike-through, tooltip | e2e `F5 gateway stop` |
| 14 | P1 | UI said CONNECTED_ACTIVE with an open but silent websocket | no heartbeat watchdog | `TRANSPORT_STALLED` after 4 s without frames | e2e `silent websocket` |
| 15 | P2 | 60 s timer re-fit the chart, yanking the view while studying history | `fitContent()` on every refresh | fit only on timeframe change, otherwise preserve range | e2e `periodic refresh ... must NOT yank` |
| 16 | P2 | Chart overflowed the viewport when the window shrank (1112 px in 900 px) | grid `1fr` min-content | `minmax(0,1fr)`, `min-width:0` | e2e `F4 chart follows window resize` |
| 17 | P2 | Header price and Open-candle panel blank until the first tick after load | values set only from tick frames | render `last_tick` from health frame | screenshot review (01-initial); not separately asserted |
| 18 | P2 | Attribution link had `target=_blank` without `rel` | library default | `rel="noopener noreferrer"` set | `inventory.spec` |
| 19 | P2 | SQLite connections never closed (Windows could not delete files) | `with sqlite3.connect()` does not close | closing context manager | storage tests (tempdir cleanup) |
| 20 | P2 | Last closed bar wrongly excluded in parity | `t >= last_closed` | exclude only the open bar | `test_exact_closed_bars_certify` |

## P3 findings (found by tests while building the intelligence package)
| # | Sev | Bug | Root cause | Fix | Test |
|---|---|---|---|---|---|
| 21 | P1 | atr_ratio50 diluted by the very move it measures (spike gave 1.32 < 1.5) | baseline SMA(ATR,50) contained the recent ATR | baseline = mean ATR of the 50 bars ending 14 bars earlier | `test_regime_volatility_expansion_after_calm_then_spike` |
| 22 | P1 | Structure analysis took 77 s on the real store | labels recomputed for the whole swing list at every bar (O(n^2)) | incremental labels; 5 000-bar window; result 0.19 s | `test_incremental_structure_events_equal_naive_oracle` (12 series), `test_analysis_cost_is_bounded_for_long_series` |
| 23 | P2 | Test data bugs (not app bugs): fixtures with `high = max(open,close)+wick` made equal neighbouring highs (no strict fractal); spike wicks applied to the whole series; H1 index beyond the 300 buckets | fixtures | fixed in the tests | the same tests |

| 24 | P1 | `sma` converted NaN to 0 (MACD signal/hist/cross-age and atr_ratio50 wrong before true validity) | `np.where(isnan, 0)` in the cumulative sum | NaN for windows containing NaN | `test_sma_returns_nan_...`, `test_macd_signal_hist_and_cross_age_are_nan_until_really_valid`, `test_atr_ratio_is_nan_until_the_baseline_is_complete` |
| 25 | P1 | MT5 indicator comparator would fail correct code (seed differences in the early zone) | verdict used the early zone | verdict on the late zone only | `test_mt5_comparator_is_valid_when_mt5_computed_on_longer_history_than_the_dump` |
| 26 | P3 | window-relative event index | `bar_idx` after truncation | absolute `bar_open_time` | `test_events_carry_absolute_time_...` |

## Test-quality findings
- Two tests were wrong, not the app, and were corrected: a race reading the chart range before `setRange` applied; an ask-only tick fixture that changed bid. One test was **deleted** because it asserted nothing (browser-offline toggle). `setOffline` does not cut an existing websocket, so the transport-silence case uses `routeWebSocket`.
- Mutation check: serving M5 data under the M1 request, and truncating history to 3 bars, both make the timeframe assertions fail (proof they can fail).

## Open / unresolved
- **O1 (P2) flaky e2e once:** `rapid timeframe clicking` failed in one full-suite run while the gateway was slow right after a restart; not reproduced in 8 isolated + 24 loaded repeats and 2 further full runs (28/28 each). Cause unknown (hypothesis: queued requests exceeding the 10 s poll). Not fixed.
- **O2 (P3):** last-price label can overlap the neighbouring axis label on narrow charts (library behaviour), seen at 390 px.
- **O3 (P2):** the `API latency 270 ms` seen with `curl localhost` was IPv6 fallback, not the API (about 10 ms on 127.0.0.1); an optimization made on that wrong diagnosis was kept but its benefit is **unmeasured**.
- Bar 2026-10-13 16:58 remains unexplained (quarantined). Bar 19:08: history revision observed once.
