"""Quantified candle patterns on CLOSED bars (policy `pa-1`). Every definition is ATR-normalised and evaluated at the bar's close,
so nothing here can see a later bar. A pattern name is a label for these numbers, nothing more.

bullish pin bar   : range >= 0.5 ATR, lower wick >= 60% of range, body <= 30% of range, close in the top 40% of the range
bullish engulfing : previous bar bearish, this bar bullish, this body covers the previous body (open <= prev close, close >= prev open),
                    body >= 0.5 ATR
strong bullish close : bullish, body >= 60% of range, close within the top 20% of the range, range >= 0.8 ATR
Bearish versions are exact mirrors (computed by mirroring the prices, so they cannot diverge from the bullish ones).
"""
from __future__ import annotations

import numpy as np

PA_VERSION = "pa-1"


def _bull(o, h, l, c, atr) -> dict:
    o, h, l, c, atr = (np.asarray(v, dtype=float) for v in (o, h, l, c, atr))
    n = len(c)
    rng = h - l
    body = np.abs(c - o)
    lower = np.minimum(o, c) - l
    with np.errstate(divide="ignore", invalid="ignore"):
        lw, bd = lower / rng, body / rng
        pos = (c - l) / rng                       # 0 = close at the low, 1 = at the high
        ok = ~np.isnan(atr) & (rng > 0)
        pin = ok & (rng >= 0.5 * atr) & (lw >= 0.60) & (bd <= 0.30) & (pos >= 0.60)
        strong = ok & (c > o) & (bd >= 0.60) & (pos >= 0.80) & (rng >= 0.8 * atr)
    engulf = np.zeros(n, dtype=bool)
    if n > 1:
        prev_bear = c[:-1] < o[:-1]
        cur_bull = c[1:] > o[1:]
        covers = (o[1:] <= c[:-1]) & (c[1:] >= o[:-1])
        engulf[1:] = prev_bear & cur_bull & covers & (body[1:] >= 0.5 * atr[1:]) & ~np.isnan(atr[1:])
    return {"pin": pin, "engulf": engulf, "strong": strong}


def candle_patterns(o, h, l, c, atr) -> dict:
    """Boolean arrays per pattern. Keys: pin_bull, engulf_bull, strong_bull, pin_bear, engulf_bear, strong_bear, any_bull, any_bear."""
    o, h, l, c, atr = (np.asarray(v, dtype=float) for v in (o, h, l, c, atr))
    b = _bull(o, h, l, c, atr)
    s = _bull(-o, -l, -h, -c, atr)               # mirror: a bearish pattern is a bullish pattern of the mirrored prices
    out = {"pin_bull": b["pin"], "engulf_bull": b["engulf"], "strong_bull": b["strong"],
           "pin_bear": s["pin"], "engulf_bear": s["engulf"], "strong_bear": s["strong"]}
    out["any_bull"] = out["pin_bull"] | out["engulf_bull"] | out["strong_bull"]
    out["any_bear"] = out["pin_bear"] | out["engulf_bear"] | out["strong_bear"]
    return out
