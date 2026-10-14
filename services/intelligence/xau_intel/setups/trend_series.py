"""Per-bar direction context for the setup machine (policy `dir-1`). Everything is the value that was knowable at that bar's CLOSE.

structure_trend_series : UP/DOWN/RANGE/UNKNOWN from the swings confirmed by each bar (zig-zag, k=2.5).
direction_series       : UP if structure UP and EMA50 slope > 0 and close above EMA200 (DOWN mirrored); UNKNOWN while EMA200/ATR do not
                         exist (INSUFFICIENT_HISTORY), NONE otherwise. Two simple agreeing confirmations on top of structure; not tuned.
align_to               : value of a higher timeframe at each lower-timeframe bar close: the latest higher bar CLOSED at or before it.
"""
from __future__ import annotations

import numpy as np

from ..indicators import compute_features
from ..structure import TF_SEC, zigzag_swings

DIR_VERSION = "dir-1"


def structure_trend_series(h, l, c, t, tf: str, k: float = 2.5) -> np.ndarray:
    h, l, c, t = (np.asarray(v, float) for v in (h, l, c, t))
    n = len(c)
    sw = sorted((s for s in zigzag_swings(h, l, c, t, tf, k=k) if not s.window_start_artifact), key=lambda s: (s.known_idx, s.idx, s.kind))
    out = np.full(n, "UNKNOWN", dtype=object)
    last_sw = {"H": None, "L": None}
    lab = {"H": None, "L": None}
    si = 0
    for j in range(n):
        while si < len(sw) and sw[si].known_idx <= j:            # known by the close of bar j
            s = sw[si]
            prev = last_sw[s.kind]
            if prev is not None:
                if s.kind == "H":
                    lab["H"] = "HH" if s.price > prev.price else "LH" if s.price < prev.price else "EH"
                else:
                    lab["L"] = "HL" if s.price > prev.price else "LL" if s.price < prev.price else "EL"
            last_sw[s.kind] = s
            si += 1
        lh, ll = lab["H"], lab["L"]
        out[j] = "UNKNOWN" if (lh is None or ll is None) else "UP" if (lh == "HH" and ll == "HL") else "DOWN" if (lh == "LH" and ll == "LL") else "RANGE"
    return out


def direction_series(o, h, l, c, t, tf: str, k: float = 2.5) -> np.ndarray:
    f = compute_features(o, h, l, c)
    trend = structure_trend_series(h, l, c, t, tf, k)
    e50, e200 = f["ema"][50], f["ema"][200]
    slope = f["ema_slope_atr"][50]
    c = np.asarray(c, float)
    out = np.full(len(c), "NONE", dtype=object)
    bad = np.isnan(e200) | np.isnan(slope)
    up = (trend == "UP") & (slope > 0) & (c > e200)
    dn = (trend == "DOWN") & (slope < 0) & (c < e200)
    out[up] = "UP"
    out[dn] = "DOWN"
    out[bad] = "UNKNOWN"
    return out


def align_to(low_t, low_tf: str, high_t, high_tf: str, high_values) -> np.ndarray:
    """For each low-timeframe bar (close time = open + tf), the value of the latest high-timeframe bar closed at or before that moment."""
    low_close = np.asarray(low_t, dtype=np.int64) + TF_SEC[low_tf]
    high_close = np.asarray(high_t, dtype=np.int64) + TF_SEC[high_tf]
    idx = np.searchsorted(high_close, low_close, side="right") - 1
    hv = np.asarray(high_values, dtype=object)
    out = np.full(len(low_close), "UNKNOWN", dtype=object)
    ok = idx >= 0
    out[ok] = hv[idx[ok]]
    return out
