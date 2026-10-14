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

## A8 (2026-10-14, Level 5.4 WP-A1): gap-safe evaluation (implementation clarification; no evaluation had run)
The first evaluator was index-based: "the M1 bar after the trigger bar" was the next ARRAY row and "288 M1 bars" was 288 available rows. With holes in the stored M1 timeline this fills at the wrong minute and stretches the timeout. Clarifications (the registered text says "OPEN of the M1 bar after the trigger bar" and "timeout 288 M1 bars"; they are read as timeline minutes):
- The entry bar must be the M1 bar stamped trigger_bar_time + 60. If it does not exist: `NOT_COUNTED:ENTRY_BAR_MISSING` (no fill is invented).
- The position lives in 288 minutes of timeline from the entry bar; bars that do not exist inside a market closure (daily break, weekend) do not extend it. A window that outruns the stored data ends `INCONCLUSIVE` (`DATA_ENDED_BEFORE_EXIT`), never a timeout result.
- SUPERSEDED BY A11 (the first formulation excluded trades by their own outcome).
- Counted-out trades are reported in the counters, never silently dropped. SELL/BUY mirror tests are parametrised. `simulate_outcome` itself (also used by P6) is unchanged.

## A9 (2026-10-14, Level 5.4 WP-A2): UTC and DST
- The 30-day gate is a pure UTC difference from 1791960048 (unchanged).
- Each new log record stores `server_utc_offset_s`. `clock()` converts the registration instant with the offset of the earliest record and "now" with the offset of the latest, so a DST switch inside the forward period cannot shift the gate.
- Limitation, stated: M1 bars are stored with SERVER time stamps. A fall-back hour repeats stamps; the evaluator then REFUSES (`REFUSED_NON_MONOTONIC_BAR_TIMES`) instead of interleaving two different hours; a spring-forward hour appears as a 60-bar closure-type hole. A UTC-keyed bar store is required before an evaluation that spans a real server DST switch (the first real switches are 2026-10-25 / 2026-11-01: real DST NOT TESTED).

## A10 (2026-10-14, Level 5.4 WP-A3): log integrity
Appends are serialised by a lock file and written with one O_APPEND write plus fsync (a concurrency test with four writers found a Windows lock race, fixed). Restore only from a backup whose SHA-256 matches `MANIFEST.sha256` and only with the gateway stopped (`scripts\windows\restore_forward_log.ps1`). Events that become knowable while the gateway is down are not logged afterwards (not observed live = never evidence); downtime therefore reduces coverage, never inflates it.

## A11 (2026-10-14, review round 11): outcome-independent sample rules (supersedes the hole rule of A8)
The independent reviewer showed (by running it) that the A8 hole rule looked only up to the simulated exit, so a trade with a 8-bar hole after a quick take-profit was kept while the same trade timing out was dropped: selection by outcome. Corrected rules, all decided from the DATA WINDOW alone, never from the simulated result:
- window = the entry bar plus 288 minutes of timeline; if the stored data does not yet cover the whole window: `NOT_COUNTED:WINDOW_NOT_COMPLETE` (even if the trade would have exited early);
- [SUPERSEDED BY A12: the fixed 119-bar threshold below is replaced by closure EVIDENCE] a hole of 1..119 missing M1 bars anywhere in the window is missing data (the stored history shows market closures of exactly 120 bars and longer: daily break and weekend; a feed outage shorter than that cannot hide as a "closure"): `NOT_COUNTED:MISSING_DATA_IN_WINDOW`; holes of 120+ bars are closures (gap stop fills at the open);
- like-for-like costs: a trade that cannot be counted under any one cost scenario is excluded from ALL scenarios (previously it vanished only from that scenario's mean, which could flip the "positive at +0.3 slippage" criterion);
- the four chronological quarters are quarters of the FORWARD PERIOD (registration to now), not of the span of the trades;
- B2 random comparator uses each trade's real ATR5 (previously stop/1.5);
- the first real evaluation MUST be published together with a sensitivity table: with and without the 40 legacy events (A5), and with and without the excluded counters above. No result is claimed from a single specification.
`NOT_COUNTED:*` counters are always written into the result file. A5 and A8 changed the code after the registration commit; whether they are "clarifications" or "protocol changes" is a judgement the registration cannot settle: they are disclosed here, none was made after any outcome was seen (the gate has never opened and `results/v2/forward_eval.json` does not exist).

## A12 (2026-10-14, Level 5.5): UTC-keyed bar store, evidence-based closures, UTC evaluation (supersedes the length threshold of A11 and the server-time refusal of A9)
- **UTC store** (`xau_gateway/utcstore.py`, dataset kind `bars_m1_utc`, derived and additive; `benchmarks/utc_migrate.py`): one row per UTC instant with the original server stamp, the offset applied, status and provenance. An offset is accepted only when MEASURED evidence of that same offset brackets the bar (gateway HIGH-confidence measurements recorded at least hourly and on change, plus the offset recorded at each capture-session start). Bars between two different measured offsets (a switch happened there), bars that fit two offsets (the repeated fall-back hour) and bars far from any evidence are NOT written; no candle is invented. Migration is idempotent, backs up the manifest first, never touches the legacy chunks; `--rollback` removes only the derived kind (files are moved aside).
- **Real data:** on 2026-10-14 the stored history (66,018 M1 bars from 2026-08-04) yielded 688 bars with proven offsets (evidence exists only since 2026-10-13); the rest are excluded as UNKNOWN_NO_EVIDENCE. They are not needed: only bars after the registration instant are evaluated.
- **Closures need evidence, never length:** a hole is a market closure only if it matches a RECURRING closure signature (>= 3 occurrences of the same start/end clock times in broker server time; weekday included only for weekend-type holes), learned from the stored history. Every other hole in the position window, of any length (a 3-hour feed outage included), is missing data and the trade is not counted. The window end falling inside an evidenced closure completes the window once the market has reopened (exit at the last pre-closure close; no price is assumed during the closure); while the market is still closed or the data has not arrived the trade is `WINDOW_NOT_COMPLETE`.
- **Evaluation on the UTC timeline:** event stamps are converted with the offset stored in each record (`server_utc_offset_s`; legacy records via the measured-evidence resolver; unprovable events are excluded and counted), bars come from the UTC store, the registration instant and the gate are UTC. A server DST switch inside the forward period can no longer repeat or skip evaluated stamps. Before an evaluation run `python -m xau_gateway.backfill --hours 48 --bars-days 70 --htf` (so the forward-period M1 bars are stored) and then `benchmarks/v2_shadow_eval.py`.
- Limitation, stated: closure signatures need history: until three repeats exist for a signature every hole counts as missing data (conservative). Real DST (2026-10-25, 2026-11-01) remains NOT TESTED against live data.
