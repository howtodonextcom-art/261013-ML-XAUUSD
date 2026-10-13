# M1 BAR MISMATCH — ROOT CAUSE ANALYSIS

Status: **PARTIAL** — one bar explained only as "history revised later" (observed once), one bar unexplained and quarantined.
Date of investigation: 2026-10-13, MetaQuotes-Demo, XAUUSD, MT5 build 6259. Times below are MT5 server time (UTC+3).

## Initial report
Of 240 M1 bars, 238 matched exactly (OHLC + tick_volume). Mismatches: **16:58** (MT5 tick_volume 322, engine 316, low 4169.44 vs 4169.45) and **19:08** (238 vs 236).

## Method
All comparisons use MT5's own tick history (`copy_ticks_range` / `copy_ticks_from`), not the gateway cursor, so the original two mismatches cannot be a gateway cursor/dedupe/pagination defect.
Scripts: `benchmarks/candle_parity.py`, `range_window_probe.py`, `history_settle_probe.py`, `live_vs_history.py`, `scripts/windows/data_qa.py`.

## Bar 19:08 — transient, cause only partly established
| Time of query | Same window `[b0-2, b0+61]` | bid-flag ticks | MT5 bar tick_volume |
|---|---|---|---|
| ≈19:15 | | 236 | 238 |
| ≈20:00 | | 238 | 238 |

Identical query, different answer at two times → MT5 tick history for that bar was **completed/revised after ≥ several minutes**. Not established: why, and how often. The settle probe over 7 later bars (19:48–19:54) showed history complete **1 s after close** and never mismatching; so it is **rare** and **not reproduced**. Hypotheses A–M from the task: none other is supported (the window result is stable for every window with end ≥ bar end).
Consequence (implemented): parity only counts bars from hourly chunks older than a settle window (`--settle-s`, default 900 s); the live-vs-history check must be repeated later for recent bars.

## Bar 16:58 — persistent, unexplained → quarantined
- 316 bid-flag ticks, min bid 4169.45 in **every** retrieval variant: windows from `[b0, b0+60]` to `[b0-300, b0+300]`, `copy_ticks_from` with counts 1000/5000/50000, hourly and 6-hour retrieval (equal multiset, 121 977 ticks both ways).
- MT5's bar says 322 ticks and low 4169.44; no tick at 4169.44 exists in the terminal's tick history. Edge/boundary ticks (±100 ms), duplicate timestamps (0), flags (1026/1028/1030/1158) do not explain it.
- Most consistent explanation: the broker's tick history lacks ~6 ticks that the server used when building the bar. **Unproven**; the live capture did not cover this bar.
- Action: bar quarantined with reason `QUARANTINED_UNEXPLAINED_MT5_TICK_HISTORY_INCOMPLETE` (kept in data, excluded from the certified comparison set, reported).

## Defects found in my own code while investigating (all fixed, regression tests added)
1. **Cursor pruning bug** (found by live-vs-history: 104 826 live ticks vs 3 925 in history). Occurrence state was pruned earlier than the second-granular re-read window, so old ticks were re-emitted as "new/late". Fixed; `test_long_polling_simulation_emits_each_tick_exactly_once`, `test_prune_never_drops_state_the_next_read_can_return`.
2. **Correction of an earlier claim:** I stated that live MT5 ticks arrive out of order. That was **wrong**, a symptom of defect 1. After the fix, a 417 s live capture matched MT5 history exactly (1806 = 1806, 0 missing, 0 extra, 0 late). The late-tick handling in `CandleEngine` stays as defensive behaviour, but no real late tick has been observed.
3. Cold-start marked catch-up ticks as late (fixed, test added).
4. `certified_parity` wrongly excluded the last closed bar (fixed, test added).
5. SQLite connections were never closed (fixed).
6. Live chunks written by the buggy cursor (`live-*` before the fix) are marked `superseded` in the manifest with quality `BUGGY_CURSOR_DUPLICATES_2026-10-13`; files are kept.

## Cause checklist (task section 2.2)
| | Result |
|---|---|
| A cursor +1 loses same-ms ticks | Not the cause of the two bars (history-based). New cursor tested with 2/10/100 same-ms ticks |
| B/C same timestamp / dedupe | 0 duplicate-looking ticks in 654 983 ticks; occurrence counting used |
| D batch size / E pagination | Not involved in history reads; continuation paging tested |
| F minute boundary | No boundary ticks in either bar |
| G timezone/bucket | 2399 bars match, so bucketing is right |
| H Bid vs other basis | Bid OHLC exact for 2399 bars |
| I started mid-bar | Not applicable (history-based) |
| J history differs | **Supported for 19:08 (once); suspected for 16:58** |
| K tick_volume rule | Fixed earlier: count only `flags & 2` |
| L restart/loss unrecorded | Not applicable |
| M rollover/session | Bars are not in a rollover window. This server has a 2 h daily break 23:00–01:00 (observed gap 22:59→01:00) |

## Acceptance gate (task 2.4)
- Eligible completed bars: **2399 compared, 2399 exact** (price tol 1e-6, tick_volume tol 0). Status `CERTIFIED_WITH_QUARANTINE`.
- Excluded: 1 quarantined (reason above), 42 `NO_TICK_COVERAGE_FOR_MINUTE`.
- Root cause: 19:08 partially explained, 16:58 unexplained but isolated. Regression tests present. No silent loss: live vs history over 417 s exact.
- Limits: sample is ~48 h (one live capture of 7 min). Not a proof for other sessions, other brokers or rollover periods.
