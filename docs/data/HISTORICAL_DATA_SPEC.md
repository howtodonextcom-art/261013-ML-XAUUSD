# HISTORICAL DATA SPEC

Scope: MetaQuotes-Demo, XAUUSD, MT5 build 6259. Everything here was measured on this feed on 2026-10-13/14; it is not claimed for other brokers.

## Sources and provenance (never mixed silently)
| source_id | what | how obtained | immutable? |
|---|---|---|---|
| `mt5_hist_ticks` | MT5 historical ticks, hourly chunks | `copy_ticks_range`, window `[h, h+3602)` filtered to `[h, h+1h)` ms-exact | chunk replaced only if re-fetch differs (old file kept, marked superseded) |
| `mt5_hist_bars` | MT5 bars M1/M5/M15/H1/H4 | `copy_rates_range`; M1 by day, others by 30-day chunk | same |
| `mt5_py_poll` | locally captured live ticks (Mode A) | `copy_ticks_from` cursor, capture session per gateway start | never superseded |
Reads are always filtered by `source_id`, `server`, `symbol` (and `session` when needed); `Store.read_table` with no filter is explicit mixing.

## Time base
- MT5 times are **broker server wall-clock expressed as an epoch**. Observed offset to UTC: **+10800 s**, measured live with a 50-sample estimator (residual -0.12 s, confidence HIGH). It changes with the broker's DST; the estimate carries a confidence and **no integrity logic depends on it** (catch-up and gap detection compare server time with server time).
- Parquet partition `date=` is the **server-time** date.
- A single sample is never trusted: a tick whose age is a multiple of 15 min cannot be told apart from a fresh tick with another offset (unit test `test_single_sample_is_never_more_than_provisional`).
- DST: bars are bucketed on the server wall clock, so buckets stay aligned across a DST switch. **NOT TESTED against real data across a switch** (history parity range 2026-08..10-13 contains none).

## Bucket convention (measured)
For M5, M15, H1, H4 (and D1) every MT5 bar time satisfies `time % seconds == 0` on the server epoch (checked over 3000 bars each, H4 since 2024-11, so the rule held across DST changes). H4 bars start at server hours 0,4,8,12,16,20. Aggregation `floor(t / sec) * sec` therefore reproduces MT5.
Evidence: M1 aggregated to M5/M15/H1/H4 equals native MT5 bars exactly: **M5 11070/11070, M15 4393/4393, H1 1098/1098, H4 299/299, 0 mismatches** (`quality.htf_parity`, `tests/integration/test_htf_parity_store.py`).

## Session structure observed
- Daily break: server 22:59 -> 01:00 (2 h, no bars, no ticks) Mon-Fri, e.g. gaps of 7200 s at 09-29 .. 10-12; weekend break about 50 h (Fri 22:59 -> Mon 01:00).
- Consequently "rollover window" is derived from data (`timeutil.session_boundary_bars`: 5 bars before and after any gap >= 30 min), not from a fixed clock window. Result on the current store: see DATA_QUALITY_REPORT.

## Candle definition
- Price basis **Bid** (what MT5 draws). `tick_volume` = number of ticks with `flags & 2` (TICK_FLAG_BID): exact on 13198 compared M1 bars.
- A bar is built from the first observed tick of its bucket; no tick is fabricated at :00; missing minutes stay missing; late ticks never rewrite closed bars.

## tick_volume / OHLC differences with MT5
Known and quarantined: M1 bar 16:58 on 2026-10-13 (RCA in `docs/qa/M1_BAR_MISMATCH_RCA.md`).

## Warm-up
M1 history is capped by the terminal (`maxbars` 100000, about 70 days). Indicators need native higher-timeframe history: H4 has 3092 bars (since 2024-10), H1 5773, M15 7540, M5 11070 in the store. `multitf.warmup_status`: EMA200 needs >= 200 bars (MINIMUM_ONLY) and >= 600 (CONVERGED, a documented rule of thumb, not an exact bound). One week of M1 gives only 38 H4 bars -> INSUFFICIENT_HISTORY (test `test_warmup_not_assumed_from_one_week_of_m1`).

## Schema
Tick: source_id, terminal_ref, server, symbol, time_msc, bid, ask, last, volume, flags, received_at_ns, quality_flags, dataset_version, capture_session_id, provenance. Bars: source_id, server, symbol, tf, time, OHLC, tick_volume, spread, real_volume, dataset_version. Schema v2; v1 files are read with null-filled new columns.

## Tick identity limit
MT5 gives no tick id. Identity = (time_msc, bid, ask, last, volume, flags) + occurrence index. Delivery is exactly-once per *observed occurrence*; bit-identical ticks in one millisecond are told apart only by count. This is not a proof of exactly-once at the exchange.
