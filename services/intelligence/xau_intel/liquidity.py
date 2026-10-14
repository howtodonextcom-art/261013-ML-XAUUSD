"""Liquidity sweeps and false breakouts: causal, optional evidence (not a mandatory strategy condition).

Rules (feature_version `liq-1`), all evaluated on CLOSED bars with levels that were confirmed on an EARLIER bar:
- SWEEP_HIGH at bar j: the bar's high exceeds the latest unbroken confirmed swing high but its CLOSE is at or below that level
  (price took the liquidity above the level and was rejected). SWEEP_LOW is the mirror. A level is swept (reported) at most once
  and a sweep does NOT consume it: a later close beyond the level is still a break, with the same one-break-per-level lifecycle as
  structure_events. A bar that closes beyond the level is a break, never a sweep.
- FALSE_BREAKOUT_UP: after a bar closed above a level (BOS/BREAKOUT/CHOCH up), the first bar within `window` bars that closes back
  below that level. FALSE_BREAKOUT_DOWN is the mirror. Known at the close of the failing bar, never before.
These are candidates: they say what price did around a level, not that a reversal will follow.
"""
from __future__ import annotations

import numpy as np

from .structure import TF_SEC, Swing, fractal_swings, structure_events, zigzag_swings

LIQ_VERSION = "liq-1"


def _row(kind, level: Swing, j, t, sec, tf, evaluated_at, extra=None):
    close_t = int(t[j]) + sec
    d = {"event": kind, "level": level.price, "level_known_at": level.known_at, "event_time": int(t[j]), "formed_at": int(t[j]),
         "known_at": close_t, "evaluated_at": evaluated_at if evaluated_at is not None else close_t, "bar_idx": j,
         "source_timeframe": tf, "feature_version": LIQ_VERSION}
    if extra:
        d.update(extra)
    return d


def liquidity_events(o, h, l, c, times, tf: str, method: str = "zigzag", k: float = 2.5, n: int = 3, window: int = 3,
                     evaluated_at: int | None = None) -> list[dict]:
    h, l, c, t = (np.asarray(v, float) for v in (h, l, c, times))
    sec = TF_SEC[tf]
    sw = zigzag_swings(h, l, c, t, tf, k=k) if method == "zigzag" else fractal_swings(h, l, t, tf, n=n)
    sw = sorted((s for s in sw if not s.window_start_artifact), key=lambda s: (s.known_idx, s.idx, s.kind))
    out: list[dict] = []
    last = {"H": None, "L": None}
    broken: set[tuple] = set()        # levels a bar has closed beyond: one break per level, same rule as structure_events
    swept: set[tuple] = set()         # levels already swept (reported once). A sweep does NOT consume the level for breaks
    pending: list[tuple] = []         # (direction, level, break_bar) waiting for a failure within `window` bars
    si = 0
    for j in range(len(c)):
        while si < len(sw) and sw[si].known_idx <= j - 1:
            last[sw[si].kind] = sw[si]
            si += 1
        # false breakouts: a pending break fails on the first later bar (within the window) that closes back inside
        still = []
        for dirn, lv, j0 in pending:
            if j > j0 + window:
                continue
            if j > j0 and ((dirn == "UP" and c[j] < lv.price) or (dirn == "DOWN" and c[j] > lv.price)):
                out.append(_row(f"FALSE_BREAKOUT_{dirn}", lv, j, t, sec, tf, evaluated_at, {"breakout_bar_idx": j0}))
            else:
                still.append((dirn, lv, j0))
        pending = still
        hi, lo = last["H"], last["L"]
        if hi is not None and (hi.kind, hi.idx) not in broken:
            if c[j] > hi.price:
                broken.add((hi.kind, hi.idx))
                pending.append(("UP", hi, j))
            elif h[j] > hi.price and (hi.kind, hi.idx) not in swept:     # wick through, close back at or below the level
                swept.add((hi.kind, hi.idx))
                out.append(_row("SWEEP_HIGH", hi, j, t, sec, tf, evaluated_at))
        if lo is not None and (lo.kind, lo.idx) not in broken:
            if c[j] < lo.price:
                broken.add((lo.kind, lo.idx))
                pending.append(("DOWN", lo, j))
            elif l[j] < lo.price and (lo.kind, lo.idx) not in swept:
                swept.add((lo.kind, lo.idx))
                out.append(_row("SWEEP_LOW", lo, j, t, sec, tf, evaluated_at))
    out.sort(key=lambda e: (e["bar_idx"], e["event"]))
    return out
