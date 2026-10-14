"""M1 Entry Intelligence, candidate V2 (SHADOW). Protocol: docs/research/M1_ENTRY_V2_PREREGISTRATION.md (committed before this code).

A pure function of CLOSED bars known at `now_s`: no hidden state, no randomness, no clock. Every event carries `known_at` (the close time of the
M1 bar at which it became knowable). SELL is the exact mirror of BUY (prices negated, then the BUY logic runs). The forming M1 bar never enters an
event; it can only produce a display-only, explicitly UNCONFIRMED observation (`forming_observation`). Nothing here sends, modifies or cancels an
order, changes a V1 decision, or authorises execution.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..indicators import atr as atr_fn
from ..setups.machine import _mirror_swings
from ..setups.patterns import candle_patterns
from ..setups.trend_series import align_to, direction_series
from ..setups.zones import build_zones
from ..structure import TF_SEC, Swing, zigzag_swings

V2_VERSION = "m1v2-1"
LABEL = "SHADOW: M1 entry-timing research observation. Not a decision, not an order."
WINDOW_M1 = 600


@dataclass(frozen=True)
class V2Policy:
    version: str = V2_VERSION
    confirm_lookback_m5: int = 6
    entry_window_m1: int = 5
    window_chase_atr5: float = 0.25        # ENTRY_WINDOW while the close is within this distance above the trigger close
    missed_atr5: float = 0.5               # beyond this distance before entry: MISSED
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


POLICY = V2Policy()
STAGES = ("NO_CONTEXT", "NO_ZONE", "WATCHING_ZONE", "M5_CONFIRMED_AWAITING_M1", "M1_TRIGGERED", "ENTRY_WINDOW")
TERMINAL = ("MISSED", "INVALIDATED", "FAILED_CONFIRMATION", "EXPIRED", "CONFIRMATION_EXPIRED")
NEXT = {
    "NO_CONTEXT": "the higher timeframe (H1) must show a direction without an H4 conflict",
    "NO_ZONE": "price must come within reach of a confirmed M15 support/resistance zone on the right side",
    "WATCHING_ZONE": "an M5 confirmation bar (pin bar / engulfing / strong close) must close at the zone",
    "M5_CONFIRMED_AWAITING_M1": "a CLOSED M1 trigger bar (rejection, engulfing, momentum shift or local structure break) inside the zone band",
    "M1_TRIGGERED": "price must return within the entry band (0.25 ATR5 of the trigger close) before the window ends",
    "ENTRY_WINDOW": "risk and spread are re-checked now; the window ends 5 M1 bars after the trigger",
}
NEXT_SELL = {k: v.replace("support/resistance", "resistance/support").replace("above", "below") for k, v in NEXT.items()}


def _closed(b: dict, tf: str, now_s: int) -> dict:
    """The snapshot rule: only bars fully closed at `now_s`."""
    t = np.asarray(b["time"], dtype=np.int64)
    m = t + TF_SEC[tf] <= now_s
    return {k: np.asarray(b[k], dtype=float)[m] if k != "time" else t[m] for k in ("time", "open", "high", "low", "close")}


def _mirror(b: dict) -> dict:
    return {"time": b["time"], "open": -b["open"], "high": -b["low"], "low": -b["high"], "close": -b["close"]}


def _idx_at(t: np.ndarray, tf: str, T: int) -> int:
    """Index of the last bar of `t` (open times) that is closed at time T; -1 if none."""
    return int(np.searchsorted(t + TF_SEC[tf], T, side="right")) - 1


def _price_back(sign: int, v):
    return None if v is None else float(sign * v)


def _scan(sign: int, A: dict, pol: V2Policy, window: int = WINDOW_M1) -> dict:
    """BUY logic on (possibly mirrored) arrays. Returns {'events': [...], 'state': {...}}."""
    m1, m5, sw15, sw1 = A["m1"], A["m5"], A["sw15"], A["sw1"]
    n1 = len(m1["close"])
    direction = "BUY" if sign == 1 else "SELL"
    ctx_ok = A["ctx_ok"]
    p1, p5 = A["pat1"], A["pat5"]
    events: list[dict] = []
    conf = None            # M5 confirmation: dict(j, known_at5, zone)
    trig = None            # active trigger
    used_m5: set[int] = set()
    cache: dict = {}
    sw_by_known = sorted((s for s in sw15 if not s.window_start_artifact), key=lambda s: s.known_at)
    sw1_known = sorted((s for s in sw1 if not s.window_start_artifact), key=lambda s: s.known_idx)

    def emit(i, stage, kind, reasons, zone, extra=None):
        T = int(m1["time"][i]) + 60
        z = None if zone is None else {"low": _price_back(sign, zone.low if sign == 1 else zone.high), "high": _price_back(sign, zone.high if sign == 1 else zone.low)}
        ev = {"event_id": f"{direction}-{kind}-{int(m1['time'][i])}-{0 if zone is None else round(sign * zone.center, 2)}", "version": pol.version, "direction": direction,
              "stage": stage, "kind": kind, "bar_time": int(m1["time"][i]), "known_at": T, "zone": z, "reasons": list(reasons)}
        if extra:
            ev.update(extra)
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
        # ---------------- active trigger: window bookkeeping
        if trig is not None:
            k = i - trig["i"]
            if k >= 1:
                if c < trig["inval"]:
                    emit(i, "INVALIDATED", "INVALIDATED", ["CLOSE_BELOW_ZONE_INVALIDATION"], trig["zone"]); trig = None
                elif c > trig["close"] + pol.missed_atr5 * a5:
                    emit(i, "MISSED", "MISSED", ["PRICE_RAN_AWAY_BEFORE_ENTRY"], trig["zone"]); trig = None
                elif k > pol.entry_window_m1:
                    emit(i, "EXPIRED", "EXPIRED", ["ENTRY_WINDOW_ENDED"], trig["zone"]); trig = None
                else:
                    want = "ENTRY_WINDOW" if c <= trig["close"] + pol.window_chase_atr5 * a5 else "M1_TRIGGERED"
                    if want != trig["stage"]:
                        trig["stage"] = want
                        emit(i, want, "WINDOW_STATE", ["PRICE_IN_ENTRY_BAND" if want == "ENTRY_WINDOW" else "PRICE_OUTSIDE_ENTRY_BAND"], trig["zone"])      # kind WINDOW_STATE: a state change of an existing trigger, never counted as a new trigger
            continue                                        # while a trigger is active nothing else is evaluated on this bar
        if not ctx_ok[i]:
            conf = None
            continue
        # ---------------- zone at this time (swings known at T)
        while si < len(sw_by_known) and sw_by_known[si].known_at <= T:
            si += 1
        key = (si, round(a15, 4), round(c / max(a15, 1e-9) * 4))
        if key not in cache:
            zs = build_zones(sw_by_known[:si], a15, 0.5, 0.25, 2)
            cands = [z for z in zs if z.high <= c + pol.zone_above_atr15 * a15 and z.high >= c - pol.zone_below_atr15 * a15]
            cache[key] = max(cands, key=lambda q: q.high) if cands else None
        zone = cache[key]
        # ---------------- existing confirmation: failure / expiry / trigger
        if conf is not None:
            z = conf["zone"]
            if A["c5"][j5] < z.low - pol.invalid_buffer_atr5 * a5 and j5 > conf["j"]:
                emit(i, "FAILED_CONFIRMATION", "FAILED_CONFIRMATION", ["M5_CLOSE_BEYOND_ZONE_INVALIDATION_BEFORE_ANY_M1_TRIGGER"], z); used_m5.add(conf["j"]); conf = None
            elif j5 - conf["j"] > pol.confirm_lookback_m5:
                emit(i, "CONFIRMATION_EXPIRED", "CONFIRMATION_EXPIRED", ["NO_M1_TRIGGER_WITHIN_THE_CONFIRMATION_WINDOW"], z); used_m5.add(conf["j"]); conf = None
            elif int(m1["time"][i]) >= conf["known_at5"]:
                lo, hi = z.low - pol.band_below_atr5 * a5, z.high + pol.band_above_atr5 * a5
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
                known1 = [x for x in sw1_known if x.known_idx <= i - 1 and x.kind == "H"]            # confirmed M1 swing highs only (known before this bar)
                if known1 and i >= 1 and c > known1[-1].price and float(m1["close"][i - 1]) <= known1[-1].price:       # the FIRST close above it
                    flags.append("M1_STRUCTURE_BREAK")
                if flags and lo <= c <= hi:
                    trig = {"i": i, "close": c, "low": float(m1["low"][i]), "zone": z, "kind": flags[0], "flags": flags, "stage": "M1_TRIGGERED",
                            "inval": z.low - pol.invalid_buffer_atr5 * a5, "a5": a5, "known_at": T, "j5": conf["j"]}
                    emit(i, "M1_TRIGGERED", flags[0], ["M1_TRIGGER_BAR_CLOSED:" + "+".join(flags)], z,
                         {"trigger_close": c, "trigger_low": trig["low"], "atr5": a5, "evidence": ["M5_CONFIRMED_AT_ZONE", *flags]})
                    used_m5.add(conf["j"]); conf = None
            continue
        # ---------------- look for an M5 confirmation at the zone
        if zone is None:
            continue
        for j in range(j5, max(-1, j5 - pol.confirm_lookback_m5 - 1), -1):
            if j in used_m5:
                continue
            if p5["any_bull"][j] and A["l5"][j] <= zone.high and A["c5"][j] > zone.low:
                conf = {"j": j, "known_at5": int(m5["time"][j]) + 300, "zone": zone}
                emit(i, "M5_CONFIRMED_AWAITING_M1", "M5_CONFIRMED", ["M5_PATTERN_BAR_AT_ZONE"], zone, {"m5_bar_time": int(m5["time"][j]), "evidence": ["M5_PATTERN_AT_ZONE"]})
                break
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
            zone_now = max(cands, key=lambda q: q.high) if cands else None
    if trig is not None:
        stage, z = trig["stage"], trig["zone"]
    elif conf is not None:
        stage, z = "M5_CONFIRMED_AWAITING_M1", conf["zone"]
    elif n1 and ctx_ok[last_i]:
        stage, z = ("WATCHING_ZONE", zone_now) if zone_now is not None else ("NO_ZONE", None)
    else:
        stage, z = "NO_CONTEXT", None
    zone_out = None if z is None else {"low": _price_back(sign, z.low if sign == 1 else z.high), "high": _price_back(sign, z.high if sign == 1 else z.low)}
    state = {"direction": direction, "stage": stage, "zone": zone_out, "next_required": (NEXT if sign == 1 else NEXT_SELL)[stage]}
    if trig is not None:
        state.update(trigger={"kind": trig["kind"], "flags": trig["flags"], "bar_close": _price_back(sign, trig["close"]), "bar_extreme": _price_back(sign, trig["low"]), "known_at": trig["known_at"],
                              "window_ends_at": int(m1["time"][trig["i"]]) + 60 * (pol.entry_window_m1 + 1), "invalidation": _price_back(sign, trig["inval"]), "atr5": trig["a5"]})
    return {"events": events, "state": state}


def run_v2(bars: dict, now_s: int, pol: V2Policy = POLICY, window: int = WINDOW_M1) -> dict:
    """bars: tf -> dict(time, open, high, low, close) for M1, M5, M15, H1, H4 (later bars are removed by the snapshot rule)."""
    B = {tf: _closed(bars[tf], tf, now_s) for tf in ("M1", "M5", "M15", "H1", "H4")}
    out = {"version": pol.version, "label": LABEL, "now": int(now_s), "bars": {tf: int(len(b["time"])) for tf, b in B.items()}}
    if min(len(B[tf]["close"]) for tf in B) < 30:
        return {**out, "context": {"direction": "UNKNOWN", "conflict": False}, "primary": None, "directions": {}, "events": [], "funnel": {}}
    t1 = B["M1"]["time"]
    d1 = direction_series(B["H1"]["open"], B["H1"]["high"], B["H1"]["low"], B["H1"]["close"], B["H1"]["time"], "H1")
    d4 = direction_series(B["H4"]["open"], B["H4"]["high"], B["H4"]["low"], B["H4"]["close"], B["H4"]["time"], "H4")
    ctx = align_to(t1.astype(float), "M1", B["H1"]["time"], "H1", d1)
    ctx4 = align_to(t1.astype(float), "M1", B["H4"]["time"], "H4", d4)
    conflict = ((ctx == "UP") & (ctx4 == "DOWN")) | ((ctx == "DOWN") & (ctx4 == "UP"))
    sw15 = zigzag_swings(B["M15"]["high"], B["M15"]["low"], B["M15"]["close"], B["M15"]["time"].astype(float), "M15", k=2.5)
    sw1 = zigzag_swings(B["M1"]["high"], B["M1"]["low"], B["M1"]["close"], t1.astype(float), "M1", k=2.5)
    atr = {tf: atr_fn(B[tf]["high"], B[tf]["low"], B[tf]["close"], 14) for tf in ("M1", "M5", "M15")}
    T1 = t1 + 60
    j5 = np.array([_idx_at(B["M5"]["time"], "M5", int(x)) for x in T1])
    j15 = np.array([_idx_at(B["M15"]["time"], "M15", int(x)) for x in T1])
    res = {}
    for sign in (1, -1):
        M = {tf: (B[tf] if sign == 1 else _mirror(B[tf])) for tf in ("M1", "M5", "M15")}
        pat1 = candle_patterns(M["M1"]["open"], M["M1"]["high"], M["M1"]["low"], M["M1"]["close"], atr["M1"])
        pat5 = candle_patterns(M["M5"]["open"], M["M5"]["high"], M["M5"]["low"], M["M5"]["close"], atr["M5"])
        A = {"m1": M["M1"], "m5": M["M5"], "sw15": sw15 if sign == 1 else _mirror_swings(sw15), "sw1": sw1 if sign == 1 else _mirror_swings(sw1),
             "ctx_ok": (ctx == ("UP" if sign == 1 else "DOWN")) & ~conflict, "pat1": pat1, "pat5": pat5, "atr1": atr["M1"], "atr5": atr["M5"], "atr15": atr["M15"],
             "j5": j5, "j15": j15, "c5": M["M5"]["close"], "l5": M["M5"]["low"]}
        res["BUY" if sign == 1 else "SELL"] = _scan(sign, A, pol, window)
    ctx_last = str(ctx[-1])
    primary = "BUY" if ctx_last == "UP" else "SELL" if ctx_last == "DOWN" else None
    events = sorted(res["BUY"]["events"] + res["SELL"]["events"], key=lambda e: (e["known_at"], e["direction"], e["event_id"]))
    funnel = {}
    for e in events:
        funnel[e["kind"]] = funnel.get(e["kind"], 0) + 1
    return {**out, "context": {"direction": ctx_last, "conflict": bool(conflict[-1]), "h4": str(ctx4[-1])},
            "primary": primary if primary and not bool(conflict[-1]) else None,
            "directions": {k: v["state"] for k, v in res.items()}, "events": events, "funnel": funnel, "atr": {tf: (None if np.isnan(a[-1]) else float(a[-1])) for tf, a in atr.items()}}


def forming_observation(partial: dict | None, atr_m1: float | None, v2: dict) -> dict | None:
    """DISPLAY ONLY: a wick-rejection geometry on the still FORMING M1 bar. Never an event, never logged, never a signal: it is discarded at the bar close and
    only a CLOSED bar that still satisfies the definition becomes an event."""
    if not partial or atr_m1 is None or not v2.get("primary"):
        return None
    st = v2["directions"].get(v2["primary"], {})
    if st.get("stage") not in ("WATCHING_ZONE", "M5_CONFIRMED_AWAITING_M1"):
        return None
    sign = 1 if v2["primary"] == "BUY" else -1
    o, h, l, c = (np.array([sign * partial["open"]]), np.array([sign * (partial["high"] if sign == 1 else partial["low"])]),
                  np.array([sign * (partial["low"] if sign == 1 else partial["high"])]), np.array([sign * partial["close"]]))
    pin = candle_patterns(o, h, l, c, np.array([atr_m1]))["pin_bull"][0]
    if not pin:
        return None
    return {"direction": v2["primary"], "candidate": "FORMING_REJECTION_CANDIDATE", "confirmed": False,
            "note": "unconfirmed: the bar is still forming and may disappear; it is not a trigger until the CLOSED bar satisfies the definition and the M5 confirmation exists"}
