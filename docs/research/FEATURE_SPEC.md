# FEATURE SPEC (P3: multi-timeframe market intelligence)

Package `services/intelligence/xau_intel` (no dependency on the gateway, MT5 or the network). Input is a point-in-time snapshot of CLOSED bars; output is context only (regime, features, structure). **It emits no BUY/SELL/WAIT**: decisions belong to P4/P5.
Versions: indicators `ind-1`, structure `struct-1`, regime `regime-1`.

## Point-in-time snapshot (`build_snapshot`)
For evaluation time t (server epoch s) a timeframe contributes only bars with `open + tf_seconds <= t`. The forming bar is never included; an H1 bar enters only after it closes (tests: `test_htf_bar_enters_snapshot_only_after_it_closes...`). Arrays are read-only. Same input, same output (`json.dumps` equality test), and physically deleting future bars changes nothing (`test_mtf_analysis_at_time_t_is_unaffected_by_future_bars`).
Analysis window: the last 5 000 closed bars per timeframe (EMA200's memory of older bars is below 1e-20). Cost on the real store: all 5 timeframes (93 381 closed bars in total, 5 000-bar window each) in 0.19 s.

## Indicators (MT5 definitions; `indicators.py`)
| Feature | Definition |
|---|---|
| EMA 20/50/100/200 | seeded with the first price, alpha = 2/(n+1); NaN before index n-1 (INSUFFICIENT_HISTORY) |
| RSI 14 | Wilder smoothing, first averages = simple mean of the first 14 changes; flat market = 50. Matches the published Wilder example (70.46, 66.25, 66.48, 69.35, 66.29, 57.92) |
| ATR 14 | simple moving average of True Range over TR[1..] (MT5's iATR is an SMA) |
| MACD 12/26/9 | EMA12-EMA26; signal = SMA(9) of the MACD line (MT5's iMACD); hist = macd - signal |
| ema_slope_atr(n) | (EMA_n[i] - EMA_n[i-10]) / ATR |
| ema_dist_atr(n) | (close - EMA_n) / ATR |
| ema_compression_atr | (max - min of EMA20/50/100/200) / ATR |
| ema_alignment | BULL if 20>50>100>200, BEAR if reversed, MIXED otherwise, INSUFFICIENT_HISTORY without EMA200 |
| rsi_regime / momentum | BULL >= 55, BEAR <= 45, NEUTRAL; momentum = RSI[i] - RSI[i-3] |
| macd_hist_slope, macd_cross_age | hist[i]-hist[i-1]; bars since the sign of hist last changed |
| atr_ratio50 | ATR14 / mean ATR14 of the 50 bars ending 14 bars earlier (a baseline that does not contain the move being measured) |
| atr_pct200 | causal percentile rank of ATR within the last 200 bars |
| spread_atr | spread price / ATR |
**MT5 parity is NOT VERIFIED.** The definitions follow MetaTrader's documented behaviour and the published Wilder RSI example, but nothing has been compared with MT5's own buffers. `mt5/scripts/DumpIndicators.mq5` (compiles with 0 errors, 0 warnings, read-only) plus `benchmarks/mt5_indicator_parity.py` do it once the script is run on a chart; until then the result is NOT TESTED. The comparator's verdict uses only the LAST 1000 bars of the (>= 3000-bar) dump: MT5 computes over the whole history while Python seeds from the slice, so EMA/RSI differ early by design (reported as informational; the test shows an early EMA200 difference above 1e-3 that is irrelevant late). It is tested to pass when the reference was computed on a longer history, and to fail on a 0.01 difference in the late zone. Its first run on real MT5 numbers has not happened.
EMA, RSI and MACD are all functions of the same close series: they are not three independent pieces of evidence (the decision layer must not count them as such).

## Causal market structure (`structure.py`)
Detector chosen by the fallback clause of a self-attested pre-registered rule (docs/research/SWING_DETECTION_DECISION.md): **ATR zig-zag, k = 2.0**; fractal(3) is kept for comparison. Both passed the hard gates on real bars (no look-ahead, no repaint); **both failed the density criterion S1** (zig-zag 11.3-11.5 vs the 4-10 band). The pre-registration has no external timestamp (see that file).
Every swing: `formed_at` (extreme bar open), `known_at` (close of the confirming bar, always later), `known_idx`, `source_timeframe`. Labels HH/HL/LH/LL/EH/EL compare with the previous swing of the same kind; trend UP = latest HH + HL, DOWN = LH + LL, RANGE otherwise, UNKNOWN before two pairs exist.
Only the latest confirmed swing high/low is a breakable level; an older unbroken level replaced by a newer swing never fires.
Events (`BOS_UP/DOWN`, `CHOCH_UP/DOWN`, `BREAKOUT_UP/DOWN`): a bar CLOSE beyond the latest swing that was confirmed on an earlier bar (a wick is not a break); each level breaks once. BOS = with the prevailing trend, CHOCH = first break against it, BREAKOUT when the trend is RANGE/UNKNOWN. Fields: `event_time, formed_at, known_at, evaluated_at, source_timeframe, feature_version` (+ level times). `analyse_tf` reports events by `bar_open_time` (absolute); `bar_idx_in_window` is relative to the analysed window and must not be used to join analyses.
Support/resistance: clusters of confirmed swing prices within 0.5 ATR (touch count); uses confirmed swings only.
Not implemented: false breakout and liquidity-sweep candidates (listed in the prompt) are NOT IMPLEMENTED.

## Regime (`classify_regime`)
Order of rules: UNKNOWN (fewer than 220 bars / no EMA200 / NaN ATR) -> VOLATILITY_EXPANSION (atr_ratio50 >= 1.5 and atr_pct200 >= 0.8) -> COMPRESSION (EMA spread < 0.5 ATR and atr_ratio50 <= 0.8) -> TRENDING_UP/DOWN (alignment, EMA50 slope sign and structure agree, no CHOCH against it in the last 20 bars) -> SIDEWAYS (MIXED alignment and |EMA50 slope| < 0.15 ATR) -> TRANSITION. High ATR is reported as volatility, never as a direction; RSI and MACD do not enter the regime.
Thresholds are initial design parameters derived from the feature definitions. **They have not been validated or tuned against outcomes.** The regime is descriptive: no claim that a regime predicts anything.

## Evidence (tests: `tests/unit/test_intel.py`, 44 pass)
Hand-checked indicator values; indicators causal (truncated series equals full-series prefix at 3 cut points); swings known-by-c equal the full-series swings restricted to `known_idx <= c` at every 7th index for 3 seeds x 2 detectors; no repaint; the incremental event engine equals a naive O(n^2) reference on 12 random series; BOS/CHOCH scenario; wick is not a break; regime classification on synthetic trend / mirror / short history / calm-then-spike; analysis cost bounded on 60 000 bars; NaN-correct SMA (MACD signal/hist/cross-age and atr_ratio50 are NaN until truly valid); a hand-computed zig-zag case. The oracle test shares `zigzag_swings` with the implementation, so it proves the incremental engine equals the naive formulation, not that the swings are right (that is what the hand-computed case and the causality tests cover).
