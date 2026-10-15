# Scalping C2 / C3: amendments to the pre-registration (Level 6.5)

The registration (`SCALPING_C2_C3_PREREGISTRATION.md`, commit 6f72dfe, instant 1792022334) is frozen and is not edited. This file records what an independent pre-code review found missing or ambiguous. It is committed BEFORE any C2 event is logged live, and before any C2 outcome exists. Where this file and the registration differ, this file wins for the stated point only. No threshold of the registration is changed here; numbers that were missing are fixed now, from the V2 definitions, without looking at any outcome.

## Clock
The C2 evaluation clock is `C2_REGISTRATION_UTC = 1792022334` (the registration commit), not the V2 constant. The 30 day / 100 trigger gate counts from it. Events logged before this amendment is committed do not exist (no live C2 logging was started).

## A1 Evaluator
C2 is evaluated by `evaluate_v2` reused with its own constants: stage `M1_TRIGGERED`, kind `M1_*` (C2 events use the same names so `triggers_of` accepts them), `clock = C2_REGISTRATION_UTC`, and no `v1_target` (TP = 2.0 x stop, as registered). Extra outputs (alignment split, funnel, coverage vs V1 and V2) are computed by a C2 report from the same log. The evaluator and V2's amendments A1-A15 are not modified.

## A2 Gate and verdict states
- Gate (one definition): at least 100 TRIGGERED events AND at least 30 calendar days from the clock. Then the evidence test of the registration needs at least 100 FILLED trades; if triggers >= 100 but filled < 100 the status stays INSUFFICIENT_EVIDENCE.
- Counts-only check, no outcome: the share of triggers that are BLOCKED is reported; a BLOCKED rate above 60% is flagged as "most triggers cannot be traded at the broker stops level", not as a verdict.
- INSUFFICIENT_EVIDENCE: the gate is not reached. NO_EVIDENCE_OF_EDGE: the gate is reached and any evidence condition of the registration fails. EVIDENCE: all hold.
- One evaluation only: the first time the gate is met (no optional stopping, no peeking before). Later evaluations are labelled follow-ups and cannot change the first verdict.
- Multiple testing: three cost scenarios, the B2/B3 comparisons and the quarter test are all part of the single registered verdict; no extra subset or parameter is searched. B3 (aligned vs countertrend) is informational.

## A3 Duplicates, clusters and trigger kind
- Event id: `scalp-c2-{DIR}-{kind}-{bar_time}-{zone center}`; the log is append-only and deduplicated by id across restarts (ids are persisted before use).
- One trigger per direction per zone episode (same as V2); a new trigger in the same direction is ignored while a trigger window or a hypothetical position is open.
- When several triggers fire on the same bar the kind is the first of the fixed priority order rejection, engulfing, momentum shift, structure break (`flags[0]`); all flags are listed.
- M1 bar to M5 structure: the M5 structure at an M1 bar is the one of the last M5 bar CLOSED at or before that M1 bar's close.

## A4 Registered rules with numbers that were missing
- MISSED: a closed M1 bar closes more than 0.5 ATR(M5) beyond the trigger close in the trade direction.
- INVALIDATED: a closed M1 bar closes beyond `zone.low - 0.25 ATR(M5)` (SELL mirrored), or the M5 structure flips to the OPPOSITE side. A RANGE / UNKNOWN M5 structure alone does not invalidate a trigger already confirmed; it only means no new WATCH or trigger (the "M5 side holds" test is applied at the trigger bar's close only).
- TRIGGERED vs ENTRY_WINDOW: TRIGGERED is the single trigger bar; ENTRY_WINDOW covers the following 5 closed M1 bars (5 M1 minutes). Timeout: 288 minutes of timeline (one M1 bar = one minute).
- WATCH is a state, not an event; WATCH transitions are not logged (only TRIGGERED, MISSED, INVALIDATED, EXPIRED and BLOCKED are).
- ATR(M5) (14) is used for the band, MISSED and invalidation; ATR(M1) (14) for the momentum bar range; ATR(M15) is a recorded context.
- Zone tie-break: the nearest zone by distance of `zone.high` to price; equal distance takes the higher confirmation count, then the lower index.
- Week = ISO week in UTC; quarter = four equal chronological blocks of the forward period.
- Zig-zag window: the last 600 M1 bars; a test requires live (window) and batch computation to give the same events over the covered range.
- H4 information is preserved: the event stores the H1 value, the H4 value and the H4-conflict flag, not only the label.

## A5 Hypothesis clause
The countertrend sentence of H-C2 is informational only (B3) and cannot rescue or sink the verdict. The registered hypothesis is the pooled C2 expectancy against the null.

## A6 Card-only M1 momentum
The card shows an M1 momentum word (UP / DOWN / NEUTRAL / UNKNOWN) from the last closed M1 bars. It is display only: it is not part of any C2 rule, trigger, event or evaluation.

## A7 Wording corrections to the audit
- `holdout_bars_used_in_computation: false` is a literal in the script, not a computed measurement; the cut at `val_end` is what enforces it.
- The mirrored-price run proves the V1 setup state counts are symmetric on that sample (20 of 20 equal). It is strong evidence against a BUY/SELL coding asymmetry, not a proof for all inputs.
- "V1 is blind" means V1 has no rule for those cases by design; it does not mean any of those cases was profitable.

## A8 Claims
A higher trigger count, coverage or a visible marker is not evidence of profit. C2 stays SHADOW; live C2 BUY/SELL is NOT OBSERVED until it occurs.

## C3
Unchanged: proposal only, not built.

## A9 Implementation clarifications (written after the independent code review, before any C2 event was logged; `data/scalp/` did not exist yet)
- Window by clock: the entry window is counted in elapsed minutes from the trigger's `known_at` (not in bars), so a feed gap cannot stretch it.
- Zone choice follows A4 exactly (nearest by `|zone.high - price|`, then more touches, then lower centre).
- Card: a plan and a BUY/SELL/BLOCKED word are shown only in stage ENTRY_WINDOW; while price is outside the entry band after a trigger the card says so and shows no entry.
- Isolation: C2 runs in its own worker pool (`c2pool`) and thread with its own 10 s deadline; V2 keeps `v2pool`. A slow or failing C2 cannot cost V2 its result.
- Prefix invariance fix: the engine no longer returns "no data" when H1/H4 history is short (that depended on how much later history existed); H1/H4 are labels and may be UNKNOWN.
- Known limit, not changed: a new trigger in the same zone can fire again after a terminal state (V2 behaves the same); the raw trigger count that feeds the 100-trigger gate can therefore contain clusters. The evaluator's one-open-position rule limits trades, and the cluster share is reported with the funnel.
- Chart markers can include events re-derived from the 600-bar window at startup; only the log (events known after the registration) is evidence.
