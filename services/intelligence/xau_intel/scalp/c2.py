"""Scalping candidate C2 (SHADOW, research only). Protocol: docs/research/SCALPING_C2_C3_PREREGISTRATION.md (committed before this code).

M5 structure gives the side, an M15 zone gives the place, a CLOSED M1 bar gives the trigger. H1/H4 is a LABEL (ALIGNED / COUNTERTREND / NEUTRAL / UNKNOWN), never a gate.
A pure function of CLOSED bars known at `now_s`: no hidden state, no randomness, no clock. Every event carries `known_at` (the close of the M1 bar at which it became knowable).
SELL is the exact mirror of BUY. The forming bar never enters an event. Nothing here sends, modifies or cancels an order, changes a V1 or V2 decision, or authorises execution.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..indicators import atr as atr_fn
from ..m1.entry_v2 import _closed, _idx_at, _mirror, _price_back
from ..setups.machine import _mirror_swings
from ..setups.patterns import candle_patterns
from ..setups.trend_series import align_to, direction_series, structure_trend_series
from ..setups.zones import build_zones
from ..structure import zigzag_swings

C2_VERSION = "scalp-c2-1"
STRATEGY_ID = "scalp-c2"
LABEL = "SHADOW: scalping candidate C2, research only. Not a decision, not an order."
WINDOW_M1 = 600
STAGES = ("NO_SIDE", "NO_ZONE", "WATCH", "M1_TRIGGERED", "ENTRY_WINDOW")
NEXT = {
    "NO_SIDE": "the M5 structure must turn UP (BUY side) or DOWN (SELL side): it is sideways or unknown now",
    "NO_ZONE": "price must come within reach of a confirmed M15 support (BUY) / resistance (SELL) zone",
    "WATCH": "a CLOSED M1 trigger bar (rejection, engulfing, momentum shift or local structure break) inside the zone band",
    "M1_TRIGGERED": "price must return within the entry band (0.25 ATR5 of the trigger close) before the window ends",
    "ENTRY_WINDOW": "risk and spread are re-checked now; the window ends 5 M1 bars after the trigger",
}
NEXT_SELL = {k: v.replace("support (BUY) / resistance (SELL)", "resistance (SELL) / support (BUY)").replace("above", "below") for k, v in NEXT.items()}
TERMINAL = ("MISSED", "INVALIDATED", "EXPIRED")


@dataclass(frozen=True)
class C2Policy:                                   # numerically the registered V2 model: the frozen evaluator is reused
    version: str = C2_VERSION
    entry_window_m1: int = 5
    window_chase_atr5: float = 0.25
    missed_atr5: float = 0.5
    zone_above_atr15: float = 0.25
    zone_below_atr15: float = 2.0
    band_below_atr5: float = 0.25
    band_above_atr5: float = 0.5
    invalid_buffer_atr5: float = 0.25
    sl_buffer_atr5: float = 0.25
    tp_rr: float = 2.0
    momentum_range_atr: float = 0.8
    momentum_lookback: int = 3
    momentum_lower_closes: int = 2


POLICY = C2Policy()


def alignment(ctx_value: str, sign: int) -> str:
    want = "UP" if sign == 1 else "DOWN"
    if ctx_value == want:
        return "ALIGNED"
    if ctx_value in ("UP", "DOWN"):
        return "COUNTERTREND"
    return "NEUTRAL" if ctx_value == "NONE" else "UNKNOWN"


def _scan(sign: int, A: dict, pol: C2Policy, window: int = WINDOW_M1) -> dict:
    """BUY logic on (possibly mirrored) arrays."""
    m1, sw15, sw1 = A["m1"], A["sw15"], A["sw1"]
    n1 = len(m1["close"])
    direction = "BUY" if sign == 1 else "SELL"
    side_ok, opp_ok, p1 = A["side_ok"], A["opp_ok"], A["pat1"]
    events: list[dict] = []
    trig = None
    cache: dict = {}
    sw_by_known = sorted((s for s in sw15 if not s.window_start_artifact), key=lambda s: s.known_at)
    sw1_known = sorted((s for s in sw1 if not s.window_start_artifact), key=lambda s: s.known_idx)

    def emit(i, stage, kind, reasons, zone, extra=None):
        T = int(m1["time"][i]) + 60
        z = None if zone is None else {"low": _price_back(sign, zone.low if sign == 1 else zone.high), "high": _price_back(sign, zone.high if sign == 1 else zone.low)}
        ev = {"event_id": f"{STRATEGY_ID}-{direction}-{kind}-{int(m1['time'][i])}-{0 if zone is None else round(sign * zone.center, 2)}", "strategy_id": STRATEGY_ID, "version": pol.version,
              "direction": direction, "stage": stage, "kind": kind, "bar_time": int(m1["time"][i]), "known_at": T, "zone": z, "reasons": list(reasons)}
        if extra:
            ev.update(extra)
            for k in ("trigger_close", "trigger_low"):
                if k in ev:
                    ev[k] = _price_back(sign, ev[k])
            ev["log_schema"] = 2
        events.append(ev)

    start = max(0, n1 - window)
    si = 0
    for i in range(start, n1):
        T = int(m1["time"][i]) + 60
        a1, j5, j15 = A["atr1"][i], A["j5"][i], A["j15"][i]
        if j5 < 0 or j15 < 0 or np.isnan(a1) or np.isnan(A["atr5"][j5]) or np.isnan(A["atr15"][j15]):
            continue
        a5, a15 = float(A["atr5"][j5]), float(A["atr15"][j15])
        c = float(m1["close"][i])
        if trig is not None:
            k = (T - trig["known_at"]) // 60                       # elapsed MINUTES by the clock, not bars: a feed gap cannot stretch the window
            if k >= 1:
                if opp_ok[i]:                                                   # registered: the M5 structure flips to the OPPOSITE side (RANGE alone does not invalidate)
                    emit(i, "INVALIDATED", "INVALIDATED", ["M5_STRUCTURE_FLIPPED_TO_THE_OPPOSITE_SIDE"], trig["zone"]); trig = None
                elif c < trig["inval"]:
                    emit(i, "INVALIDATED", "INVALIDATED", ["CLOSE_BELOW_ZONE_INVALIDATION"], trig["zone"]); trig = None
                elif c > trig["close"] + pol.missed_atr5 * a5:
                    emit(i, "MISSED", "MISSED", ["PRICE_RAN_AWAY_BEFORE_ENTRY"], trig["zone"]); trig = None
                elif k > pol.entry_window_m1:
                    emit(i, "EXPIRED", "EXPIRED", ["ENTRY_WINDOW_ENDED"], trig["zone"]); trig = None
                else:
                    want = "ENTRY_WINDOW" if c <= trig["close"] + pol.window_chase_atr5 * a5 else "M1_TRIGGERED"
                    if want != trig["stage"]:
                        trig["stage"] = want
                        emit(i, want, "WINDOW_STATE", ["PRICE_IN_ENTRY_BAND" if want == "ENTRY_WINDOW" else "PRICE_OUTSIDE_ENTRY_BAND"], trig["zone"])
            continue                                        # while a trigger is active nothing else is evaluated on this bar
        if not side_ok[i]:
            continue
        while si < len(sw_by_known) and sw_by_known[si].known_at <= T:
            si += 1
        key = (si, round(a15, 4))
        if key not in cache:
            cache[key] = build_zones(sw_by_known[:si], a15, 0.5, 0.25, 2)
        cands = [z for z in cache[key] if z.high <= c + pol.zone_above_atr15 * a15 and z.high >= c - pol.zone_below_atr15 * a15]
        zone = min(cands, key=lambda q: (abs(q.high - c), -q.touches, q.center)) if cands else None      # A4: nearest by |zone.high - price|, then more touches, then lower
        if zone is None:
            continue
        lo, hi = zone.low - pol.band_below_atr5 * a5, zone.high + pol.band_above_atr5 * a5
        if not (lo <= c <= hi):
            continue
        flags = []
        if p1["pin_bull"][i]:
            flags.append("M1_REJECTION")
        if p1["engulf_bull"][i]:
            flags.append("M1_ENGULFING")
        lb = pol.momentum_lookback
        if i >= lb + 1 and c > float(np.max(m1["high"][i - lb:i])) and (m1["high"][i] - m1["low"][i]) >= pol.momentum_range_atr * a1:
            lower = int(np.sum(m1["close"][i - 4:i] < m1["close"][i - 5:i - 1])) if i >= 5 else 0
            if lower >= pol.momentum_lower_closes:
                flags.append("M1_MOMENTUM_SHIFT")
        known1 = [x for x in sw1_known if x.known_idx <= i - 1 and x.kind == "H"]
        if known1 and i >= 1 and c > known1[-1].price and float(m1["close"][i - 1]) <= known1[-1].price:
            flags.append("M1_STRUCTURE_BREAK")
        if flags:
            trig = {"i": i, "close": c, "low": float(m1["low"][i]), "zone": zone, "kind": flags[0], "flags": flags, "stage": "M1_TRIGGERED",
                    "inval": zone.low - pol.invalid_buffer_atr5 * a5, "a5": a5, "known_at": T, "align": str(A["align"][i]), "h4c": bool(A["h4c"][i]), "h1": str(A["h1v"][i]), "h4": str(A["h4v"][i])}
            emit(i, "M1_TRIGGERED", flags[0], ["M1_TRIGGER_BAR_CLOSED:" + "+".join(flags)], zone,
                 {"trigger_close": c, "trigger_low": trig["low"], "atr5": a5, "atr15": a15, "alignment": trig["align"], "h4_conflict": trig["h4c"], "h1": trig["h1"], "h4": trig["h4"], "m5_structure": "UP" if sign == 1 else "DOWN",
                  "evidence": ["M5_STRUCTURE_SIDE", *flags]})
    # ---------------- final state
    last_i = n1 - 1
    zone_now = None
    if n1:
        T = int(m1["time"][last_i]) + 60
        j15 = A["j15"][last_i]
        if j15 >= 0 and not np.isnan(A["atr15"][j15]):
            a15 = float(A["atr15"][j15])
            known = [s for s in sw_by_known if s.known_at <= T]
            zs = build_zones(known, a15, 0.5, 0.25, 2)
            cands = [z for z in zs if z.high <= float(m1["close"][last_i]) + pol.zone_above_atr15 * a15 and z.high >= float(m1["close"][last_i]) - pol.zone_below_atr15 * a15]
            zone_now = min(cands, key=lambda q: (abs(q.high - float(m1["close"][last_i])), -q.touches, q.center)) if cands else None
    if trig is not None:
        stage, z = trig["stage"], trig["zone"]
    elif n1 and side_ok[last_i]:
        stage, z = ("WATCH", zone_now) if zone_now is not None else ("NO_ZONE", None)
    else:
        stage, z = "NO_SIDE", None
    pb = lambda zz: None if zz is None else {"low": _price_back(sign, zz.low if sign == 1 else zz.high), "high": _price_back(sign, zz.high if sign == 1 else zz.low)}  # noqa: E731
    state = {"direction": direction, "stage": stage, "zone": pb(z), "zone_nearby": pb(zone_now), "next_required": (NEXT if sign == 1 else NEXT_SELL)[stage]}
    if trig is not None:
        state.update(trigger={"kind": trig["kind"], "flags": trig["flags"], "bar_close": _price_back(sign, trig["close"]), "bar_extreme": _price_back(sign, trig["low"]), "known_at": trig["known_at"],
                              "window_ends_at": int(m1["time"][trig["i"]]) + 60 * (pol.entry_window_m1 + 1), "invalidation": _price_back(sign, trig["inval"]), "atr5": trig["a5"],
                              "alignment": trig["align"], "h4_conflict": trig["h4c"]})
    return {"events": events, "state": state}


def m1_momentum(m1: dict, atr1: np.ndarray) -> str:
    """DISPLAY ONLY (never part of a rule or an event): net change of the last 5 CLOSED M1 closes in units of ATR(M1): above +0.5 UP, below -0.5 DOWN, else NEUTRAL; UNKNOWN below 20 bars."""
    n = len(m1["close"])
    if n < 20 or np.isnan(atr1[-1]) or atr1[-1] <= 0:
        return "UNKNOWN"
    chg = (float(m1["close"][-1]) - float(m1["close"][-6])) / float(atr1[-1])
    return "UP" if chg > 0.5 else "DOWN" if chg < -0.5 else "NEUTRAL"


def run_c2(bars: dict, now_s: int, pol: C2Policy = POLICY, window: int = WINDOW_M1) -> dict:
    """bars: tf -> dict(time, open, high, low, close) for M1, M5, M15, H1, H4 (later bars are removed by the snapshot rule)."""
    B = {tf: _closed(bars[tf], tf, now_s) for tf in ("M1", "M5", "M15", "H1", "H4")}
    out = {"strategy_id": STRATEGY_ID, "version": pol.version, "label": LABEL, "now": int(now_s), "bars": {tf: int(len(b["time"])) for tf, b in B.items()}}
    if min(len(B[tf]["close"]) for tf in ("M1", "M5", "M15")) < 30:      # H1/H4 may be short or empty: they are only labels (UNKNOWN); a guard on them would make events depend on how much LATER history exists
        return {**out, "m5_structure": "UNKNOWN", "m1_momentum": "UNKNOWN", "h1_h4": {"h1": "UNKNOWN", "h4": "UNKNOWN", "conflict": False}, "side": None, "directions": {}, "events": [], "funnel": {}}
    t1 = B["M1"]["time"]
    trend5 = structure_trend_series(B["M5"]["high"], B["M5"]["low"], B["M5"]["close"], B["M5"]["time"].astype(float), "M5")
    d1 = direction_series(B["H1"]["open"], B["H1"]["high"], B["H1"]["low"], B["H1"]["close"], B["H1"]["time"], "H1")
    d4 = direction_series(B["H4"]["open"], B["H4"]["high"], B["H4"]["low"], B["H4"]["close"], B["H4"]["time"], "H4")
    ctx = align_to(t1.astype(float), "M1", B["H1"]["time"], "H1", d1)
    ctx4 = align_to(t1.astype(float), "M1", B["H4"]["time"], "H4", d4)
    h4c = ((ctx == "UP") & (ctx4 == "DOWN")) | ((ctx == "DOWN") & (ctx4 == "UP"))
    sw15 = zigzag_swings(B["M15"]["high"], B["M15"]["low"], B["M15"]["close"], B["M15"]["time"].astype(float), "M15", k=2.5)
    sw1 = zigzag_swings(B["M1"]["high"], B["M1"]["low"], B["M1"]["close"], t1.astype(float), "M1", k=2.5)
    atr = {tf: atr_fn(B[tf]["high"], B[tf]["low"], B[tf]["close"], 14) for tf in ("M1", "M5", "M15")}
    T1 = t1 + 60
    j5 = np.array([_idx_at(B["M5"]["time"], "M5", int(x)) for x in T1])
    j15 = np.array([_idx_at(B["M15"]["time"], "M15", int(x)) for x in T1])
    t5m1 = np.where(j5 >= 0, trend5[np.maximum(j5, 0)], "UNKNOWN")                 # M5 structure known at the close of each M1 bar
    res = {}
    for sign in (1, -1):
        M = {tf: (B[tf] if sign == 1 else _mirror(B[tf])) for tf in ("M1", "M5", "M15")}
        pat1 = candle_patterns(M["M1"]["open"], M["M1"]["high"], M["M1"]["low"], M["M1"]["close"], atr["M1"])
        align = np.array([alignment(str(x), sign) for x in ctx], dtype=object)
        A = {"m1": M["M1"], "sw15": sw15 if sign == 1 else _mirror_swings(sw15), "sw1": sw1 if sign == 1 else _mirror_swings(sw1), "side_ok": t5m1 == ("UP" if sign == 1 else "DOWN"), "opp_ok": t5m1 == ("DOWN" if sign == 1 else "UP"), "h1v": ctx, "h4v": ctx4,
             "pat1": pat1, "atr1": atr["M1"], "atr5": atr["M5"], "atr15": atr["M15"], "j5": j5, "j15": j15, "align": align, "h4c": h4c}
        res["BUY" if sign == 1 else "SELL"] = _scan(sign, A, pol, window)
    m5_last = str(trend5[-1])
    side = "BUY" if m5_last == "UP" else "SELL" if m5_last == "DOWN" else None
    events = sorted(res["BUY"]["events"] + res["SELL"]["events"], key=lambda e: (e["known_at"], e["direction"], e["event_id"]))
    funnel = {}
    for e in events:
        funnel[e["kind"]] = funnel.get(e["kind"], 0) + 1
    h1_last, h4_last = str(ctx[-1]), str(ctx4[-1])
    return {**out, "m5_structure": {"UP": "UP", "DOWN": "DOWN", "RANGE": "SIDEWAYS"}.get(m5_last, "UNKNOWN"), "m1_momentum": m1_momentum(B["M1"], atr["M1"]),
            "h1_h4": {"h1": h1_last, "h4": h4_last, "conflict": bool(h4c[-1]), "alignment": alignment(h1_last, 1 if side == "BUY" else -1) if side else None},
            "m15": {"atr": None if np.isnan(atr["M15"][-1]) else float(atr["M15"][-1]), "support": res["BUY"]["state"]["zone_nearby"], "resistance": res["SELL"]["state"]["zone_nearby"]},
            "side": side, "directions": {k: v["state"] for k, v in res.items()}, "events": events, "funnel": funnel,
            "atr": {tf: (None if np.isnan(a[-1]) else float(a[-1])) for tf, a in atr.items()}}
