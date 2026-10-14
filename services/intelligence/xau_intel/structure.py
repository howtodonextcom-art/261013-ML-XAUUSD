"""Causal market structure. Every event carries event_time, formed_at, known_at, evaluated_at, source_timeframe, feature_version.

A swing is only ever reported at its `known_idx` (the bar whose CLOSE confirms it). Detection at index c uses bars <= c only, so
results never repaint and never use the future. `swings_known_by(bars, c)` is a pure function of bars[:c+1].

Detectors (see docs/research/SWING_DETECTION_DECISION.md, pre-registered):
  fractal(n)   : swing high if high[i] > every high in the n bars on each side; known at bar i+n.
  zigzag(k)    : swing confirmed once price retraces >= k*ATR14 from the running extreme; known at the confirming bar.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .indicators import atr

STRUCT_VERSION = "struct-1"
TF_SEC = {"M1": 60, "M5": 300, "M15": 900, "H1": 3600, "H4": 14400}


@dataclass(frozen=True)
class Swing:
    kind: str            # "H" or "L"
    idx: int             # bar index of the extreme
    known_idx: int       # bar index at whose close it became known
    price: float
    formed_at: int       # open time of the extreme bar (server epoch s)
    known_at: int        # close time of the confirming bar
    source_timeframe: str
    window_start_artifact: bool = False   # first zig-zag swing: relative to where the analysed window starts, not a proven swing


def fractal_swings(h, l, times, tf: str, n: int = 3, upto: int | None = None) -> list[Swing]:
    h, l, t = np.asarray(h, float), np.asarray(l, float), np.asarray(times)
    last = (len(h) - 1) if upto is None else upto
    sec = TF_SEC[tf]
    out: list[Swing] = []
    for i in range(n, last - n + 1):
        lo, hi = i - n, i + n
        if h[i] > h[lo:i].max() and h[i] > h[i + 1:hi + 1].max():
            out.append(Swing("H", i, hi, float(h[i]), int(t[i]), int(t[hi]) + sec, tf))
        if l[i] < l[lo:i].min() and l[i] < l[i + 1:hi + 1].min():
            out.append(Swing("L", i, hi, float(l[i]), int(t[i]), int(t[hi]) + sec, tf))
    out.sort(key=lambda s: (s.known_idx, s.idx, s.kind))
    return out


def zigzag_swings(h, l, c, times, tf: str, k: float = 2.0, upto: int | None = None) -> list[Swing]:
    """ATR zig-zag, causal. A swing is confirmed once price retraces >= k*ATR14 from the running extreme.

    Initialisation (corrected after review): from the first bar with a valid ATR both the running high and the running low are
    tracked; the first swing is the LOW if price rises k*ATR above the running low first, the HIGH if it falls k*ATR below the running
    high first (previously the first swing was always assumed to be a high).
    Intra-bar ordering policy: OHLC does not say whether a bar's High or Low came first. A bar that BOTH extends the extreme and also
    reaches the retrace threshold does NOT confirm a swing on that bar (the extreme is extended; confirmation can only happen on a later
    bar). During initialisation a bar that satisfies both triggers, or whose only trigger spans its own low and high, is skipped. This
    biases confirmation later, never earlier, and never uses information the OHLC bar does not contain.
    The FIRST swing is flagged `window_start_artifact`: the series starts mid-move, so it is relative to the window start and is not
    used for labels, support/resistance or breakable levels (the swing is still returned for transparency)."""
    h, l, c, t = (np.asarray(v, float) for v in (h, l, c, times))
    last = (len(c) - 1) if upto is None else upto
    a = atr(h[: last + 1], l[: last + 1], c[: last + 1], 14)
    sec = TF_SEC[tf]
    out: list[Swing] = []
    direction = 0  # 1 = tracking a high, -1 = tracking a low
    ext_i, ext_p = 0, 0.0
    hi_i = hi_p = lo_i = lo_p = None
    for i in range(1, last + 1):
        if np.isnan(a[i]):
            continue
        thr = k * a[i]
        if direction == 0:
            if hi_i is None:
                hi_i, hi_p, lo_i, lo_p = i, h[i], i, l[i]
                continue
            if h[i] > hi_p:
                hi_i, hi_p = i, h[i]
            if l[i] < lo_p:
                lo_i, lo_p = i, l[i]
            up = (h[i] - lo_p >= thr) and lo_i < i       # rise measured from a low that formed on an EARLIER bar
            dn = (hi_p - l[i] >= thr) and hi_i < i
            if up and dn:
                continue                                   # both triggers on one bar: order unknowable, wait
            if up:
                out.append(Swing("L", lo_i, i, float(lo_p), int(t[lo_i]), int(t[i]) + sec, tf, True))
                j = lo_i + 1 + int(np.argmax(h[lo_i + 1:i + 1]))
                direction, ext_i, ext_p = 1, j, h[j]
            elif dn:
                out.append(Swing("H", hi_i, i, float(hi_p), int(t[hi_i]), int(t[i]) + sec, tf, True))
                j = hi_i + 1 + int(np.argmin(l[hi_i + 1:i + 1]))
                direction, ext_i, ext_p = -1, j, l[j]
            continue
        if direction == 1:
            if h[i] > ext_p:
                ext_i, ext_p = i, h[i]            # extends; even if the same bar also dropped a lot, no confirmation on this bar
            elif ext_p - l[i] >= thr:
                out.append(Swing("H", ext_i, i, float(ext_p), int(t[ext_i]), int(t[i]) + sec, tf))
                direction, ext_i, ext_p = -1, i, l[i]
        else:
            if l[i] < ext_p:
                ext_i, ext_p = i, l[i]
            elif h[i] - ext_p >= thr:
                out.append(Swing("L", ext_i, i, float(ext_p), int(t[ext_i]), int(t[i]) + sec, tf))
                direction, ext_i, ext_p = 1, i, h[i]
    return out


def swings_known_by(h, l, c, times, tf: str, c_idx: int, method: str = "fractal", **kw) -> list[Swing]:
    """Swings known at the close of bar c_idx, computed ONLY from bars[:c_idx+1]."""
    s = slice(0, c_idx + 1)
    if method == "fractal":
        return fractal_swings(np.asarray(h)[s], np.asarray(l)[s], np.asarray(times)[s], tf, upto=None, **kw)
    return zigzag_swings(np.asarray(h)[s], np.asarray(l)[s], np.asarray(c)[s], np.asarray(times)[s], tf, upto=None, **kw)


def label_structure(swings: list[Swing]) -> list[dict]:
    """HH/HL/LH/LL labels in confirmation order. A label compares a swing with the previous swing of the same kind.
    Window-start artifacts are skipped."""
    last = {"H": None, "L": None}
    out = []
    for s in swings:
        if s.window_start_artifact:
            continue
        prev = last[s.kind]
        if prev is None:
            lab = "FIRST_H" if s.kind == "H" else "FIRST_L"
        elif s.kind == "H":
            lab = "HH" if s.price > prev.price else "LH" if s.price < prev.price else "EH"
        else:
            lab = "HL" if s.price > prev.price else "LL" if s.price < prev.price else "EL"
        out.append({"label": lab, "swing": s})
        last[s.kind] = s
    return out


def trend_from_labels(labels: list[dict]) -> str:
    """UP when the latest high is HH and the latest low is HL; DOWN when LH and LL; otherwise RANGE; UNKNOWN without 2+2 swings."""
    hs = [x["label"] for x in labels if x["swing"].kind == "H" and not x["label"].startswith("FIRST")]
    ls = [x["label"] for x in labels if x["swing"].kind == "L" and not x["label"].startswith("FIRST")]
    if not hs or not ls:
        return "UNKNOWN"
    if hs[-1] == "HH" and ls[-1] == "HL":
        return "UP"
    if hs[-1] == "LH" and ls[-1] == "LL":
        return "DOWN"
    return "RANGE"


def structure_events(o, h, l, c, times, tf: str, n: int = 3, evaluated_at: int | None = None, method: str = "zigzag", k: float = 2.0) -> list[dict]:
    """BOS / CHoCH / breakout events on closed bars, strictly causal and O(bars + swings).
    Default detector: ATR zig-zag k=2.0 (chosen by the fallback clause of a self-attested pre-registered rule: both candidates failed the density criterion; see docs/research/SWING_DETECTION_DECISION.md).
    Only the latest confirmed swing high and low are tracked as breakable levels: an older unbroken level that a newer swing replaced never produces an event (design choice).
    A level is the latest CONFIRMED swing high/low at the time of the break bar (confirmed on a PREVIOUS bar).
    Break = a bar CLOSES beyond that level (a wick is not a break). BOS = break in the direction of the prevailing trend;
    CHOCH = first break against it; BREAKOUT when the trend is RANGE/UNKNOWN. Each level breaks at most once."""
    h, l, c, t = (np.asarray(v, float) for v in (h, l, c, times))
    sec = TF_SEC[tf]
    all_sw = zigzag_swings(h, l, c, t, tf, k=k) if method == "zigzag" else fractal_swings(h, l, t, tf, n=n)
    all_sw = sorted((x for x in all_sw if not x.window_start_artifact), key=lambda s: (s.known_idx, s.idx, s.kind))
    events: list[dict] = []
    broken: set[tuple] = set()
    last_sw: dict[str, Swing | None] = {"H": None, "L": None}
    last_label: dict[str, str | None] = {"H": None, "L": None}    # latest non-FIRST label per kind (what trend_from_labels uses)
    si = 0
    for j in range(len(c)):
        while si < len(all_sw) and all_sw[si].known_idx <= j - 1:   # only swings confirmed on a PREVIOUS bar can be broken by bar j
            sw = all_sw[si]
            prev = last_sw[sw.kind]
            if prev is not None:
                if sw.kind == "H":
                    last_label["H"] = "HH" if sw.price > prev.price else "LH" if sw.price < prev.price else "EH"
                else:
                    last_label["L"] = "HL" if sw.price > prev.price else "LL" if sw.price < prev.price else "EL"
            last_sw[sw.kind] = sw
            si += 1
        hi, lo = last_sw["H"], last_sw["L"]
        if hi is None and lo is None:
            continue
        lh, ll = last_label["H"], last_label["L"]
        trend = "UNKNOWN" if (lh is None or ll is None) else "UP" if (lh == "HH" and ll == "HL") else "DOWN" if (lh == "LH" and ll == "LL") else "RANGE"
        if hi is not None and (hi.kind, hi.idx) not in broken and c[j] > hi.price:
            broken.add((hi.kind, hi.idx))
            kind = "BOS_UP" if trend == "UP" else "CHOCH_UP" if trend == "DOWN" else "BREAKOUT_UP"
            events.append(_ev(kind, hi, j, t, sec, tf, trend, evaluated_at))
        if lo is not None and (lo.kind, lo.idx) not in broken and c[j] < lo.price:
            broken.add((lo.kind, lo.idx))
            kind = "BOS_DOWN" if trend == "DOWN" else "CHOCH_DOWN" if trend == "UP" else "BREAKOUT_DOWN"
            events.append(_ev(kind, lo, j, t, sec, tf, trend, evaluated_at))
    return events


def _ev(kind, level: Swing, j: int, t, sec, tf, trend, evaluated_at):
    close_t = int(t[j]) + sec
    return {"event": kind, "level": level.price, "level_formed_at": level.formed_at, "level_known_at": level.known_at,
            "event_time": int(t[j]), "formed_at": int(t[j]), "known_at": close_t, "evaluated_at": evaluated_at if evaluated_at is not None else close_t,
            "bar_idx": j, "prior_trend": trend, "source_timeframe": tf, "feature_version": STRUCT_VERSION}


def support_resistance(swings: list[Swing], atr_value: float, merge_atr: float = 0.5, max_levels: int = 6) -> list[dict]:
    """Cluster confirmed swing prices that lie within merge_atr*ATR into levels (touch count). Uses confirmed swings only."""
    swings = [x for x in swings if not x.window_start_artifact]
    if not swings or not atr_value or np.isnan(atr_value):
        return []
    pts = sorted(swings, key=lambda s: s.price)
    clusters: list[list[Swing]] = []
    for s in pts:
        if clusters and abs(s.price - np.mean([x.price for x in clusters[-1]])) <= merge_atr * atr_value:
            clusters[-1].append(s)
        else:
            clusters.append([s])
    lv = [{"price": float(np.mean([x.price for x in cl])), "touches": len(cl), "first_known_at": min(x.known_at for x in cl),
           "kinds": sorted({x.kind for x in cl})} for cl in clusters]
    lv.sort(key=lambda d: (-d["touches"], d["price"]))
    return lv[:max_levels]
