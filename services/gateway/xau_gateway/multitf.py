"""Multi-timeframe helpers: aggregate M1 -> M5/M15/H1/H4 using the broker's bucket convention, and warm-up accounting.

Convention (measured on MetaQuotes-Demo XAUUSD, see docs/qa/HISTORICAL_DATA_SPEC.md): every timeframe bucket starts at
epoch_server_time // seconds * seconds (H4 bars start at server hours 0,4,8,...,20 and the series is expressed in server wall-clock
time, so the rule holds across DST changes). Buckets with no M1 bar are NOT created (no synthetic candles); a bucket that only
partially exists (daily break, session edge) is aggregated from the bars that exist, exactly as MT5 does.
"""
from __future__ import annotations

import numpy as np

TF_SECONDS = {"M1": 60, "M5": 300, "M15": 900, "H1": 3600, "H4": 14400}

# Bars needed before an indicator is allowed to answer instead of INSUFFICIENT_HISTORY.
# EMA(n) needs >= n bars to exist at all; >= 3n for the seed's influence to be negligible (documented rule of thumb, not exact).
WARMUP = {"EMA200": (200, 600), "EMA100": (100, 300), "EMA50": (50, 150), "EMA20": (20, 60), "RSI14": (15, 100),
          "MACD12_26_9": (35, 105), "ATR14": (15, 100)}


def aggregate_m1(times, o, h, l, c, tv, tf: str):
    """Aggregate sorted M1 arrays to `tf`. Returns dict of arrays (time, open, high, low, close, tick_volume, n_m1)."""
    sec = TF_SECONDS[tf]
    times = np.asarray(times, dtype=np.int64)
    if len(times) == 0:
        return {k: np.array([]) for k in ("time", "open", "high", "low", "close", "tick_volume", "n_m1")}
    bucket = times // sec * sec
    starts = np.r_[0, np.where(np.diff(bucket) != 0)[0] + 1]
    ends = np.r_[starts[1:], len(times)]
    o, h, l, c, tv = (np.asarray(x) for x in (o, h, l, c, tv))
    return {
        "time": bucket[starts],
        "open": o[starts],
        "high": np.maximum.reduceat(h, starts),
        "low": np.minimum.reduceat(l, starts),
        "close": c[ends - 1],
        "tick_volume": np.add.reduceat(tv, starts).astype(np.int64),
        "n_m1": (ends - starts),
    }


def warmup_status(n_bars_by_tf: dict[str, int]) -> dict:
    """Per timeframe and indicator: INSUFFICIENT_HISTORY / MINIMUM_ONLY / CONVERGED based on available bar counts."""
    out = {}
    for tf, n in n_bars_by_tf.items():
        out[tf] = {"bars": n, "indicators": {
            name: ("INSUFFICIENT_HISTORY" if n < mn else "MINIMUM_ONLY" if n < conv else "CONVERGED")
            for name, (mn, conv) in WARMUP.items()}}
    return out
