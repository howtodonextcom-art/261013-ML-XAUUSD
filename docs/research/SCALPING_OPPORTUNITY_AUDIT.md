# Scalping opportunity audit (Level 6.5, P0)

Written 2026-10-15 at HEAD d6934e5. Method: code reading plus `benchmarks/scalping_audit.py` -> `results/v1/scalping_audit.json`. **Counts and classifications only: no price outcome, P/L, R or expectancy is computed anywhere in this audit.** Historical numbers use development + validation bars closed at `val_end` (2026-08-02); the sealed holdout contributes nothing (`holdout_bars_used_in_computation: false`). All stored M1 history (from 2026-08-04) lies inside the sealed period, so no M1 number is used here except the V2 forward log (events after the V2 registration, outside the sealed period).

## 1. Where the higher timeframes act as hard gates (code)
| Layer | Gate | Code |
|---|---|---|
| V1 setup | a setup may start only when the H1 direction equals the setup side AND H4 does not oppose; an open setup in its early states is ended (`INVALIDATED`) when the H1 context stops matching | `services/intelligence/xau_intel/setups/machine.py:93-149` (`ctx_ok`, `conflict`), `run_setups` lines 238-249 (`ctx == "UP"` for BUY, `== "DOWN"` for SELL, one shared `conflict`), `current_status` lines 254-276 |
| V1 decision | no eligible setup -> WAIT (`NO_DIRECTION`, `NO_VALID_IMPULSE`, `SIGNAL_CONFLICT`); eligible -> risk-1 / gate-1 | `services/intelligence/xau_intel/decision/decide.py` (`_decide`, `WAIT_NEXT`) |
| V2 shadow | `ctx_ok = (H1 direction == side) & ~H4 conflict` for every stage; no context -> `NO_CONTEXT`, nothing else is evaluated | `services/intelligence/xau_intel/m1/entry_v2.py:84,132,198,234` |
| Where M15 / M5 / M1 take part | V1: M15 only (impulse, pullback, zone, confirmation bar, entry window); M5 only as the spread/price source of the decision; M1 not at all. V2: M15 zone, M5 `pa-1` confirmation (within 6 bars), M1 closed trigger. Neither uses an M5 structure direction nor a countertrend side | `setups/machine.py`, `m1/entry_v2.py` |

## 2. BUY and SELL are processed symmetrically (executed proof)
V1 was run on the real dev+val prices and on the price-mirrored series (open -> -open, high -> -low, low -> -high, close -> -close). BUY on one must equal SELL on the other, state by state: **20 of 20 state counts equal** (`v1_buy_sell_symmetry_on_mirrored_prices.all_equal: true`). The asymmetry seen in the funnel (BUY 10 vs SELL 21 risk-passed setups) comes from the price path of the sample (a falling market), not from the code. Unit tests: `tests/unit/test_setups.py`, `tests/unit/test_m1_entry_v2.py::test_sell_is_the_exact_mirror_of_buy`.

## 3. What V1 and V2 skip by design (M5 structure view, 55,158 M5 bars of dev+val)
M5 structure (zig-zag k = 2.5) is UP or DOWN on 34,235 bars (62.1%); the rest is RANGE / UNKNOWN. On those 34,235 bars:
| Relation to H1 / H4 | Bars | Share |
|---|---|---|
| H1 shows NO direction | 17,023 | 49.7% |
| H1 direction UNKNOWN (not enough data) | 1,491 | 4.4% |
| COUNTERTREND (H1 direction opposite to the M5 side) | 6,190 | 18.1% |
| ALIGNED with H1 (of which with an H4 conflict: 676) | 9,531 | 27.8% |
| V1 had an active setup on the SAME side | 2,581 | **7.5%** |
M5 `pa-1` pattern bars (pin / engulfing / strong close) in the M5 structure direction: 6,866 (BUY side 3,523, SELL side 3,343); **7.6% of them coincide with an active V1 setup on that side; 49.1% occur while H1 shows no direction, 17.9% countertrend to H1, 2.4% with an H4 conflict.** So V1 is blind to more than nine tenths of the M5-level price-action events, mostly because the H1 hard gate has no direction (about half of the time) or opposes the M5 side. That is exactly what the design says (V1 is a with-the-H1-trend pullback strategy), not an implementation error.

## 4. What V2 sees that V1 does not (forward data only)
17 V2 triggers were logged live since the registration (all with an H1 direction and no H4 conflict, because V2 shares the V1 context gate): **15 had no V1 setup on the same side** at that moment, 2 had one (`forward_v2_vs_v1`). V2 therefore already catches M1 timing events V1 has no setup for, but it cannot see anything the H1/H4 gate excludes (the 49.7% + 18.1% above).

## 5. Why WAIT is frequent: design, not a bug
Three independent causes, none of them a defect: (1) the frozen policy is selective (docs/research/V1_SIGNAL_FORENSICS.md: about 31 setups passed the risk gate at their first eligible bar in 6.5 months); (2) the H1 hard gate removes half of the M5-level opportunities before any setup is formed; (3) risk-1 blocks about half of the eligible setups (6.00 USD broker stops level, minimum net R:R). One implementation defect was found and fixed earlier (a misleading `AWAITING_PULLBACK` label, Level 6.2). **No strategy exists for M5/M1 opportunities against or without the H1 direction: that is the gap.**

## 6. Dataset isolation consequence (decided before any study)
M1 development data does not exist (all M1 history is inside the holdout period). Any C2 evidence must therefore be forward-only shadow (INSUFFICIENT_EVIDENCE until the sample exists). M5 data exists for dev+val, but a study of M5-level entries would need its own registration with execution assumptions an M5 bar cannot support (spread, intrabar order of SL/TP): not started.
