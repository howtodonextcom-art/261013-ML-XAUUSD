# RED TEAM / INDEPENDENT REVIEW FINDINGS

Reviewer: one real subagent in a separate context (read-only, no MT5 access, instructed to refute the implementer's claims). It ran the offline tests (54 passed at that time). Gate F6 stays **PARTIAL**: one review round happened; the fixes were verified by the implementer's own regression runs (71 pytest + 30 Chrome tests), **not re-reviewed independently**.

| # | Severity (reviewer) | Finding | Disposition |
|---|---|---|---|
| 1 | High | Pipeline thread had no exception handling or heartbeat; health could stay CONNECTED_ACTIVE while nothing was processed | FIXED: `process_tick` contains and counts errors, heartbeat, state `DEGRADED`; tests in `test_review_findings.py` |
| 2 | High | Writer dropped ticks on a failed flush without retry; the persisted watermark could skip the hole; drops not visible in the UI | FIXED: retry with backoff, bounded buffer, permanent `hole` flag, `DEGRADED`, UI shows persistence drops/hole |
| 3 | Medium | `restore_cursor` keyed by the symbol hint, not the resolved symbol (for example XAUUSD.r) | FIXED: restore runs after connect with the terminal's real server/symbol |
| 4 | Medium | The quarantine row had empty server/symbol and applied everywhere | FIXED: strict scoping, real row updated, test |
| 5 | Medium | `continuous=true` only meant "some tick in the hour" | FIXED: minute-level check against MT5 bars; *_PARTIAL statuses; the current store is still continuous (222 active hours) |
| 6 | Medium | README called replay-on-history "parity" and mixed it with live verification | FIXED: wording separates the two |
| 7 | Medium | Partial/quarantined bars drawn like normal bars; no warning on the seam | PARTLY FIXED: such bars are grey (deterministic e2e). No UI warning for the backfill/live seam yet |
| 8 | Medium | Paint loop could die on a library exception; an update could hit the previous timeframe's series | FIXED: try/catch with reload; updates applied only when the data timeframe equals the current one (e2e injects a bad update) |
| 9 | Medium | Vacuous or weak tests: a `toBeDefined()` assertion, only a coarse-to-fine timeframe check, an MQL5 scan on a missing folder, safety scan only on `services/` | FIXED: removed; median spacing must equal the timeframe exactly; the MQL5 test now SKIPS visibly; scan covers services/scripts/benchmarks/apps. NOT fixed: the HTF aggregation test self-skips without a local store |
| 10 | Low | Supersede does not check completeness; byte-hash identity superseded 40 chunks on a metadata change | PARTLY FIXED: content-based identity (219 identical on re-run); a re-fetch with FEWER rows is a visible supersede (tested) but still replaces the active file |
| 11 | Low | `received_at_ns` is process-monotonic; shutdown did not drain; `image/` not ignored; innerHTML unescaped | FIXED: documented, writer joined on shutdown, `image/` ignored, strings escaped |

Unverified assumptions listed by the reviewer that remain open: DST behaviour, frequency of late ticks beyond the 2 s window, a crash between Parquet and manifest, power loss, other servers/symbols. `crash_recovery_test.sh` kills any process listening on port 8765.
No order path was found anywhere (static analysis); there is no runtime guard if someone adds one later.


# Review round 2: P3 intelligence package (independent subagent, read-only, 2026-10-14)
It could not refute: causality of indicators and structure (40 random seeds with fat tails, cut-and-compare), no repaint, level confirmed before the breaking bar opened, closed-bar snapshot rule, absence of BUY/SELL in outputs, ATR definition.
| # | Sev | Finding | Disposition |
|---|---|---|---|
| 1 | High (verified) | `sma` turned NaN into 0: MACD signal valid from index 8 with fake values, hist/cross-age wrong for bars 25-32 | FIXED (NaN when the window holds a NaN); tests: first valid signal index 33, NaN hist/cross-age before it |
| 2 | Medium (verified) | `atr_ratio50` same cause, inflated first values (index 63-76) | FIXED; first valid index 77 asserted |
| 3 | High (verified by simulation) | MT5 comparator would report FAIL on correct definitions: MT5 seeds on the whole history, the CSV has the last 3000 bars; the earlier fake-dump test was vacuous | FIXED: verdict on the late zone only, early shown as informational; new test simulates a longer reference history |
| 4 | Low | `bar_idx` relative to the truncated window | FIXED: events carry `bar_open_time` (absolute) |
| 5 | Low | `max_bars` truncation | no defect found (30 cut points at 600 bars: identical trend/regime/labels); convergence is empirical, not proven |
| 6 | Medium | Pre-registration unverifiable (not committed before the run; file also holds the result); both candidates failed the density band | DOCUMENTED in the decision file and wording changed ("chosen by the fallback clause"); process change: pre-register by commit before running |
| 7 | Low | weak tests (`<= known_at - 900 + 900`, 3-regime assertion, oracle shares code) | FIXED the first; added a hand-computed zig-zag case; limits of the oracle documented; the 3-regime assertion kept deliberately broad (documented) |
| 8 | Suspicion | only the latest level per kind is breakable | DOCUMENTED as a design choice |
Gate F6 remains PARTIAL: P3 fixes were verified by the implementer's tests, not re-reviewed.

# Review round 3: P3 closure (independent subagent, read-only, 2026-10-14)
Confirmed as truly fixed (it ran experiments): NaN-as-zero `sma` and everything derived from it; late-zone verdict of the MT5 comparator (EMA200 seed error after 2000 bars about 2e-9; a simulated MT5 seeded on 30 000 bars vs a 3 000-bar dump: late difference 1.4e-8, PASS); absolute event times; no causality or repaint violation in zig-zag, fractal, structure events or liquidity events (300 seeds, many cut points); no trading call in `DumpIndicators.mq5`.
| # | Sev | Finding | Disposition |
|---|---|---|---|
| 1 | Medium | The comparator verdict is only valid for CSVs of at least about 2800 bars; nothing enforced it (N=2500 and below gave false FAIL) | FIXED: `MIN_BARS = 2800` in the provenance check; the MQL5 script refuses to write a dump shorter than InpBars-50 |
| 2 | Medium | Provenance failed OPEN: an empty store skipped the OHLC cross-check; an unpinned account_ref skipped the account check | FIXED: fail closed (`UNVERIFIED_FEED`, `NO_PINNED_ACCOUNT_REF`); tests for None/empty store and empty account_ref |
| 3 | Low | Overlap did not have to cover the late zone; 0.1% mismatch tolerated anywhere; dumps dated in the future accepted | FIXED: overlap must cover >= 900 of the last 1000 bars, any mismatch in the late zone rejects, future-dated dump rejected |
| 4 | Low-Medium | A swept level was dead for liquidity but still breakable for structure (34% of break events were on swept levels) | FIXED/DOCUMENTED: one lifecycle: a sweep never consumes a level; one break per level in both modules; consistency tests |
| 5 | Low | Early `return false` in the MQL5 script leaked indicator handles; it continued after an incomplete calculation | FIXED: wrapper releases on every path; fails if not calculated within 20 s |
| 6 | Medium | Pre-registration claims overstated (implementation after, not with, the pre-registration; extra degrees of freedom; k=2.5 reused on untested timeframes) | DOCUMENTED in an addendum to SWING_K_PREREGISTRATION.md; commit ordering verified: pre-registration d01eca2 < implementation 49527a5 < result |
| 7 | Low | Weak tests (liquidity prefix only 4 seeds/16 cuts, store-empty case untested, same data used as dump and store) | PARTLY FIXED: full-length prefix, artifact, empty/None store, late-zone cases added; the dump and the store in the provenance tests still derive from the same generator (documented) |
Not independently re-reviewed after these fixes: gate F6 stays PARTIAL.

# Review round 4: P4 setup lifecycle (independent subagent, read-only, 2026-10-14)
It could not refute: prefix == full (also through the whole H1 -> M15 pipeline, 3 seeds), BUY/SELL mirror (by construction; 39 random markets turned upside down twice gave 0 differences), no duplicate setups, legal transitions, `known_at` = bar close on every event, no BUY/SELL decision emitted by the machine.
| # | Sev | Finding | Disposition |
|---|---|---|---|
| 1 | Medium (verified) | A confirmation bar did not have to touch the zone: a strong bullish bar entirely above it confirmed with entry 3.1 above the zone | FIXED (`low <= zone.high` required); regression test + mutation check |
| 2 | Low (verified) | SELL evidence strings printed mirrored (negative) prices | FIXED: evidence formatted in real prices; test uses a positive-price mirrored market |
| 3 | Low (verified) | First event had `prev_state = SETUP_FORMING` instead of None | FIXED; chain-consistency test |
| 4 | Low | Test count in SETUP_LIFECYCLE.md wrong (31 vs 30) | FIXED (docs now state the real count) |
| 5 | Low-Medium (measured) | Setups could be created long after the impulse (p99 19 bars, max 47) and age was counted from creation | FIXED: creation allowed only within 20 bars of the impulse high becoming known; age counted from it |
| 6 | Low-Medium | `current_status` ignored an H4 conflict once a setup was active | FIXED: eligible + conflict => WAIT / SIGNAL_CONFLICT |
| 7 | Low | Mirror test only on one hand-built scenario | FIXED: 8 random markets upside down with price offset |
| 8 | Low | Prefix test sliced the context instead of recomputing the pipeline | FIXED: full-pipeline prefix test |
Unverified suspicions: confirm-window boundary (confirmed bars up to touch+5, timeout on touch+6) matches the specification text as now written; chase check uses the bar high by design (documented).
Not independently re-reviewed after these fixes: gate F6 stays PARTIAL.

# Review round 5: live integration, backend to browser (independent subagent, read-only, 2026-10-14)
It could NOT refute: the backend is the only decision source and the browser escapes every server field (no XSS found); BUY/SELL cannot be produced without an ENTRY_ELIGIBLE setup (adversarial `decide()` inputs); `process_tick` only sets a flag; the snapshot rule is applied first; the value per unit is the larger of the sources; no order function exists (grep). It **refuted** the privacy and staleness claims.
| # | Sev | Finding | Disposition |
|---|---|---|---|
| 1 | Critical (verified) | Equity could be reconstructed exactly from the public plan (`lot_raw * loss_distance * value_per_unit / risk_fraction`) | FIXED: `RiskPlan.public_plan()` excludes lot_raw, value per unit, loss/margin amounts and budget; the decision publishes only the public plan. LIMIT (documented): the ROUNDED `lot` with `risk_fraction` and the contract size still bounds the account size to within the lot-step rounding. The API is loopback-only and unauthenticated. |
| 2 | Critical (verified) | Reason strings carried amounts (margin needed/free, budget) | FIXED: ratios only; a test scans every number and string of the public output for account-dependent values in 5 scenarios, plus two mutations (full plan republished, amounts back in reasons) that each fail it |
| 3 | High (verified) | A stale decision still published ENTRY/SL/zone overlays | FIXED: `overlays()` returns nothing when DATA_STALE |
| 4 | High (verified) | The browser dimmed but still displayed BUY/SELL for a stale decision; a cached payload's age was ignored | FIXED: stale view shows STALE, payloads carry `intel_age_s`; e2e tests |
| 5 | High (verified) | `intel_worker` froze on an exception; a NaN spread raised | FIXED: engine error publishes WAIT / INTEL_ENGINE_ERROR (type name only); non-finite inputs give RISK_NOT_EVALUABLE; tests |
| 6 | Medium (verified) | Displayed setup could differ from the one the decision used | FIXED + test |
| 7 | Medium (verified) | Busy loop at start-up; failing heavy compute retried every 2 s | FIXED: event cleared, back-off; test counts wait() calls |
| 8 | Medium (suspected) | Partial live bar could enter the analysis; failed bar fill left gaps silently | FIXED: partial bars excluded; BAR_HISTORY_FILL_FAILED is a gate |
| 9 | Medium (suspected) | Thread-safety of fill_recent_bars / INTEL assignments | no defect found |
| 10 | Medium (suspected) | GIL pressure on the tick path from compute_heavy | PARTLY MEASURED: receipt-to-publish p99 5.5 ms (n=320) in one sample, 29 ms in another right after a restart; not measured systematically under sustained heavy compute (OPEN) |
| 11 | Low | NaN in JSON; exception text in intel.error | FIXED: strict() and allow_nan=False; only the exception type is stored |
Not independently re-reviewed after these fixes: gate F6 stays PARTIAL.

# Review round 6 (2026-10-14): independent re-review of the round-5 fixes, and independent review of the P6 engine
Two independent subagent reviewers (read-only). Both found real defects; the round-5 privacy claim did NOT hold.

## Round-5 fixes re-reviewed
| # | Sev | Finding | Disposition |
|---|---|---|---|
| 1 | High (verified) | Reason strings still leaked equity/free margin as RATIOS (`10.70 x the budget`, `347.73 x the free margin`): recomputing from public numbers gave the exact secret; the privacy test only grepped literals | FIXED: constant reason strings (`RISK_MIN_LOT_EXCEEDS_BUDGET`, `INSUFFICIENT_MARGIN`); test asserts they are identical across accounts |
| 2 | Medium (verified) | The public `lot` of a BLOCKED plan flipped at known loss distances when the spread was swept, pinning equity far more tightly than the documented lot-step bound | FIXED: a non-eligible (BLOCKED) plan carries levels and R:R but NO lot; test. LIMIT remains for ELIGIBLE decisions: the lot of a BUY/SELL still bounds equity roughly (documented) |
| 3 | High (verified) | A failed heavy recompute was overwritten two seconds later by a decision from the pre-error setup (BUY/SELL could reappear) | FIXED: heavy result discarded on failure, error published until a recompute succeeds, 10 s retry back-off; test |
| 4 | High (verified) | ANY web page could read the decision over WebSocket (no Origin/Host check; DNS rebinding also returned data) | FIXED: HTTP middleware + WebSocket check allow only loopback Host/Origin (127.0.0.1, localhost, ::1); tests incl. a mutation check; verified live: foreign Host -> 403. Limit: still no authentication (any local process can read it) |
| 5 | Medium | After a stale/closed state the plan, setup, layers and eligibility text stayed on screen | FIXED: every decision sub-panel is blanked; a backend DATA_STALE decision shows STALE (reasons kept, no levels); e2e tests |
| 6 | Low/Med | The backend cache served the last BUY forever to non-dashboard clients if the worker stalled | FIXED: `served_intel()` converts a payload older than 10 s into a stale WAIT without setup/plan/overlays |
| 7 | Low | Race: payload visible before its timestamp | FIXED: `publish_intel()` writes the age first |
| 8 | Low | Out-of-order frames could overwrite a newer decision | FIXED: sequence number + browser guard (reset on reconnect); e2e test |
| 9 | Low | WAIT/BLOCKED decisions still carried levels (stale setup levels; BLOCKED full plan) | FIXED: stale => no setup/plan; BLOCKED => levels labelled NOT ELIGIBLE, dashed grey, no size |
| 10 | Low | JSON strictness gaps (tick/health/NOT_READY paths; ndarray) | FIXED: `allow_nan=False` on every send path; `strict()` converts ndarrays |
Not refuted: loopback-only binding (netstat: 127.0.0.1 only), no account fields in /api/health, no UI/backend action mismatch, setup ids consistent across decision/plan/overlays.

## P6 engine review
No look-ahead and no result-invalidating bug found (the reviewer re-ran prefix invariance on real pre-holdout data, 0 differences; the independent 29-trade re-simulation reproduces; C6 == C4 verified). Findings and dispositions are listed in docs/research/BACKTEST_AMENDMENTS.md (spread realism, seal mechanics, protocol deviations, SELL stop on the ask, per-level absent trade, power, wording, weak tests). Not independently re-reviewed after these fixes.

# Review round 6b (2026-10-14): second independent re-review (of the round-6 fixes)
| # | Sev | Finding | Disposition |
|---|---|---|---|
| 1 | High (verified) | The new error back-off was a HOT LOOP: the event was not cleared, `wait()` returned at once; 87 948 publishes in 1 s | FIXED (event cleared in the back-off branch); regression test counts publishes, mutation-checked |
| 2 | Medium | Equity/free-margin oracles remain: `RISK_MIN_LOT_EXCEEDS_BUDGET` and `INSUFFICIENT_MARGIN` flip at exact thresholds while the entry/loss distance moves with the live price | NOT FIXED, DOCUMENTED (RISK_GOVERNANCE, KNOWN_LIMITATIONS): the information is inherent in showing a size and a feasibility verdict; mitigated only by the loopback + Host/Origin guard |
| 3 | Medium | The lot bound for an ELIGIBLE decision tightens to about 0.2% with a few dozen observations at different loss distances (lot, risk_fraction, stop distance, spread are public) | NOT FIXED, DOCUMENTED. Option for later: publish a size bucket instead of the lot, or require authentication |
| 4 | Medium | The backend's stale WAIT still carried `strategy_eligible: true`, `risk.status OK` and the 'hypothetical plan' text | FIXED: every live-looking field is overwritten; test |
| 5 | Low-Med | `next_required` hid the real blocker (conflict, spread, margin, R:R) | FIXED: conflict/stale name themselves; BLOCKED gets a gate-specific condition; tests |
| 6 | Low-Med | `expires_at` / `entry_window_ends_at` are wall-clock projections of a bar-count rule (wrong across breaks) | FIXED in wording: shown as `~HH:MM` with 'bar-count rule, later across market breaks'; values unchanged |
| 7 | Low | Host/Origin parser accepted userinfo with a numeric port (`127.0.0.1:80@evil.com`), any localhost port as Origin, `testserver` | FIXED: urlsplit-based authority, no userinfo, exact loopback names, Origin port must equal the Host port, `testserver` removed; table test |
| 8 | Low | payload and age were two assignments | FIXED: one atomic tuple |
| 9 | Low | The error-path payload was built outside its own protection | FIXED: defensive `_error_payload` with a minimal fallback; test |
Test gaps named by the reviewer and now closed: XSS in the events panel, blanking of the events panel on socket loss, the 390x844 layout, SELL wording is the dict actually used. Still open: no gateway-restart test of the browser's seq reset.

# Review round 7 (2026-10-14, Level 5.1): final independent pass over commits 6cfd8ba..e4c6ae5
No way past the authentication was found (path tricks, methods, encodings, query token off the root, subprotocol, wrong cookie, foreign Origin with a valid bearer), no leakage in the ML features (features at the validation cut equal the longer series on all 13 930 overlapping rows), and the round-6b fixes held. It found real defects:
| # | Sev | Finding | Disposition |
|---|---|---|---|
| 1 | High (function) | `ab_capture.py` could never exit 0: the reader started at the end of the file and skipped the EA header, so the identity gate always said "no header"; the mismatch test passed for that wrong reason; two unrelated streams (zero common ticks) exited 0 | FIXED: header read from offset 0 then the backlog dropped; "not comparable" (fewer than half common ticks) = exit 1 with no result; gaps/sessions/resets reported; 3 end-to-end tests (identical streams exit 0, wrong account exit 4, unrelated exit 1), mutation-checked |
| 2 | Medium | Privacy oracles: BLOCKED flips (`RISK_MIN_LOT_EXCEEDS_BUDGET`, `INSUFFICIENT_MARGIN`) reveal equity / free margin | FIXED structurally: in privacy mode the plan is sized on a hypothetical REFERENCE account (`risk.reference_equity`), the real equity is not used at all, so the public decision is byte-identical for every real account incl. a 52 USD account and one with no free margin (test over a 60-step path and 7 accounts); reveal mode (`XAU_REVEAL_SIZE=1`) sizes on the live account and says so (`sizing: LIVE_ACCOUNT`) |
| 3 | Medium | `account_ref` (32-bit hash) in `/api/health` is brute-forceable to the account number | FIXED: removed from the health detail; EA comment/file name documented as private (a 32-bit prefix: treat the CSV as private) |
| 4 | Medium | Heavy worker: a hung worker survived a timeout and blocked exit; a hard-killed gateway orphaned its worker; `heavy_warm` failure leaked it; teardown never closed the pool | FIXED: `_discard_pool()` kills the worker processes; a parent-pid watchdog ends an orphaned worker (verified live: 0 workers 4 s after killing the gateway; 5 pre-existing orphans removed by hand); pool discarded on warm-up failure and at shutdown; 3 new tests incl. a hard-killed parent, mutation-checked |
| 5 | Medium | The failed-token limiter was checked before the token: a web page navigating to `/?token=x` ten times locked the owner out for 60 s | FIXED: the right token always works; only wrong tokens are throttled; test |
| 6 | Low-Med | The session cookie never expired server-side; the access log records `/?token=`; cookies are not port-isolated | FIXED: signed expiring cookie (expiry inside the HMAC, dies with the token); `--no-access-log`; port isolation is a browser limit (documented) |
| 7 | Low-Med | The bind guard trusted `XAU_HOST` defaulting to loopback: `uvicorn --host 0.0.0.0` with `XAU_AUTH=off` ran open | FIXED: `XAU_AUTH=off` is honoured only with an explicit loopback `XAU_HOST` (set by `run_gateway.ps1`); anything else keeps authentication ON and the application refuses to start; tests |
| 8 | Low-Med | EA: `n < want` broke early when the terminal capped a call; a false `#gap` was written when the loop ended normally on the last page; restart gaps flagged only above 5 s; the Python model never exercised the terminal cap | FIXED: a short page (`n < InpPageSize`) is the only "nothing more" signal; `capped` flag; `InpPageSize >= 100` enforced (a page must exceed the most ticks that can share one millisecond); model tests the cap and resumption; restart threshold 2 s |
| 9 | Low | Drawings: poisoned storage (absurd values, bad/duplicate ids) could break the first render or collide ids; keydown ignored the focused element; equal-time trendlines were invisible | FIXED: strict validation (ranges, id format, uniqueness, cap), failing render contained, typing never hijacked, trend needs two different bars; 3 e2e tests |
| 10 | Low | ML: B1 used the magnitude, not the sign; walk-forward had no 24 h embargo; `holdout_loaded` was a literal | DISCLOSED in docs/research/ML_SHADOW_AMENDMENTS.md; the flag is now computed |
Not refuted: all authentication bypass attempts, WebSocket handshake attempts, Host/Origin parsing, ML leakage, stale serving, error back-off, reconnect/sequence handling, secrets in tracked files.
The fixes above were NOT re-reviewed by a third independent reviewer; each is covered by tests with mutation checks. Gate F6 stays PARTIAL.

# Review round 8 (2026-10-14, Level 5.1): verification pass over the round-7 fixes (commit 00e6d47)
No Critical or High finding. It confirmed: the signed cookie cannot be forged or extended, the token-first bootstrap cannot lock the owner out, privacy mode output is independent of the real equity / free margin, the offset estimator shows no false LOW under normal jitter, EA pagination matches the model line by line, and the ab_capture identity paths return 4/1.
| # | Sev | Finding | Disposition |
|---|---|---|---|
| 1 | Medium (verified live) | `session_ok` crashed (HTTP 500 + traceback) on a malformed cookie (`str.isdigit()` accepts U+00B2; `int()` of 5000 digits raises) | FIXED: ASCII digits, length <= 12, exceptions -> False; raw-byte test, mutation-checked |
| 2 | Medium | `/ws` bypassed the limiter; a short `XAU_API_TOKEN` was accepted | FIXED: wrong bearer on the handshake counts in the shared limiter; env token must be >= 24 characters (start-up refuses otherwise); tests |
| 3 | Low | `auth_enabled()` trusts the self-declared `XAU_HOST`: a stale `XAU_AUTH=off` + `XAU_HOST=127.0.0.1` with a manual `uvicorn --host 0.0.0.0` runs open | ACCEPTED, DOCUMENTED (THREAT_MODEL): the real bind is not observable from inside the app; always start with `run_gateway.ps1`, never export `XAU_AUTH=off` in a profile |
| 4 | Low | `--no-access-log` only in the script; `open_dashboard.ps1` puts the token on a command line briefly | FIXED for logs: a logging filter redacts `token=` in `uvicorn.access` however the server is started (test); the brief command-line exposure of the launcher is ACCEPTED (same-user trust domain) |
| 5 | Medium | ab_capture judged coverage against the SMALLER stream (an EA that died after 6 matching ticks exited 0); only the last header was checked; any exception exited 1 (same as "not comparable") | FIXED: coverage against the LARGER stream (+ per-side coverage in the result), EVERY header seen is identity-checked, exceptions exit 5; 3 tests, mutation-checked |
| 6 | Medium | EA used `StringFormat("%.*f")` (undocumented for MQL5) on the data line; never run live | FIXED: `DoubleToString` / `IntegerToString` only; recompiled (0 errors / 0 warnings). STILL not run in a terminal: LIVE_AB_NOT_TESTED |
| 7 | Low | EA: ignored `FileWriteString` failure while the cursor advanced; `InpOverlapMs` unchecked; `#gap page_cap` read as a loss | FIXED: a failed write does not advance the cursor (counted); input validation; the reader labels `page_cap` as `EA_PAGE_CAP_RESUMING` (informational). Restart duplicates/gap remain by design and are reported |
| 8 | Medium | A draw-time error wiped ALL drawings (`items = []` then the next save overwrote the store) | FIXED: per-item containment, nothing removed from memory or storage, a visible "N could not be drawn (kept in storage)" notice, backup key `.bak` when load drops invalid items, integer-time validation, 500-item cap in `add()`; 3 e2e tests, mutation-checked |
| 9 | Low | other drawing losses: two tabs last-writer-wins; ids reach 10 digits after 1e9 adds | ACCEPTED, DOCUMENTED (client-side drawings; KNOWN_LIMITATIONS) |
| 10 | Low | `minmax(0,1fr)` missing in the narrow grid | FIXED |
| 11 | Low | narrow layout reorders visually only (DOM / tab order unchanged: chart before decision) | ACCEPTED, DOCUMENTED (WCAG 1.3.2 / 2.4.3 gap; fixing it needs a DOM reorder with desktop grid placement) |
| 12 | Low | ctypes handles untyped (64-bit truncation), `WAIT_FAILED` could end a healthy worker, private `_processes` only | FIXED: typed handles, `WAIT_FAILED` counts as alive, public `kill_workers()` first with the private table as fallback |
Gate F6: PARTIAL still. Every round (5, 6, 6b, 7, 8) found real defects; the round-8 fixes themselves have no further independent pass, only their tests with mutation checks.
