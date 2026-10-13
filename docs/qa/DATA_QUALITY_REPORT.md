# DATA QUALITY REPORT

Generated from `scripts/windows/data_qa.py` (raw output: `data/qa_latest.json`, local, not committed) on 2026-10-14. Feed: MetaQuotes-Demo XAUUSD. Scope: historical ticks of server days 2026-09-29 -> 2026-10-13 (14 days), M1 bars 70 days, HTF bars up to 2 years (H4).

## Integrity
- Manifest verification (sha256 of every file): **no problems**.
- Isolation: all numbers below are filtered to `mt5_hist_*` sources, server MetaQuotes-Demo, symbol XAUUSD.

## Tick checks (4 265 178 ticks)
| Check | Result | Note |
|---|---|---|
| Invalid quotes (<=0 or bid>ask) | 0 | |
| Zero-spread ticks | 0 | |
| Duplicate-looking ticks (same msc, bid, ask, flags) | 0 | reported only; cannot prove true duplicates |
| Median spread | 0.36 | price units |
| Abnormal-spread ticks (>5x median) | 1 780 (0.04%) | candidates, **not investigated** |
| Spike candidates (single-tick jump >8x median move that reverts within 3 ticks) | 969 | candidates, **not investigated** |
| Tick gaps > 60 s | 10 | all explained by the daily break (2.0 h at 22:59 server) or the weekend (50 h) |
| Max tick gap | 180 010 s | weekend (Fri 22:59 -> Mon 01:00 server) |

## Bar checks
| Check | Result |
|---|---|
| M1 bars | 65 906 (2026-08-04 -> 2026-10-13) |
| Missing-minute total | 34 894 min = session breaks (50 detected: 10 weekends + daily breaks); not filled, no synthetic bars |
| Zero-spread bars | 0 |
| tick_volume outliers (robust z > 6) | 0 |
| Tick-size conformity | OK, tick size 0.01 read from symbol metadata (not hard-coded) |
| Session-boundary ("rollover") bars | 500 bars (5 before + 5 after each of 50 breaks), derived from the data |
| Rollover bars with >= 2 independent anomaly features | **0** |

## M1 parity (certified)
Status **CERTIFIED_WITH_QUARANTINE**. Price tolerance 1e-6, tick_volume tolerance 0.
- Compared **13 198**, exact **13 198**, mismatches 0.
- Overall coverage: 13 198 / 65 906 = **20.0%** of stored M1 bars (ticks cover only the last 14 days; M1 bars cover 70 days).
- Excluded 52 708: `NO_TICK_COVERAGE_FOR_MINUTE` 52 706, `LOCAL_BAR_STILL_OPEN` 1, `QUARANTINED_UNEXPLAINED_MT5_TICK_HISTORY_INCOMPLETE` 1 (bar 2026-10-13 16:58; see M1_BAR_MISMATCH_RCA.md).
- The quarantined bar is excluded from certified sets by construction and is labelled `HISTORICAL_QUARANTINED` in the chart API; it must not enter training sets by default.

## Higher-timeframe aggregation parity
M5 11 070/11 070, M15 4 393/4 393, H1 1 098/1 098, H4 299/299 exact; 0 mismatches (buckets entirely inside the stored M1 range).

## Hourly coverage / seam (`coverage.py`)
337 server hours inspected: HIST_ONLY 219, BOTH_MATCH 1, LIVE_ONLY 1, MARKET_BREAK 116; **UNRESOLVED_GAP 0**, BOTH_DIFFER 0. Of 221 hours with M1 bars, 100% have ticks. `continuous = true` holds for this inventory only.
Seam: the former 2563 s gap between history and live (19:00-19:42) is now covered by the historical hour chunk; hour 19:00 compares history vs live: BOTH_MATCH. Live-vs-history identity was exact on the 417 s capture and on the 3-session crash experiment (541/541).
The hour after the settle window (about the last 15 min and any recent hour) is LIVE_ONLY by design: history is not trusted until it settles (one observed history revision, see RCA).

## Not done / limits
- Spike and abnormal-spread candidates are unexamined; no rollover anomaly exists in this sample, which says nothing about other periods or brokers.
- DST transitions are not covered by this sample.
- 80% of M1 bars have no tick-level parity because ticks were not backfilled beyond 14 days (a deliberate size/time bound).
