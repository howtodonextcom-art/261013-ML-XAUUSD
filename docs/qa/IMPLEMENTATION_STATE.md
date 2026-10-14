# IMPLEMENTATION STATE (checkpoint; read this first when resuming)

## CURRENT CHECKPOINT (Level 6.2, 2026-10-14) - start here
- Level 6.2 (signal forensics + human decision UI; no strategy, threshold, risk-gate or V2 change): (1) WAIT audit: a labelling defect fixed (`NO_VALID_IMPULSE` instead of `AWAITING_PULLBACK` when no setup exists) and the funnel measured on development+validation data: V1 publishes about one BUY/SELL per week by policy (docs/research/V1_SIGNAL_FORENSICS.md, `benchmarks/v1_signal_funnel.py`, `results/v1/signal_funnel.json`); (2) V1 decision events: append-only `data/decisions/v1_events.jsonl`, first publication only, `/api/decisions`, payload `v1_events` + `v1_current_id`; (3) chart markers for V1 BUY/SELL/BLOCKED with tooltips, V2 SHADOW label, setup F/C labels; (4) decision hero: market bias, setup progress, plain sentence; chart sticky and taller, advanced diagnostics collapsible; (5) production-path replay tests (fixtures: development+validation bars only).
- Tests at this checkpoint: see the Release Acceptance evidence list; re-verify in a new session. Independent review of the final candidate: RED_TEAM_FINDINGS.md round 15.
- Status words unchanged: LIVE_AB_NOT_TESTED, PARITY_NOT_TESTED, Mac NOT TESTED, native zoom NOT TESTED, real DST NOT TESTED, live BUY/SELL NOT OBSERVED (no live decision has passed every gate since the event log exists; the BUY/SELL path is verified on historical replays and fixtures only).
- **Next executable actions:** (1) you: the checklist in docs/handover/HUMAN_ACCEPTANCE_CHECKLIST.md; (2) keep the gateway running: `data\decisions\v1_events.jsonl` fills as real decisions are published (back it up with the forward log); (3) a momentum/breakout idea only as a NEW pre-registered study (proposal in V1_SIGNAL_FORENSICS.md section 5).

## Previous checkpoint (Level 5.6, 2026-10-14)
- Level 5.6 (final audit, no algorithm or strategy change): A14 reviewed by an independent reviewer (round 14: 2 High, both in the UTC resolver, fixed as A15 with direct tests, a 200-world randomised simulation and mutation checks); live-candle vs UTC-store DST test added; all Markdown PowerShell commands validated and the documented backfill / evaluation commands executed; a corrupted path repaired; Research Status, Release Acceptance, checklist updated. F6 stays PARTIAL (A15 fixes have no further independent pass). MT5 / Mac / native zoom / real DST stay NOT TESTED.

## Previous checkpoint (Level 5.5, 2026-10-14)
- HEAD: see `git log -1` (Level 5.5 commits follow 5658271). Tests at this checkpoint: 471 pytest passed, 89 Playwright passed (full suites after the last code change). Re-verify in a new session.
- P0 done: UTC-keyed M1 store (`xau_gateway/utcstore.py`, `benchmarks/utc_migrate.py`, amendments A12-A14): evidence-only offsets, switch-uncertainty window, fresh-offset guard, idempotent migration with backup and rollback. Real data: 688 of 66,018 stored bars have a proven offset today (evidence starts 2026-10-13); the gateway now records HIGH, fresh offset evidence hourly and on change.
- P1 done: closures need recurring-signature evidence (never length), outcome-independent window rules incl. holes straddling the window end, evaluation entirely on the UTC timeline (`benchmarks/v2_shadow_eval.py`).
- P2: independent reviews round 12 (4 High) and round 13 (1 High, 3 Medium): all fixed with regression tests; the round-13 fixes have NO independent pass, so F6 stays PARTIAL (candidate frozen; reopen only on new evidence).
- P3/P4: docs synced (A11 threshold wording superseded by A12; KNOWN_LIMITATIONS); `docs/handover/HUMAN_ACCEPTANCE_CHECKLIST.md` for MT5, native zoom, Mac. Chrome MCP not re-run (no API/UI change in 5.5).
- Status words unchanged: LIVE_AB_NOT_TESTED, PARITY_NOT_TESTED, Mac NOT TESTED, native zoom NOT TESTED, real DST NOT TESTED, live BUY/SELL NOT OBSERVED. V1 INSUFFICIENT_EVIDENCE, ML NO_EVIDENCE_OF_PREDICTIVE_SKILL, V2 FORWARD_SHADOW_COLLECTING.
- **Next executable actions:** (1) you: the checklist (MT5 EA + DumpIndicators + `.\scripts\windows\verify_live_session.ps1 -Minutes 30`); (2) leave the gateway running across 2026-10-25 / 2026-11-01 so offset evidence brackets the real switch; (3) before any V2 evaluation: `$env:PYTHONPATH="services\gateway;services\intelligence"; .\.venv\Scripts\python.exe -m xau_gateway.backfill --hours 48 --bars-days 70 --htf` then `.\.venv\Scripts\python.exe benchmarks\v2_shadow_eval.py` (it refuses until 100 triggers AND 30 days); (4) weekly forward-log backup.

---
(older checkpoints below)


## CURRENT CHECKPOINT (Level 5.4, 2026-10-14) - start here
- HEAD: see `git log -1` (Level 5.4 commits follow 40a4039). Tests at this checkpoint: 452 pytest passed, 89 Playwright passed (full suites after the last code change); 3 further full Playwright runs under 4-process CPU load: run 1 produced no summary line within its 300 s limit (no failure printed: INCONCLUSIVE), runs 2 and 3: 89 passed. The two originally reported flakes (drag-to-pan, gateway stop/restart) were not reproduced in any run. Re-verify in a new session.
- WP-A done: gap-safe V2 evaluation (A8: entry bar must exist at trigger+60 s, 288 minutes of timeline, missing-data and data-ended classes; mutation-checked), UTC/DST clock and refusal on repeated bar stamps (A9), log integrity (A10: lock + single O_APPEND write + fsync, concurrency test found and fixed a Windows lock race), restore script with SHA-256 verification (smoke-tested: exit 0 / 4 / 2).
- WP-C done: plain-words line under the decision reason; Next Required emphasised; Playwright test for it; baselines updated deliberately.
- WP-D: MCP session (fixtures S1,S4,S5,S6,S7 rendered through the real page; live WAIT equals /api/intel; timeframe click; keyboard focus ring; live V2 trigger with SL_TOO_CLOSE observed). Native browser zoom NOT TESTED: manual checklist in docs/handover/CHROME_QA_REPORT.md.
- WP-B: adversarial review round 11 found 1 High (A8 hole rule selected trades by outcome), 5 Medium, 5 Low; all fixed with tests (A11) except L2/L3 (accepted, documented). RELEASE CANDIDATE FROZEN at the commit that follows 8951210; the round-11 fixes have regression tests and mutation checks but no further independent pass (F6 PARTIAL). Reopen only on new evidence.
- Status words unchanged: LIVE_AB_NOT_TESTED, PARITY_NOT_TESTED, Mac NOT TESTED, real DST NOT TESTED, live BUY/SELL NOT OBSERVED. V1 INSUFFICIENT_EVIDENCE, ML NO_EVIDENCE_OF_PREDICTIVE_SKILL, V2 FORWARD_SHADOW_COLLECTING (gate: 100 triggers AND 30 days after 1791960048).
- **Next executable actions:** (1) you: MT5 EA + DumpIndicators, then `.\scripts\windows\verify_live_session.ps1 -Minutes 30`; (2) weekly `.\scripts\windows\backup_forward_log.ps1`; (3) native zoom checklist and a Mac session; (4) 2026-10-25 / 2026-11-01 DST: build a UTC-keyed bar store BEFORE any V2 evaluation that spans a switch; (5) `python benchmarks/v2_shadow_eval.py` only once the gate can open.

---
(older checkpoints below)

## Previous checkpoint (Level 5.3, 2026-10-14)
- HEAD: see `git log -1` (Level 5.3 commits follow c07f12f). Rules: CLAUDE.md. Gateway: `scripts\windows\run_gateway.ps1`; open it with `scripts\windows\open_dashboard.ps1`.
- Tests at this checkpoint: 438 pytest passed; Playwright 88 passed (full suite after the last UI change; only a label string changed since, re-run below). Re-verify in a new session; do not assume.
- **Found and fixed in 5.3:** SELL `trigger_close`/`trigger_low` were written to the V2 forward log in mirrored (negated) space (amendment A1, docs/research/M1_ENTRY_V2_AMENDMENTS.md; legacy lines repaired on read, never edited); the forward logger now marks ids seen only after write+fsync, closes torn lines, reloads ids at start; the evaluation gate is measured in UTC; backup script `scripts\windows\backup_forward_log.ps1` (a backup of the 40 lines existed at 17:59 local).
- **Playwright flakes:** three different timing flakes were reproduced under load and fixed at their cause: (1) the bad-bar test hook shared `pending` with the live tick (a live candle could overwrite it before the next frame), now its own slot `__badBar`; (2) the quarantined-bar colour test counted a legitimate live partial bar, now judges only the fixture bars. The two originally reported failures (drag-to-pan, gateway stop/restart) did NOT reproduce in 30+ repeated runs under CPU load: cause unknown, status PARTIAL.
- UI: "Next required" lines are emphasised, confirmed M1 trigger is labelled "CONFIRMED (closed bar, research observation)"; visual baselines for the decision card were updated deliberately.
- Independent review: round 9 (Level 5.2) fixed; round 10 (fresh reviewer over the 5.3 changes) is recorded in RED_TEAM_FINDINGS.md when finished. F6 stays PARTIAL until the findings of the latest round are fixed and re-reviewed.
- Status words: LIVE_AB_NOT_TESTED, PARITY_NOT_TESTED, native zoom NOT TESTED, Mac NOT TESTED, real DST NOT TESTED, live BUY/SELL NOT OBSERVED. V1 INSUFFICIENT_EVIDENCE, ML NO_EVIDENCE_OF_PREDICTIVE_SKILL, V2 FORWARD_SHADOW_COLLECTING (gate: 100 triggers AND 30 days after 1791960048).
- **Next executable actions:** (1) you: MT5 EA + DumpIndicators, then `scripts\windows\verify_live_session.ps1 -Minutes 30` (it prints NOT TESTED honestly until then); (2) weekly `backup_forward_log.ps1`; (3) 2026-10-25 / 2026-11-01 DST checks; (4) native zoom + Mac; (5) `.\.venv\Scripts\python.exe benchmarks\v2_shadow_eval.py` only when the gate can open (it refuses before); (6) reviewer pass over any later change.

---
(older checkpoints below)

Updated: 2026-10-14 (Master Prompt Level 5.1). Rules: CLAUDE.md. Product contract: docs/product (reconstructed; acceptance matrix is the status source). Check `git log` / `git status` first. Gateway: `scripts\windows\run_gateway.ps1` (prints the dashboard URL with the one-time token) -> http://127.0.0.1:8765 (authentication ON).

## Baseline at the start of Level 5.1 (reported, then re-verified)
6cfd8ba: 347 pytest, 59 Playwright, P6 INSUFFICIENT_EVIDENCE, P7 NO_EVIDENCE_OF_PREDICTIVE_SKILL, holdout unused.

## Done in Level 5.1 (evidence in the cited files)
- **Mode B audit and fixes:** EA v1.1 (paginated CopyTicks, `want = page + g_last_cnt` after the Python model of the algorithm lost ticks when more than a page shared one millisecond; account_ref in the file name; `#gap` markers); reader gap/restart detection; `ab_capture.py` identity gate (mismatch, missing header, unpinned account, unverified Mode A, symbol difference => exit 4, no result file). docs/architecture/MODE_B.md, docs/qa/MT5_LIVE_VERIFICATION.md, scripts\windows\verify_live_session.ps1.
- **Security:** token authentication (HttpOnly SameSite=Strict cookie + bearer + WebSocket handshake), rate limit, bind guard, Host/Origin with optional private hosts only while authenticated; threat model docs/architecture/THREAT_MODEL.md; token file git-ignored.
- **Privacy:** lot hidden by default (privacy mode); public decision byte-identical across affordable accounts over a 60-step price path (tests); reveal only by start-up env; reveal mode leaks equity to <1% (tested, mutation check).
- **Latency/reliability:** heavy recompute moved to a worker process (benchmarks/gil_contention.py: scheduling-delay p99 19.6 ms in-process -> 0.11 ms process); end-to-end instrumentation (`pub_wall_ms`, `window.__lat`) and `benchmarks/e2e_latency.mjs` in real Chrome (results/p3); intel seq starts at wall-clock ms; DST mixed-window fix in OffsetEstimator (it could report a confident wrong 2.5 h offset); synthetic DST tests.
- **UI/QA:** visual regression baselines (5, decision card); interactive Chrome DevTools MCP QA: unauthenticated 401, token login, gateway stop -> DISCONNECTED/STALE with nothing actionable, restart -> reconnect with a new seq, no duplicate bars; emulated viewports/zoom (docs/qa/MCP_BROWSER_QA.md).
- **Docs synchronised:** README, KNOWN_LIMITATIONS, RELEASE_ACCEPTANCE, PRODUCT_ACCEPTANCE_MATRIX, RED_TEAM_FINDINGS.
- **Research integrity:** nothing in BACKTEST_PREREGISTRATION / CLARIFICATIONS / AMENDMENTS / ML_SHADOW_PREREGISTRATION was edited; no holdout bar was loaded by P6 or P7 code paths (`cut_bars` at the frozen `val_end`); no candidate or threshold was tuned.

## Status words (gates)
LIVE_AB_NOT_TESTED. Indicator parity NOT TESTED. Native browser zoom NOT TESTED (emulated only). Mac NOT TESTED. Real DST NOT TESTED. Live BUY/SELL NOT OBSERVED. F6 independent review: PARTIAL (see RED_TEAM_FINDINGS.md for the last pass and what was fixed after it).

## Next executable actions
1. **You (manual, about 40 min):** follow docs/qa/MT5_LIVE_VERIFICATION.md (attach `XauTickLoggerModeB`, run `DumpIndicators`), then `scripts\windows\verify_live_session.ps1`. Record the real outcome; choose Mode A / B / hybrid by the stated decision rule.
2. On 2026-10-25 (EU) and 2026-11-01 (US) check the server-offset logic live (`/api/health` detail) and the candle buckets across the switch.
3. Native browser zoom 100/125/150/200% by hand (or with a tool that drives the browser UI), and a Mac session over an SSH tunnel.
4. Research V2 only as a NEW pre-registered study on new future data (the P6/P7 holdout is not reusable as unseen); see docs/research.
5. Optional: Mode B as a gateway source only if the A/B decision rule is met and a second independent review passes.

## Known open items
M1 bar 2026-10-13 16:58 quarantined; thresholds unvalidated; approximate expiry times; no TLS; drawing tools are client-side only. Full list: docs/qa/KNOWN_LIMITATIONS.md.


## CHECKPOINT (end of Level 5.1 session)
- Tests: 392 pytest passed; 74 Playwright passed (real Chrome 155, incl. 5 visual-regression baselines); mutation checks recorded per fix.
- Independent reviews this session: round 7 (final pass over 6cfd8ba..e4c6ae5) and round 8 (verification of the round-7 fixes): real defects found and fixed each time; no Critical/High in round 8. Gate F6 stays PARTIAL: the round-8 fixes have no further independent pass.
- Interactive MCP QA (Chrome DevTools MCP): unauthenticated 401, token login, gateway stop/restart reconnect, drawing H-line/trend guard/Delete/Undo/reload persistence (docs/qa/MCP_BROWSER_QA.md). Native browser zoom NOT TESTED.
- Latency: docs/qa/LATENCY_REPORT.md (end-to-end in Chrome, GIL contention at 50 Hz and a 300 Hz burst). Heavy analysis runs in a worker process with a parent watchdog.
- Security: token authentication, signed expiring cookie, WebSocket handshake auth, limiter, privacy mode (reference-account sizing, no lot), threat model with accepted residuals.
- The API token was rotated at the end of the session (the previous value appeared in a QA transcript): `configs/api_token` is a new file; open the dashboard with `scripts\windows\open_dashboard.ps1`.
- Status words unchanged: LIVE_AB_NOT_TESTED, indicator parity NOT TESTED, native zoom NOT TESTED, Mac NOT TESTED, real DST NOT TESTED, live BUY/SELL NOT OBSERVED.
- Next: the manual MT5 session (docs/qa/MT5_LIVE_VERIFICATION.md), 2026-10-25 / 2026-11-01 DST checks, native zoom and Mac checks, any research V2 as a NEW pre-registered study on new data.

## CHECKPOINT (end of Level 5.2 session, 2026-10-14)
- Done: WP-A peer guard (real-process test) + exit-code labels; WP-B checklist only (LIVE_AB_NOT_TESTED, PARITY_NOT_TESTED); WP-C V2 shadow (pre-registration afd688e, code 2e02edf, forward evaluation gated); WP-D five-region UI, layers, a11y; WP-E MCP session + Playwright (docs/handover/CHROME_QA_REPORT.md); WP-F P6/P7 conclusions unchanged, holdout unopened; WP-G docs/handover.
- Independent review round 9 found 1 High (V2 job could stall V1) + 4 Medium + lows: fixed with tests (RED_TEAM_FINDINGS.md). The fixes have no further independent pass: F6 stays PARTIAL.
- Tests: 433 pytest passed; Playwright 88 (one run flaked 2, see KNOWN_LIMITATIONS). Gateway running on the fixed code; V2 forward log collecting (`data/shadow/v2_events.jsonl`).
- Release gate: RESEARCH BETA (docs/qa/RELEASE_ACCEPTANCE.md). Not a profitable trading system.
- Next: (1) you: MT5 EA + DumpIndicators, then `scripts\windows\verify_live_session.ps1 -Minutes 30`; (2) rotate `configs/api_token`; (3) 2026-10-25 / 2026-11-01 DST checks; (4) native zoom + Mac; (5) re-run `benchmarks/v2_shadow_eval.py` once 100 triggers and 30 days exist; (6) a reviewer pass over the round-9 fixes.
