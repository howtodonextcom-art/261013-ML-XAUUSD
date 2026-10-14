"""P7 point-in-time features (docs/research/ML_SHADOW_PREREGISTRATION.md). Each row i uses closed M15 bars <= i and higher-timeframe bars closed at
or before bar i's close; the label (future) is built separately and never enters a feature."""
from __future__ import annotations

import numpy as np

from ..backtest.engine import setup_run
from ..indicators import atr as atr_fn, ema, macd, rsi

FEATURE_NAMES = ("rsi14", "ema20_dist_atr", "ema20_50_atr", "macd_hist_atr", "atr_ratio", "ret1_atr", "ret4_atr", "ret16_atr", "dist_swing_high_atr",
                 "dist_swing_low_atr", "h1_dir", "h4_dir", "hour_sin", "hour_cos")
ML_VERSION = "ml-1"
HORIZON = 4
M15 = 900
_DIR = {"UP": 1.0, "DOWN": -1.0, "NONE": 0.0}


def build_features(bars: dict, sr: dict | None = None) -> dict:
    """Returns {X (n, F) with NaN where undefined, t (bar open time), close, names}. `sr` may be passed to avoid recomputing the setup run."""
    sr = sr or setup_run(bars)
    o, h, l, c, t = sr["o"], sr["h"], sr["l"], sr["c"], sr["t"]
    n = len(c)
    a14 = atr_fn(h, l, c, 14)
    a50 = atr_fn(h, l, c, 50)
    r14 = rsi(c, 14)
    e20, e50 = ema(c, 20), ema(c, 50)
    _, _, hist = macd(c)
    X = np.full((n, len(FEATURE_NAMES)), np.nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        X[:, 0] = r14
        X[:, 1] = (c - e20) / a14
        X[:, 2] = (e20 - e50) / a14
        X[:, 3] = hist / a14
        X[:, 4] = a14 / a50
        for col, k in ((5, 1), (6, 4), (7, 16)):
            r = np.full(n, np.nan)
            r[k:] = (c[k:] - c[:-k]) / a14[k:]
            X[:, col] = r
    # distance to the last CONFIRMED swing high / low (known_idx <= i), in ATR
    sw = sorted((s for s in sr["swings"] if not s.window_start_artifact), key=lambda s: s.known_idx)
    last_h = last_l = np.nan
    si = 0
    for i in range(n):
        while si < len(sw) and sw[si].known_idx <= i:
            if sw[si].kind == "H":
                last_h = sw[si].price
            else:
                last_l = sw[si].price
            si += 1
        if a14[i] > 0 and not np.isnan(a14[i]):
            X[i, 8] = (last_h - c[i]) / a14[i] if not np.isnan(last_h) else np.nan
            X[i, 9] = (c[i] - last_l) / a14[i] if not np.isnan(last_l) else np.nan
    X[:, 10] = [_DIR.get(str(v), np.nan) for v in sr["ctx"]]           # "UNKNOWN" -> NaN: the sample is dropped
    X[:, 11] = [_DIR.get(str(v), np.nan) for v in sr["ctx4"]]
    hr = (t % 86400) / 3600.0
    X[:, 12] = np.sin(2 * np.pi * hr / 24.0)
    X[:, 13] = np.cos(2 * np.pi * hr / 24.0)
    return {"X": X, "t": t.astype(np.int64), "close": c, "names": FEATURE_NAMES, "version": ML_VERSION}


def build_labels(t: np.ndarray, close: np.ndarray, horizon: int = HORIZON, bar_s: int = M15) -> np.ndarray:
    """1.0 up, 0.0 down, NaN when equal or when the horizon is not fully observed (missing bars or end of data). USES THE FUTURE: target only."""
    n = len(close)
    y = np.full(n, np.nan)
    if n > horizon:
        ok = (t[horizon:] - t[:-horizon]) == horizon * bar_s            # all bars in between exist (no gap)
        d = close[horizon:] - close[:-horizon]
        y[:-horizon] = np.where(ok & (d > 0), 1.0, np.where(ok & (d < 0), 0.0, np.nan))
    return y
