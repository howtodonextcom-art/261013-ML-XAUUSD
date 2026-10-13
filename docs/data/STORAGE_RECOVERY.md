# STORAGE & RECOVERY

## Layout
`data/store/{ticks|bars_m1|bars_m5|bars_m15|bars_h1|bars_h4}/source=<id>/server=<server>/symbol=<sym>/date=<server date>/<chunk>-<sha12>.parquet` (zstd) plus `manifest.sqlite` (WAL): `files` (path, rows, key range, sha256, session, superseded, quality), `quarantine`, `sessions`, `checkpoints`, `meta`.
Writes: temp file -> sha256 -> atomic rename -> manifest row in one SQLite transaction.

## Guarantees (and their evidence)
| Property | Mechanism | Evidence |
|---|---|---|
| Re-running a backfill does not duplicate data | identical content hash = no-op | rerun: ticks 41 identical / 0 written; M1 49 of 51 chunks identical (the other 2 are the moving "today" chunk) |
| Changed history never silently overwrites | new file + old marked superseded, both kept | `test_changed_chunk_supersedes_but_keeps_old_file` |
| Live restart cannot overwrite an earlier session | chunk id includes `capture_session_id`; `allow_supersede=False` raises on collision | `test_A_restart_with_reset_bridge_seq_does_not_supersede_earlier_session` |
| Corruption is detected | `Store.verify()` recomputes sha256 of every file | `test_store_idempotent_and_checksum_detects_corruption`; current store: no problems |
| Reads cannot mix servers/sources/symbols | filtered `read_table` | `test_CD_read_table_filters_by_source_server_symbol_and_session`, `test_D_parity_ignores_live_ticks_and_other_servers` |

## Crash recovery design
The in-memory cursor is **not** authoritative. On start `Store.restore_cursor()` rebuilds the cursor from the **persisted** live ticks of the same source/server/symbol: the last 2 s before the persisted watermark are seeded as "already seen", then MT5 is re-read from there. Ticks consumed in memory but lost before flush are therefore re-read; ticks already on disk are not duplicated (`test_B_restart_recovers_ticks_consumed_but_not_persisted`).
If the persisted watermark is older than 600 s (server time), the gap is **not** replayed as live: the cursor restarts cold and a `RESTART_GAP_NOT_RECOVERED_LIVE` record is raised; the hole is filled by the historical backfill and is reported by the coverage inventory.

## Measured crash experiment (real MT5, `scripts/windows/crash_recovery_test.sh`)
Gateway started, **hard-killed twice** (`taskkill /F`, unflushed buffer lost), 60 s and 20 s downtime, restarted each time. Union of the 3 capture sessions vs MT5 history over the 180.9 s interior window (12 s trimmed each edge): **history 541 = live 541, missing 0, only-in-live 0, result EXACT**. Sessions are disjoint in time (no overlap rows). n = one experiment; not a statistic.
Not covered by this experiment: crash exactly between Parquet write and manifest insert (an orphan file without a manifest row is possible and would be ignored by reads; no automatic orphan sweeper yet), power loss, disk full.

## Unit-level crash/restart cases tested
crash before writer flush (B), restart with seeded cursor, overlap re-read, multiple ticks in the same ms (2/10/100), identical payloads by occurrence, batch boundary inside a ms, pagination retry, late insert flagged not lost, no re-emit during long polling (regression for the 104826-vs-3925 duplication).

## Retention
Raw ticks are never deleted. Current size: 41.9 MB parquet for 4.27 M historical ticks + 23.7 k live ticks (about 10 bytes/tick including bar files and superseded files kept on disk). Widen backfill only after estimating: 14 active days gave 4.27 M ticks, so one more week is about 2.1 M ticks (about 21 MB).

## Rollback
Delete `data/store` to start clean (it is derived data re-creatable from MT5 within the terminal's history depth); nothing outside `data/` is touched. Git rollback: revert the commit.
