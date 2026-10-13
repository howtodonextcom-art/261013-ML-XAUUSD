# BACKFILL REPORT

Command: `python -m xau_gateway.backfill [--hours N] [--bars-days N] [--htf]` (terminal, server and account come from `configs/source.json`; identity verified before any read; refuses to run without a pinned server). Rate limit 50 ms between hourly tick requests; recent data newer than `--settle-s` (900 s) is skipped.

## Runs (2026-10-13/14)
| Run | Scope | Result |
|---|---|---|
| 1 | 6 h ticks, 2 d M1 | 121 977 ticks, 2 413 bars; rerun: 6/6 tick chunks identical, 2/2 bar chunks identical |
| 2 | 48 h ticks, 3 d M1 | 653 141 ticks, 40 chunks (8 empty hours = weekend/daily break) |
| 3 | 70 d M1 + native M5/M15/H1/H4 | M1 65 906 bars; M5 11 070 (60 d), M15 7 540 (120 d), H1 5 773 (365 d), H4 3 092 (730 d) |
| 4 | 72 h ticks | 669 972 ticks; 40 older chunks superseded (schema v1 -> v2 columns), files kept |
| 5 | **14 d ticks** (336 h) + 70 d M1 + HTF | **4 265 178 ticks, 220 non-empty chunks, 116 empty hours** (market closed), 49 of 51 M1 chunks identical to run 3 |

Elapsed time per run was not recorded (not measured). Terminal limit read: `maxbars = 100000` (M1 70 days = 65 906 bars fits).

## Verification
- Idempotent: reruns report `identical`, never duplicate rows (`Store.read_table` row count equals active-file rows: 4 265 178 hist ticks).
- Checksums: `Store.verify()` clean after every run.
- Bar counts reconciled against MT5: M5/M15/H1/H4 native bars equal M1 aggregation exactly on the overlapping span (DATA_QUALITY_REPORT).
- Empty hours are quarantined with reason `EMPTY_HOUR` (the table records one row per run per hour, so repeated runs add duplicate rows; harmless but untidy).

## Size
43 MB parquet on disk (including superseded files kept for provenance). Expansion rule used: first run small, then 14 days after the size estimate; multi-year tick history is **not** downloaded.

## Known issues
- Run 4 superseded 40 chunks only because the schema gained columns; content (ticks) was identical. A schema-aware comparison would avoid the extra files; not implemented.
- The moving "today" M1 chunk is superseded on each run by design.
