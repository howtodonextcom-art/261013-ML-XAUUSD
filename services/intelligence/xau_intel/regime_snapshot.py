"""Point-in-time multi-timeframe snapshot and market regime classification.

Snapshot rule: for evaluation time t (server epoch s) a timeframe contributes ONLY bars whose close time (open + tf seconds) <= t.
The still-forming bar is never included. Arrays are read-only. The same inputs always give the same output (deterministic).

Regime thresholds below are INITIAL DESIGN PARAMETERS chosen from the definitions of the features, not tuned on outcomes.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .indicators import FEATURE_VERSION, compute_features
from .liquidity import liquidity_events
from .structure import STRUCT_VERSION, TF_SEC, label_structure, structure_events, support_resistance, trend_from_labels, zigzag_swings

REGIME_VERSION = "regime-1"
REGIMES = ("TRENDING_UP", "TRENDING_DOWN", "SIDEWAYS", "COMPRESSION", "VOLATILITY_EXPANSION", "TRANSITION", "UNKNOWN")
MIN_BARS = 220          # EMA200 must exist (200) plus slope window; fewer => INSUFFICIENT_HISTORY
TH = {"expansion_ratio": 1.5, "expansion_pct": 0.8, "compression_atr": 0.5, "compression_ratio": 0.8, "flat_slope": 0.15}


@dataclass(frozen=True)
class TfBars:
    tf: str
    time: np.ndarray
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    spread_price: np.ndarray | None = None


@dataclass(frozen=True)
class Snapshot:
    evaluated_at: int
    tfs: dict = field(default_factory=dict)       # tf -> TfBars (closed bars only, read-only arrays)
    versions: dict = field(default_factory=dict)


def build_snapshot(bars_by_tf: dict, t_now: int) -> Snapshot:
    """bars_by_tf: tf -> dict(time, open, high, low, close[, spread_price]) sorted by time. Keeps bars closed at or before t_now."""
    out = {}
    for tf, b in bars_by_tf.items():
        sec = TF_SEC[tf]
        t = np.asarray(b["time"], dtype=np.int64)
        keep = (t + sec) <= t_now
        arrs = {k: np.asarray(b[k], dtype=float)[keep] for k in ("open", "high", "low", "close")}
        sp = np.asarray(b["spread_price"], dtype=float)[keep] if b.get("spread_price") is not None else None
        for a in (*arrs.values(), t[keep]):
            a.setflags(write=False)
        out[tf] = TfBars(tf, t[keep], arrs["open"], arrs["high"], arrs["low"], arrs["close"], sp)
    return Snapshot(int(t_now), out, {"indicators": FEATURE_VERSION, "structure": STRUCT_VERSION, "regime": REGIME_VERSION})


def classify_regime(f: dict, i: int, structure_trend: str, recent_choch_against: bool) -> tuple[str, list[str]]:
    """Regime at closed-bar index i from features `f` (compute_features) and structure. Returns (regime, reasons)."""
    if i < MIN_BARS - 1 or np.isnan(f["atr"][i]) or f["ema_alignment"][i] == "INSUFFICIENT_HISTORY":
        return "UNKNOWN", ["INSUFFICIENT_HISTORY"]
    ratio, pct = f["atr_ratio50"][i], f["atr_pct200"][i]
    comp, slope50 = f["ema_compression_atr"][i], f["ema_slope_atr"][50][i]
    align = f["ema_alignment"][i]
    if not np.isnan(ratio) and not np.isnan(pct) and ratio >= TH["expansion_ratio"] and pct >= TH["expansion_pct"]:
        return "VOLATILITY_EXPANSION", [f"atr_ratio50={ratio:.2f}>={TH['expansion_ratio']}", f"atr_pct200={pct:.2f}>={TH['expansion_pct']}"]
    if comp < TH["compression_atr"] and not np.isnan(ratio) and ratio <= TH["compression_ratio"]:
        return "COMPRESSION", [f"ema_spread/atr={comp:.2f}<{TH['compression_atr']}", f"atr_ratio50={ratio:.2f}<={TH['compression_ratio']}"]
    if align == "BULL" and slope50 > 0 and structure_trend == "UP" and not recent_choch_against:
        return "TRENDING_UP", ["ema_alignment=BULL", f"ema50_slope={slope50:.2f}>0", "structure=UP"]
    if align == "BEAR" and slope50 < 0 and structure_trend == "DOWN" and not recent_choch_against:
        return "TRENDING_DOWN", ["ema_alignment=BEAR", f"ema50_slope={slope50:.2f}<0", "structure=DOWN"]
    if align == "MIXED" and abs(slope50) < TH["flat_slope"]:
        return "SIDEWAYS", ["ema_alignment=MIXED", f"|ema50_slope|={abs(slope50):.2f}<{TH['flat_slope']}"]
    return "TRANSITION", [f"ema_alignment={align}", f"structure={structure_trend}", f"choch_against={recent_choch_against}"]


MAX_BARS = 5000   # analysis window: EMA200 influence of older bars is below 1e-20 after 5000 bars; keeps the cost bounded


def analyse_tf(b: TfBars, choch_lookback_bars: int = 20, max_bars: int = MAX_BARS) -> dict:
    """Latest-closed-bar intelligence for one timeframe (everything computed from the last `max_bars` closed bars only)."""
    if len(b.close) > max_bars:
        sl = slice(len(b.close) - max_bars, None)
        b = TfBars(b.tf, b.time[sl], b.open[sl], b.high[sl], b.low[sl], b.close[sl], None if b.spread_price is None else b.spread_price[sl])
    n = len(b.close)
    if n == 0:
        return {"tf": b.tf, "bars": 0, "regime": "UNKNOWN", "reasons": ["NO_CLOSED_BARS"]}
    f = compute_features(b.open, b.high, b.low, b.close, b.spread_price)
    i = n - 1
    sw = zigzag_swings(b.high, b.low, b.close, b.time, b.tf, k=2.5)
    labels = label_structure(sw)
    trend = trend_from_labels(labels)
    ev = structure_events(b.open, b.high, b.low, b.close, b.time, b.tf)
    recent = [e for e in ev if e["bar_idx"] >= n - choch_lookback_bars]
    prior = "UP" if trend == "UP" else "DOWN" if trend == "DOWN" else None
    choch_against = any((e["event"] == "CHOCH_DOWN" and prior == "UP") or (e["event"] == "CHOCH_UP" and prior == "DOWN") for e in recent)
    regime, reasons = classify_regime(f, i, trend, choch_against)

    def at(k, sub=None):
        v = (f[k][sub] if sub is not None else f[k])[i]
        return None if (isinstance(v, float) and np.isnan(v)) else (v.item() if hasattr(v, "item") else v)

    return {"tf": b.tf, "bars": n, "last_closed_open_time": int(b.time[i]), "regime": regime, "reasons": reasons,
            "structure_trend": trend, "structure_labels_last": [x["label"] for x in labels[-6:]],
            "events_recent": [{"event": e["event"], "level": e["level"], "known_at": e["known_at"], "bar_open_time": int(b.time[e["bar_idx"]]),
                               "bar_idx_in_window": e["bar_idx"]} for e in recent[-5:]],   # identify events by TIME: indices are relative to the analysed window
            "liquidity_recent": [{"event": e["event"], "level": e["level"], "known_at": e["known_at"], "bar_open_time": int(b.time[e["bar_idx"]])}
                                 for e in liquidity_events(b.open, b.high, b.low, b.close, b.time, b.tf)
                                 if e["bar_idx"] >= n - choch_lookback_bars][-5:],      # candidates only: not a mandatory condition
            "support_resistance": support_resistance(sw[-30:], at("atr")),
            "ema": {n_: at("ema", n_) for n_ in (20, 50, 100, 200)}, "ema_alignment": at("ema_alignment"),
            "ema_slope_atr": {n_: at("ema_slope_atr", n_) for n_ in (20, 50, 100, 200)}, "ema_compression_atr": at("ema_compression_atr"),
            "rsi": at("rsi"), "rsi_regime": at("rsi_regime"), "macd_hist": at("macd_hist"), "macd_cross_age": at("macd_cross_age"),
            "atr": at("atr"), "atr_ratio50": at("atr_ratio50"), "atr_pct200": at("atr_pct200"), "spread_atr": at("spread_atr"),
            "versions": {"indicators": FEATURE_VERSION, "structure": STRUCT_VERSION, "regime": REGIME_VERSION}}


def analyse_snapshot(s: Snapshot) -> dict:
    return {"evaluated_at": s.evaluated_at, "versions": s.versions, "timeframes": {tf: analyse_tf(b) for tf, b in s.tfs.items()}}
