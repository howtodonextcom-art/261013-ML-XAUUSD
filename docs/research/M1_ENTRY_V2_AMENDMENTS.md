# M1 Entry V2: amendments (the pre-registration M1_ENTRY_V2_PREREGISTRATION.md is frozen and unedited)

Each entry is an implementation or evidence-handling change. None changes a hypothesis, threshold, policy value, registration instant (1791960048, commit afd688e) or the evaluation gate (>= 100 triggers AND >= 30 days).

## A1 (2026-10-14): SELL trigger prices were logged in mirrored space (defect, found by inspecting the live forward log)
- **What:** the SELL scan runs on negated prices. `trigger_close` and `trigger_low` of SELL events were written negated (e.g. -4147.18). The zone and the event id were already real. BUY records were correct.
- **Impact:** an evaluator reading those fields as real prices would have produced wrong SELL entries/stops. No performance evaluation had run (the gate was never open), so no result was affected.
- **Fix:** events now carry real prices and `log_schema: 2`. The 40 lines written before the fix are NOT edited. The evaluator repairs legacy SELL records on read (`real = -stored`, marked `REPAIRED_FROM_1`), deterministic and lossless. Test: `test_event_prices_are_real_prices_for_sell_not_mirrored_ones`, `test_legacy_sell_records_are_repaired_on_read_and_the_stored_line_is_untouched`.

## A2 (2026-10-14): `v1_target` was not logged
Logged from the round-9 fix on. Earlier trigger records lack it, so the evaluator uses the registered 2R fallback for them (the registration says V1 impulse extreme "when one was active"; its absence in old records cannot be reconstructed without hindsight, so it is not).

## A3 (2026-10-14): evaluation clock
The gate is now measured in UTC (`time.time() - 1791960048`), independent of any DST offset. Server-time stamps are compared with the registration instant converted using the server offset recorded in the log (`server_utc_offset_s`, stored from the fix on; +10800 assumed for older records, measured HIGH confidence at registration). Before: a hard-coded 10800 for "now" as well.

## A4 (2026-10-14): log durability
Ids are marked seen only after write + flush + fsync; a torn last line is closed before appending; seen-ids are reloaded from the file at start; unreadable lines are counted by the evaluator, never silently dropped. Backups: `scripts/windows/backup_forward_log.ps1`.

## A5 (2026-10-14, review round 9, commit c07f12f): zone selection
The M15 zone chosen for the entry band was cached per (known swings, ATR15, close quantised to 0.25 ATR15), so the band filter used a rounded close. Now the zone SET is cached per (known swings, ATR15) and the band filter (`zone.high <= close + 0.25 ATR15`, `>= close - ...`) uses the exact close of each bar, as the registration states. Causal; may change which bars trigger compared with the first implementation. The events logged before c07f12f (40 lines at 2026-10-14 17:59 local, all at bars of that day) came from the earlier rule and are kept as logged; this is disclosed, and the first 100-trigger evaluation will be reported with and without them.

## A6 (2026-10-14, commit c07f12f): weekly concentration
`max_week_share` is the largest weekly R divided by TOTAL R (registration wording: "no single week contributing more than 40% of total R"); it fails when total R <= 0. Before: share of the sum of absolute weekly R. Stricter, wording-faithful. No evaluation had run.

## A7 (2026-10-14, review round 10): `v1_target` timing
The V1 impulse extreme is snapshotted when the shadow job is LAUNCHED (the bar close that created the trigger), not when it finishes. Records written between c07f12f and this change may carry the value read up to 10 s later (mild hindsight, disclosed).
