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

| 27 | P1 | Gateway failed to start after wiring the intelligence service (ImportError: `xau_intel` not on PYTHONPATH of run_gateway.ps1) | the run script only added services/gateway | script adds services/intelligence | live restart + `/api/intel` ready |
| 28 | P1 | `compute_heavy` cut its 5 000-bar window BEFORE the time filter, so bars after `now` shifted the window and changed the result | pre-cap `_tail` | time filter first, windows after | `test_heavy_result_shape_and_snapshot_discipline_future_bars_change_nothing` |
| 29 | P1 | Shadow simulator produced a positive "SL_FIRST" when the fill was already beyond the stop | no guard on the fill price | NO_FILL (FILL_BEYOND_STOP / FILL_BEYOND_TARGET) | `test_a_fill_beyond_the_stop_or_the_target_is_no_fill_...` (found by a property test) |
| 30 | P1 | Decision record lacked the zone, so no overlay could be drawn from it | omitted field | `setup.zone` and `setup.impulse` included | `test_overlays_without_a_plan_use_the_setup_levels_and_zone` |
| 31 | P2 | Test only proved chart price lines were CREATED; a screenshot showed them outside the visible price range | fixture used far-away prices | levels taken from the live price; pixel position asserted (`priceToCoordinate`) | `F5 BUY levels near the live price are really drawn inside the visible chart` |
| 32 | P2 | Safety test banned any `order_` text, so it would have blocked the pure calculators; broad bans hide real intent | too coarse | allow-list: only `order_calc_profit` / `order_calc_margin`, applied to mt5_source and symbol_spec | `test_mt5_module_never_exposes_order_calls_to_source` |

## Test-quality findings
- Two tests were wrong, not the app, and were corrected: a race reading the chart range before `setRange` applied; an ask-only tick fixture that changed bid. One test was **deleted** because it asserted nothing (browser-offline toggle). `setOffline` does not cut an existing websocket, so the transport-silence case uses `routeWebSocket`.
- Mutation check: serving M5 data under the M1 request, and truncating history to 3 bars, both make the timeframe assertions fail (proof they can fail).

## Open / unresolved
- **O1 (P2) flaky e2e once:** `rapid timeframe clicking` failed in one full-suite run while the gateway was slow right after a restart; not reproduced in 8 isolated + 24 loaded repeats and 2 further full runs (28/28 each). Cause unknown (hypothesis: queued requests exceeding the 10 s poll). Not fixed.
- **O2 (P3):** last-price label can overlap the neighbouring axis label on narrow charts (library behaviour), seen at 390 px.
- **O3 (P2):** the `API latency 270 ms` seen with `curl localhost` was IPv6 fallback, not the API (about 10 ms on 127.0.0.1); an optimization made on that wrong diagnosis was kept but its benefit is **unmeasured**.
- **O4 (P2) flaky e2e once:** in one decision.spec run right after a mutation cycle, 2 of 10 tests failed (sequence display and stale-decision); 3 immediate reruns and 2 full-suite runs passed 10/10 and 11/11. Cause unknown (hypothesis: gateway load at a bar close). Not fixed.
- Bar 2026-10-13 16:58 remains unexplained (quarantined). Bar 19:08: history revision observed once.

## Integration, privacy and data findings (2026-10-14, later)
| # | Sev | Bug | Root cause | Fix | Test |
|---|---|---|---|---|---|
| 33 | P0 | After widening the HTF backfill, M5-H4 contained duplicate bar times (M5: 80 148 duplicate rows) | chunk ids were anchored on the moving start of each run, so later runs wrote overlapping chunks under new ids | fixed absolute 30-day grid (`chunking.grid_cells`), legacy chunks marked superseded (kept), `duplicate_times` check in data_qa | test_backfill_chunking.py; store now 0 duplicates |
| 34 | P1 (data finding) | HTF aggregation parity turned FAIL once native HTF bars covered a year | MT5's M1 history has real holes: 293 missing minutes on 2026-08-05 and 4 on 2026-09-24, while native M5-H4 bars exist there | evidence-based hole detection (`holes.m1_holes`), affected buckets excluded with reason M1_HISTORY_HOLE and reported; parity PASS elsewhere | test_holes.py; M5 13 202/13 202, M15 4 399, H1 1 098, H4 298 |
| 35 | P0 | Equity recoverable from the public plan; amounts in reason strings | see RED_TEAM_FINDINGS round 5 | public plan only; ratios in reasons | test_privacy.py |
| 36 | P1 | Stale decision kept levels and the word BUY/SELL on screen | see round 5 | overlays removed, STALE action, intel_age_s | test_integration_review.py, decision.spec.ts |
| 37 | P1 | Intel worker froze on exceptions / spun at start-up | see round 5 | error record + back-off | test_integration_review.py |
| 38 | P2 | Displayed setup != decided setup | see round 5 | eligible setup displayed | test_the_displayed_setup_is_the_one_the_decision_is_based_on |

## Round 6 (2026-10-14)
| # | Sev | Bug | Fix | Test |
|---|---|---|---|---|
| 39 | P0 | Equity inferable from ratio reason strings | constant reasons | test_privacy.py::test_risk_reasons_are_constant_strings_independent_of_the_account |
| 40 | P1 | `lot` of a BLOCKED plan pinned equity under spread sweep | no lot on non-eligible plans | test_a_blocked_decision_publishes_levels_but_no_lot |
| 41 | P0 | Any web page could read the decision (WebSocket without Origin/Host check; DNS rebinding) | loopback Host/Origin allow-list | test_http_and_websocket_refuse_foreign_host_and_origin (mutation-checked) |
| 42 | P1 | Failed recompute republished the pre-error setup | discard + back-off | test_a_failed_recompute_discards_the_old_setup_instead_of_republishing_it |
| 43 | P1 | Stale text stayed on screen; backend cache served BUY forever | blanking, `served_intel()` | decision.spec.ts F6 + test_the_backend_never_serves_an_old_decision_as_current |
| 44 | P2 | Out-of-order frames; race on the payload age | seq guard; `publish_intel` | decision.spec.ts F6, test_payload_is_published_with_its_age_and_a_monotonic_sequence |
| 45 | P1 (P6) | SELL stop triggered on the bid high instead of the ask | ask-side trigger | test_sell_stop_is_triggered_by_the_ask_not_the_bid_high |
| 46 | P2 (P6) | A trade absent at one cost level crashed run_trades | None per level, stats skip it | test_a_trade_absent_at_one_cost_level... |
| 47 | P1 (P6) | Seal did not freeze boundaries/dataset; overwritable; crash burned the holdout silently | frozen boundaries, dataset hash, run log, STARTED/CRASHED/COMPLETED marker, --dry | test_seal_verification, test_fixed_boundaries_cannot_drift_when_the_store_grows |

## Round 6b (2026-10-14)
| # | Sev | Bug | Fix | Test |
|---|---|---|---|---|
| 48 | P1 | Error back-off hot loop (88k publishes/s) | clear the event in the back-off | test_the_error_backoff_never_becomes_a_hot_loop (mutation-checked) |
| 49 | P2 | Stale backend WAIT kept eligible/OK fields | overwritten | test_the_backend_never_serves_an_old_decision_as_current |
| 50 | P2 | next_required hid the real blocker | gate-specific conditions | test_next_required_names_the_real_blocker |
| 51 | P2 | Host/Origin parser holes (userinfo+port, foreign local port, testserver) | urlsplit authority + same-origin port | test_host_origin_parser_rejects_userinfo_port_tricks_and_foreign_ports |
| 52 | P3 | SELL setups showed BUY wording as next event | NEXT_EVENT_SELL | test_sell_events_carry_the_mirrored_next_required_wording... |
| 53 | P3 | Expiry shown as exact wall clock | approximate label | decision.spec F5 BUY |
| 54 | P3 | payload/age not atomic; error payload not defensive | tuple; fallback | test_a_failing_error_payload_builder_cannot_kill_the_worker |
