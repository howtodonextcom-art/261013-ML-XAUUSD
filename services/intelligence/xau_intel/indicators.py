"""Indicators on CLOSED bars, following MetaTrader 5's built-in definitions. Pure numpy, causal (value at i uses bars <= i only).

MT5 definitions implemented (feature_version `ind-1`):
- EMA(n): ema[0] = price[0]; ema[i] = ema[i-1] + a*(price[i]-ema[i-1]), a = 2/(n+1). Valid from index n-1 (earlier values exist but are
  seed-dominated and are reported as NaN: INSUFFICIENT_HISTORY).
- RSI(n): Wilder smoothing; first averages are the simple mean of the first n gains/losses; RSI = 100 - 100/(1+RS). Flat market
  (no gains and no losses) -> 50 (documented choice).
- ATR(n): simple moving average of True Range over TR[1..n] (MT5's iATR is an SMA, not Wilder's RMA); TR[0] is excluded.
- MACD(f,s,g): EMA(f) - EMA(s); the signal line is a SIMPLE moving average of the MACD line (as in MT5's iMACD); hist = macd - signal.
atr_ratio50 = ATR14 / (mean of ATR14 over the 50 bars ending 14 bars earlier): a baseline that does not contain the move being measured.
Whether these equal MT5's own numbers is NOT verified here (needs an MQL5 script dumping iMA/iRSI/iATR/iMACD; see mt5/scripts/DumpIndicators.mq5).
"""
from __future__ import annotations

import numpy as np

FEATURE_VERSION = "ind-1"
NaN = np.nan


def ema(x, n: int):
    x = np.asarray(x, dtype=float)
    out = np.full(len(x), NaN)
    if len(x) == 0:
        return out
    a = 2.0 / (n + 1)
    e = x[0]
    vals = np.empty(len(x))
    vals[0] = e
    for i in range(1, len(x)):
        e = e + a * (x[i] - e)
        vals[i] = e
    out[n - 1:] = vals[n - 1:]
    return out


def sma(x, n: int):
    """Simple moving average; NaN whenever the window contains a NaN (missing history is never treated as zero)."""
    x = np.asarray(x, dtype=float)
    out = np.full(len(x), NaN)
    if len(x) < n:
        return out
    isn = np.isnan(x)
    c = np.cumsum(np.insert(np.where(isn, 0.0, x), 0, 0.0))
    cn = np.cumsum(np.insert(isn.astype(np.int64), 0, 0))
    s = (c[n:] - c[:-n]) / n
    s[(cn[n:] - cn[:-n]) > 0] = NaN
    out[n - 1:] = s
    return out


def rsi(close, n: int = 14):
    c = np.asarray(close, dtype=float)
    out = np.full(len(c), NaN)
    if len(c) <= n:
        return out
    d = np.diff(c)
    gain, loss = np.where(d > 0, d, 0.0), np.where(d < 0, -d, 0.0)
    ag, al = gain[:n].mean(), loss[:n].mean()

    def val(g, l):
        if g == 0 and l == 0:
            return 50.0
        if l == 0:
            return 100.0
        return 100.0 - 100.0 / (1.0 + g / l)

    out[n] = val(ag, al)
    for i in range(n, len(d)):
        ag = (ag * (n - 1) + gain[i]) / n
        al = (al * (n - 1) + loss[i]) / n
        out[i + 1] = val(ag, al)
    return out


def true_range(h, l, c):
    h, l, c = (np.asarray(v, dtype=float) for v in (h, l, c))
    tr = np.empty(len(c))
    if len(c) == 0:
        return tr
    tr[0] = h[0] - l[0]
    pc = c[:-1]
    tr[1:] = np.maximum.reduce([h[1:] - l[1:], np.abs(h[1:] - pc), np.abs(l[1:] - pc)])
    return tr


def atr(h, l, c, n: int = 14):
    tr = true_range(h, l, c)
    out = np.full(len(tr), NaN)
    if len(tr) <= n:
        return out
    s = sma(tr[1:], n)           # SMA over TR[1..]; index shift by one
    out[1:] = s
    return out


def macd(close, fast: int = 12, slow: int = 26, signal: int = 9):
    c = np.asarray(close, dtype=float)
    line = ema(c, fast) - ema(c, slow)
    sig = sma(line, signal)
    return line, sig, line - sig


# ---------------------------------------------------------------- features
def bars_since_sign_change(v):
    """For each i: bars since sign(v) last changed (0 on the bar of the change); NaN while undefined."""
    v = np.asarray(v, dtype=float)
    out = np.full(len(v), NaN)
    last_sign, age = 0, 0
    for i, x in enumerate(v):
        if np.isnan(x):
            continue
        s = 1 if x > 0 else -1 if x < 0 else last_sign
        if last_sign == 0 or s != last_sign:
            age, last_sign = 0, s
        else:
            age += 1
        out[i] = age
    return out


def rolling_percentile(x, window: int):
    """Causal percentile rank of x[i] within x[i-window+1..i] (0..1). NaN until the window is full."""
    x = np.asarray(x, dtype=float)
    out = np.full(len(x), NaN)
    for i in range(window - 1, len(x)):
        w = x[i - window + 1:i + 1]
        if np.isnan(w).any():
            continue
        out[i] = (w < x[i]).sum() / (window - 1) if window > 1 else 0.0
    return out


def compute_features(o, h, l, c, spread_price=None, slope_bars: int = 10) -> dict:
    """All indicator series and derived features for closed bars. Missing history -> NaN (callers treat as INSUFFICIENT_HISTORY)."""
    c = np.asarray(c, dtype=float)
    e = {n: ema(c, n) for n in (20, 50, 100, 200)}
    a = atr(h, l, c, 14)
    r = rsi(c, 14)
    ml, ms, mh = macd(c)
    with np.errstate(divide="ignore", invalid="ignore"):
        slope = {n: (e[n] - np.roll(e[n], slope_bars)) / a for n in (20, 50, 100, 200)}
        for n in slope:
            slope[n][:slope_bars] = NaN
        dist = {n: (c - e[n]) / a for n in (20, 50, 100, 200)}
        stack = np.vstack([e[20], e[50], e[100], e[200]])
        compression = (np.max(stack, axis=0) - np.min(stack, axis=0)) / a
        base = np.roll(sma(a, 50), 14)       # baseline = mean ATR of the 50 bars that END 14 bars ago (no overlap with the ATR window itself)
        base[:14] = NaN
        atr_ratio = a / base
        spread_atr = (np.asarray(spread_price, dtype=float) / a) if spread_price is not None else np.full(len(c), NaN)
    bull = (e[20] > e[50]) & (e[50] > e[100]) & (e[100] > e[200])
    bear = (e[20] < e[50]) & (e[50] < e[100]) & (e[100] < e[200])
    valid = ~np.isnan(stack).any(axis=0)
    alignment = np.where(~valid, "INSUFFICIENT_HISTORY", np.where(bull, "BULL", np.where(bear, "BEAR", "MIXED")))
    rsi_regime = np.where(np.isnan(r), "INSUFFICIENT_HISTORY", np.where(r >= 55, "BULL", np.where(r <= 45, "BEAR", "NEUTRAL")))
    return {"ema": e, "ema_slope_atr": slope, "ema_dist_atr": dist, "ema_compression_atr": compression, "ema_alignment": alignment,
            "rsi": r, "rsi_regime": rsi_regime, "rsi_momentum3": r - np.roll(r, 3),
            "macd": ml, "macd_signal": ms, "macd_hist": mh, "macd_hist_slope": np.diff(mh, prepend=NaN),
            "macd_cross_age": bars_since_sign_change(mh), "atr": a, "atr_ratio50": atr_ratio,
            "atr_pct200": rolling_percentile(a, 200), "spread_atr": spread_atr, "feature_version": FEATURE_VERSION}
