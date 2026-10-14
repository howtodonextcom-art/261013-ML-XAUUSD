# Product fit audit (Level 6.4, 2026-10-15)

Evidence-based and short. Sources: `docs/product/PRODUCT_VISION_AND_REQUIREMENTS.md`, `docs/product/PRODUCT_ACCEPTANCE_MATRIX.md`, the running gateway, the Chrome MCP sessions of Levels 5.x to 6.4, `docs/research/*`. Classification unchanged: **RESEARCH BETA**, READ_ONLY + SHADOW + PAPER_SIMULATION.

## 1. Personas
| Persona | Jobs to be done | Decision they make | Must be on the first screen | Time to understand (target / measured) | Misreading risk | Gaps found |
|---|---|---|---|---|---|---|
| **Primary: discretionary XAU/USD trader** | see what the market does, know whether the frozen research rules currently justify a BUY/SELL observation, know why not and what is missing, see what happened earlier | trade or not by his own judgement; the terminal never trades | market bias, V1 action, reason, next required event, eligibility, signal age/expiry, data freshness | target under 10 s; measured by inspection only (no user study) | a research BUY/SELL read as advice or as a proven edge; a past marker read as current; a shadow arrow read as V1 | the 13-px dense right column (fixed in 6.4), no alert for a new decision (added in 6.4: toast, opt-in sound and desktop notification), M1 price-action state scattered (regrouped) |
| **Secondary: strategy researcher / quant** | audit funnel, event history, provenance, pre-registered studies, evidence status | decide whether a hypothesis deserves a study | research status, funnel, setup event inspector, provenance, forward-log status | minutes; documents exist (V1_SIGNAL_FORENSICS, SETUP_EVENT_FORENSICS, RESEARCH_STATUS) | confusing display counts with performance; confusing live-engine and replay events | historical setup events are a replay, not a live recording (disclosed with provenance); V1 live decisions are only recorded since 2026-10-14 |
| **Developer / QA** | prove nothing regressed, reproduce, roll back | accept or reject a change | tests, evidence files, amendments, review rounds | n/a | trusting fixtures as live evidence | live BUY/SELL NOT OBSERVED; MT5 live checks NOT TESTED |
| **Who must NOT use it as a proven signal source** | anyone expecting profit | | | | | V1 backtest INSUFFICIENT_EVIDENCE (7 validation trades), ML NO_EVIDENCE_OF_PREDICTIVE_SKILL (AUC 0.499), V2 collecting: no demonstrated edge; beginners, anyone sizing real money from a BUY/SELL marker, anyone needing an execution tool |

## 2. Product-market fit (honest)
Fit exists for a narrow job: an explainable, read-only research dashboard whose every label is traceable to backend data. It does NOT yet have evidence that the decisions are worth acting on (research validation: INSUFFICIENT / NO EVIDENCE), live BUY/SELL has not been observed, and no user has been interviewed. Fit for trading profit: NOT ESTABLISHED.

## 3. Original goals (the ten questions of the Level 6.4 mission)
| # | Question | Status |
|---|---|---|
| 1 | market UP/DOWN/SIDEWAYS | PASS: market bias BULLISH / BEARISH / NEUTRAL / UNKNOWN from backend H1/H4 direction (display of backend fields, predicts nothing) |
| 2 | M1 momentum | PARTIAL: only the V2 shadow's closed-bar flags and forming-bar observation; no validated M1 momentum indicator; clearly labelled shadow |
| 3 | H1/H4 vs M1 | PASS (display): "M1 shadow side vs H1/H4: AGREES / CONFLICT" |
| 4 | price action / setup | PASS: setup lifecycle F/C/X/I/M with history and provenance |
| 5 | BUY/SELL/WAIT/BLOCKED | PASS (software); live BUY/SELL NOT OBSERVED |
| 6 | when and on what evidence | PASS: decision events with published_at, known_at, setup id, reason; tooltips |
| 7 | missing / invalidated conditions | PASS: setup progress, next required, terminal states |
| 8 | Entry/SL/TP/R:R | PASS (paper plan on a reference account, privacy mode) |
| 9 | setup history, expiry, missed | PASS (replay history + inspector) with limits in KNOWN_LIMITATIONS |
| 10 | out-of-sample evidence after costs | NOT ESTABLISHED: INSUFFICIENT_EVIDENCE / NO_EVIDENCE_OF_PREDICTIVE_SKILL |

## 4. Layout options and acceptance criteria (fixed BEFORE the redesign was coded)
Criteria: (C1) the V1 action, market bias, reason and next event readable within 3 s at 1440x900 without scrolling; (C2) chart at least 60% of the width and the full viewport height; (C3) body text at least 14 px on desktop, no important text clipped, contrast at least 4.5:1 for text; (C4) no state conveyed by colour alone; (C5) works at 1152x720 and 390x844 without horizontal overflow; (C6) every existing control still works; (C7) no new work in the tick path (render p99 not worse than the baseline +20%).
| Option | Description | C1 | C2 | C5 | Cost/risk |
|---|---|---|---|---|---|
| A | keep the right column as is, only enlarge fonts | partial | no (column grows) | ok | low, but density problem stays |
| **B (chosen)** | chart-first; one right "hero rail" (bias, action, chips, progress, next event, plan); M1 price-action card; everything else inside one collapsible "More"; Advanced diagnostics collapsed; sidebar can be hidden; top bar shows analysis time | yes | yes | ok | moderate: tests that touch the collapsed panels must open it |
| C | bottom dock for all panels, chart full width on top | yes | yes | needs a rewrite of the mobile layout | high |
Decision: B. It meets C1 to C6 with the smallest change and keeps the tests' structure.

## 5. History correctness (Level 6.3 items audited at HEAD 6ca6619, which is pushed to origin/main)
| Item | State at HEAD |
|---|---|
| emission order of events in one second | FIXED (`seq`); test `test_a_lifecycle_inside_one_second_keeps_its_emission_order_and_bounds_are_inclusive` (mutation-checked) |
| a failed replay is not cached as success | FIXED (server backoff 60 s, client not-covered + retry); tests |
| live/replay overlap stability | FIXED by design: replay is the canonical history, live only beyond it; test that the past does not change when the window slides |
| pagination and cursor | tested (every event exactly once, same-second extension, inclusive bounds, limit cap); the limit is a soft cap by a few events |
| cache invalidation | store signature + newest bar per timeframe; tested with a fake worker |
| marker-to-candle mapping | tested in real Chrome for M1 to H4, missing bar, outside range |
Residual: quarantine changes are not in the cache signature; the replay is not a live recording.
