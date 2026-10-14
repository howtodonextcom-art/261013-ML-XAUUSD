"""Setup lifecycle state machine (policy `setup-1`): Multi-Timeframe Trend Pullback + relevant zone + price-action confirmation.

States (non-terminal): SETUP_FORMING -> PULLBACK_IN_PROGRESS -> AT_RELEVANT_ZONE -> AWAITING_CONFIRMATION -> CONFIRMED ->
ENTRY_WINDOW <-> ENTRY_ELIGIBLE. Terminal: INVALIDATED, MISSED, EXPIRED. (NO_SETUP = no active setup. BLOCKED belongs to the P5 gate.)

The machine is a pure function of closed bars: the state after bar j depends only on bars <= j (tested: prefix == full). It emits an
EVENT only when a setup changes state, so consecutive bars of the same situation never create duplicate setups; every setup has a
stable `setup_id` derived from the impulse leg it belongs to.

SELL is the exact mirror of BUY: prices are negated (high <-> low) and the BUY logic runs on the mirrored series.

All thresholds live in SetupPolicy (initial design parameters, derived from the definitions, NOT tuned on outcomes).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..indicators import atr as atr_fn
from ..structure import Swing, TF_SEC
from .patterns import candle_patterns
from .zones import Zone, build_zones

SETUP_VERSION = "setup-1"
WAIT = ("NO_DIRECTION", "NO_VALID_IMPULSE", "NO_RELEVANT_ZONE", "AWAITING_PULLBACK", "PULLBACK_IN_PROGRESS", "AWAITING_CONFIRMATION", "SIGNAL_CONFLICT",
        "ENTRY_WINDOW_NOT_OPEN", "INSUFFICIENT_HISTORY", "DATA_STALE")
NEXT_EVENT = {
    "SETUP_FORMING": "price retraces at least pullback_min ATR below the impulse high",
    "PULLBACK_IN_PROGRESS": "price reaches a relevant support zone without closing below the impulse start",
    "AT_RELEVANT_ZONE": "a bullish confirmation bar (pin bar / engulfing / strong close) closes at the zone",
    "AWAITING_CONFIRMATION": "a bullish confirmation bar closes at the zone before the confirmation window ends",
    "CONFIRMED": "the entry window opens on the next closed bar",
    "ENTRY_WINDOW": "price returns within the entry band of the planned entry before the window ends",
    "ENTRY_ELIGIBLE": "entry decision (risk gate) while price stays inside the band and above the invalidation level",
}
NEXT_EVENT_SELL = {                                  # the SELL setup is the exact mirror: the wording must mirror too (a BUY sentence on a SELL setup misleads)
    "SETUP_FORMING": "price retraces at least pullback_min ATR above the impulse low",
    "PULLBACK_IN_PROGRESS": "price reaches a relevant resistance zone without closing above the impulse start",
    "AT_RELEVANT_ZONE": "a bearish confirmation bar (pin bar / engulfing / strong close) closes at the zone",
    "AWAITING_CONFIRMATION": "a bearish confirmation bar closes at the zone before the confirmation window ends",
    "CONFIRMED": "the entry window opens on the next closed bar",
    "ENTRY_WINDOW": "price returns within the entry band of the planned entry before the window ends",
    "ENTRY_ELIGIBLE": "entry decision (risk gate) while price stays inside the band and below the invalidation level",
}


@dataclass(frozen=True)
class SetupPolicy:
    version: str = SETUP_VERSION
    min_impulse_atr: float = 1.5      # impulse leg (swing low -> swing high) must be at least this many ATR
    pullback_min_atr: float = 0.5     # retracement from the impulse high that counts as a pullback
    zone_merge_atr: float = 0.5
    zone_pad_atr: float = 0.25
    zone_min_touches: int = 2
    confirm_window_bars: int = 5      # bars after the zone touch in which a confirmation bar is accepted
    invalid_buffer_atr: float = 0.25  # close below zone low minus this => zone failed; also the SL buffer of the invalidation level
    entry_window_bars: int = 4
    entry_band_atr: float = 0.25      # price within this distance above the planned entry => ENTRY_ELIGIBLE
    max_chase_atr: float = 1.0        # price this far above the planned entry before ever being eligible => MISSED
    max_setup_age_bars: int = 60      # counted from the bar at which the impulse high became known
    max_impulse_age_bars: int = 20    # a setup is only created while the impulse high was confirmed at most this many bars ago
    require_zone: bool = True         # False = ablation C5 only: a pattern bar after the pullback starts confirms, its own range is the pseudo-zone


POLICY = SetupPolicy()


@dataclass
class _Active:
    setup_id: str
    created_idx: int
    sh: Swing
    sl: Swing
    sign: int = 1                     # +1 BUY view, -1 SELL view: evidence strings are printed in REAL prices
    state: str = "NO_SETUP"
    zone: object = None
    touch_idx: int | None = None
    entry_level: float | None = None
    invalidation: float | None = None
    window_end: int | None = None
    chase_limit: float | None = None
    band: float | None = None
    ever_eligible: bool = False
    confirm_idx: int | None = None
    evidence: list = field(default_factory=list)


def _mirror_swings(sw: list[Swing]) -> list[Swing]:
    return [Swing("L" if s.kind == "H" else "H", s.idx, s.known_idx, -s.price, s.formed_at, s.known_at, s.source_timeframe, s.window_start_artifact) for s in sw]


def _run_dir(o, h, l, c, t, tf, atr, swings, ctx_ok, conflict, pol: SetupPolicy, sign: int, patterns_any, evaluated_at) -> list[dict]:
    """BUY logic on (possibly mirrored) arrays; `sign` maps prices back (+1 BUY view, -1 SELL view)."""
    n = len(c)
    sec = TF_SEC[tf]
    direction = "BUY" if sign == 1 else "SELL"
    sw_sorted = sorted((s for s in swings if not s.window_start_artifact), key=lambda s: (s.known_idx, s.idx, s.kind))
    known: list[Swing] = []
    si = 0
    events: list[dict] = []
    used: set[tuple] = set()
    act: _Active | None = None

    def px(v):          # price back to the real (un-mirrored) scale
        return None if v is None else float(sign * v)

    def emit(j, state, reasons, a=None, extra=None):
        nonlocal act
        a = a or act
        prev = None if a.state == "NO_SETUP" else a.state
        a.state = state
        z = a.zone
        ev = {"setup_id": a.setup_id, "direction": direction, "setup_timeframe": tf, "state": state, "prev_state": prev, "bar_idx": j,
              "event_time": int(t[j]), "known_at": int(t[j]) + sec, "evaluated_at": evaluated_at if evaluated_at is not None else int(t[j]) + sec,
              "reasons": list(reasons), "evidence": list(a.evidence), "policy_version": pol.version,
              "impulse": {"start_price": px(a.sl.price), "high_price": px(a.sh.price), "high_known_at": a.sh.known_at},
              "zone": None if z is None else {"low": px(z.low if sign == 1 else z.high), "high": px(z.high if sign == 1 else z.low),
                                               "touches": z.touches, "zone_id": z.zone_id if sign == 1 else f"Z{-z.center:.2f}"},
              "entry_level": px(a.entry_level), "invalidation_level": px(a.invalidation),
              "next_required_event": (NEXT_EVENT if sign == 1 else NEXT_EVENT_SELL).get(state),
              "expires_at": int(a.sh.known_at) + pol.max_setup_age_bars * sec,                                  # informational: the setup is EXPIRED by the first bar closing after this
              "entry_window_ends_at": None if a.confirm_idx is None else int(t[a.confirm_idx]) + (pol.entry_window_bars + 1) * sec}
        if extra:
            ev.update(extra)
        events.append(ev)

    def terminal(j, state, reason):
        nonlocal act
        emit(j, state, [reason])
        used.add((act.sh.kind, act.sh.idx))
        act = None

    for j in range(n):
        while si < len(sw_sorted) and sw_sorted[si].known_idx <= j:
            known.append(sw_sorted[si])
            si += 1
        a_j = atr[j]
        if np.isnan(a_j):
            continue
        if act is not None and act.created_idx < j:
            s = act
            if j - s.sh.known_idx > pol.max_setup_age_bars:
                terminal(j, "EXPIRED", "SETUP_AGE")
            elif s.state in ("SETUP_FORMING", "PULLBACK_IN_PROGRESS", "AT_RELEVANT_ZONE", "AWAITING_CONFIRMATION") and not ctx_ok[j]:
                terminal(j, "INVALIDATED", "CONTEXT_LOST")
            else:
                _step(j, s, o, h, l, c, a_j, known, pol, patterns_any, emit, terminal)
        if act is None and ctx_ok[j] and not conflict[j]:
            hi = next((x for x in reversed(known) if x.kind == "H"), None)
            if hi is not None and (hi.kind, hi.idx) not in used and c[j] <= hi.price and j - hi.known_idx <= pol.max_impulse_age_bars:
                lo = next((x for x in reversed(known) if x.kind == "L" and x.idx < hi.idx), None)
                if lo is not None and hi.price - lo.price >= pol.min_impulse_atr * a_j:
                    sid = f"{tf}-{direction}-{hi.known_at}-{sign * lo.price:.2f}"
                    act = _Active(sid, j, hi, lo, sign)
                    act.evidence = [f"CONTEXT:higher-timeframe {direction} direction", f"IMPULSE:{(hi.price - lo.price) / a_j:.1f} ATR leg"]
                    emit(j, "SETUP_FORMING", ["IMPULSE_FOUND"], act)
    return events


def _step(j, s: _Active, o, h, l, c, a_j, known, pol, pat_any, emit, terminal):
    """Advance one active setup by one closed bar j (BUY view)."""
    if s.state == "SETUP_FORMING":
        if c[j] > s.sh.price:
            terminal(j, "EXPIRED", "SUPERSEDED_BY_CONTINUATION")
            return
        if s.sh.price - l[j] >= pol.pullback_min_atr * a_j:
            s.evidence.append(f"PULLBACK:{(s.sh.price - l[j]) / a_j:.1f} ATR below the impulse high (real price {s.sign * s.sh.price:.2f} -> {s.sign * l[j]:.2f})")
            emit(j, "PULLBACK_IN_PROGRESS", ["PULLBACK_STARTED"], s)
        else:
            return
    if s.state == "PULLBACK_IN_PROGRESS":
        if c[j] < s.sl.price:
            terminal(j, "INVALIDATED", "STRUCTURE_BROKEN")
            return
        if c[j] > s.sh.price:
            terminal(j, "EXPIRED", "SUPERSEDED_BY_CONTINUATION")
            return
        zones = [z for z in build_zones(known, a_j, pol.zone_merge_atr, pol.zone_pad_atr, pol.zone_min_touches)
                 if z.high < s.sh.price - 0.5 * pol.pullback_min_atr * a_j and z.high >= s.sl.price and l[j] <= z.high and c[j] >= z.low]
        if not zones and not pol.require_zone and pat_any[j]:
            zones = [Zone(float(l[j]), float(h[j]), float((l[j] + h[j]) / 2), 1, 0, j, j)]
        if not zones:
            return                                                    # still pulling back, no relevant zone reached yet (reason NO_RELEVANT_ZONE)
        z = max(zones, key=lambda q: q.high)                          # the first (highest) zone price fell into
        s.zone, s.touch_idx = z, j
        lo_r, hi_r = sorted((s.sign * z.low, s.sign * z.high))
        s.evidence.append(f"ZONE:{z.touches} confirmed swings, [{lo_r:.2f}, {hi_r:.2f}]")
        emit(j, "AT_RELEVANT_ZONE", ["ZONE_TOUCHED"], s)
        if not _confirm(j, s, o, h, l, c, a_j, pol, pat_any, emit):
            emit(j, "AWAITING_CONFIRMATION", ["NO_CONFIRMATION_YET"], s)
        return
    if s.state == "AWAITING_CONFIRMATION":
        z = s.zone
        if c[j] < z.low - pol.invalid_buffer_atr * a_j:
            terminal(j, "INVALIDATED", "ZONE_FAILED")
        elif c[j] > s.sh.price:
            terminal(j, "EXPIRED", "SUPERSEDED_BY_CONTINUATION")
        elif j - s.touch_idx > pol.confirm_window_bars:
            terminal(j, "EXPIRED", "CONFIRMATION_TIMEOUT")
        else:
            _confirm(j, s, o, h, l, c, a_j, pol, pat_any, emit)
        return
    if s.state in ("CONFIRMED", "ENTRY_WINDOW", "ENTRY_ELIGIBLE"):
        if l[j] <= s.invalidation:
            terminal(j, "INVALIDATED", "INVALIDATION_LEVEL_TOUCHED")
            return
        if j > s.window_end:
            terminal(j, "EXPIRED", "ENTRY_WINDOW_ENDED")
            return
        if not s.ever_eligible and h[j] - s.entry_level > s.chase_limit:
            terminal(j, "MISSED", "PRICE_RAN_AWAY")
            return
        want = "ENTRY_ELIGIBLE" if c[j] <= s.entry_level + s.band else "ENTRY_WINDOW"
        if want == "ENTRY_ELIGIBLE":
            s.ever_eligible = True
        if want != s.state:
            emit(j, want, ["PRICE_IN_ENTRY_BAND" if want == "ENTRY_ELIGIBLE" else "WINDOW_OPEN_PRICE_OUTSIDE_BAND"], s)


def _confirm(j, s: _Active, o, h, l, c, a_j, pol, pat_any, emit) -> bool:
    """Confirmation bar at the zone: a bullish pattern whose low stays within the zone area and whose close is back above the zone low."""
    z = s.zone
    # the bar must really be AT the zone: its low reaches into the zone (<= zone high), does not pierce far below it, and it closes back above the zone low
    if not pat_any[j] or l[j] > z.high or l[j] < z.low - pol.zone_pad_atr * a_j or c[j] <= z.low:
        return False
    s.confirm_idx = j
    s.entry_level = float(c[j])
    s.invalidation = float(min(l[j], z.low) - pol.invalid_buffer_atr * a_j)
    s.window_end = j + pol.entry_window_bars
    s.chase_limit = pol.max_chase_atr * a_j
    s.band = pol.entry_band_atr * a_j
    s.evidence.append(f"CONFIRMATION:{'bullish' if s.sign == 1 else 'bearish'} pattern bar closed at {s.sign * c[j]:.2f}")
    emit(j, "CONFIRMED", ["CONFIRMATION_PATTERN_AT_ZONE"], s)
    return True


def run_setups(o, h, l, c, t, tf: str, swings: list[Swing], ctx_dir, ctx_conflict=None, policy: SetupPolicy = POLICY,
               evaluated_at: int | None = None) -> dict:
    """Run both directions over closed bars. `swings` = confirmed zig-zag swings of the setup timeframe; `ctx_dir` = per-bar higher
    timeframe direction ('UP'/'DOWN'/'NONE'/'UNKNOWN'); `ctx_conflict` = per-bar bool (even higher timeframe opposes)."""
    o, h, l, c, t = (np.asarray(v, dtype=float) for v in (o, h, l, c, t))
    n = len(c)
    ctx = np.asarray(ctx_dir, dtype=object)
    conflict_buy = np.zeros(n, dtype=bool) if ctx_conflict is None else np.asarray(ctx_conflict, dtype=bool)
    atr = atr_fn(h, l, c, 14)
    pat = candle_patterns(o, h, l, c, atr)
    ev = _run_dir(o, h, l, c, t, tf, atr, swings, ctx == "UP", conflict_buy, policy, 1, pat["any_bull"], evaluated_at)
    ev += _run_dir(-o, -l, -h, -c, t, tf, atr, _mirror_swings(swings), ctx == "DOWN", conflict_buy, policy, -1, pat["any_bear"], evaluated_at)
    ev.sort(key=lambda e: (e["bar_idx"], e["direction"]))
    return {"events": ev, "policy_version": policy.version, "bars": n}


def current_status(result: dict, n_bars: int, ctx_last: str, conflict_last: bool = False, history_ok: bool = True, stale: bool = False) -> dict:
    """Summary at the last closed bar: the active setup per direction (if any) and one WAIT reason when nothing is eligible."""
    if stale:
        return {"decision_context": "WAIT", "wait_reason": "DATA_STALE", "active": {}}
    if not history_ok or ctx_last == "UNKNOWN":
        return {"decision_context": "WAIT", "wait_reason": "INSUFFICIENT_HISTORY", "active": {}}
    last: dict[str, dict] = {}
    for e in result["events"]:
        last[e["setup_id"]] = e
    active = {e["direction"]: e for e in last.values() if e["state"] not in ("INVALIDATED", "MISSED", "EXPIRED")}
    if len(active) == 2:
        return {"decision_context": "WAIT", "wait_reason": "SIGNAL_CONFLICT", "active": active}
    if active:
        e = next(iter(active.values()))
        reason = {"SETUP_FORMING": "AWAITING_PULLBACK", "PULLBACK_IN_PROGRESS": "NO_RELEVANT_ZONE" if e["zone"] is None else "PULLBACK_IN_PROGRESS",
                  "AT_RELEVANT_ZONE": "AWAITING_CONFIRMATION", "AWAITING_CONFIRMATION": "AWAITING_CONFIRMATION", "CONFIRMED": "ENTRY_WINDOW_NOT_OPEN",
                  "ENTRY_WINDOW": "ENTRY_WINDOW_NOT_OPEN", "ENTRY_ELIGIBLE": None}[e["state"]]
        if reason is None and conflict_last:            # eligible, but an even higher timeframe opposes it right now: no entry readiness
            return {"decision_context": "WAIT", "wait_reason": "SIGNAL_CONFLICT", "active": active}
        return {"decision_context": "ENTRY_ELIGIBLE" if reason is None else "WAIT", "wait_reason": reason, "active": active}
    if conflict_last:
        return {"decision_context": "WAIT", "wait_reason": "SIGNAL_CONFLICT", "active": {}}
    # No active setup. NO_DIRECTION: H1 shows no direction. Otherwise a direction exists but NO qualifying impulse leg is on the books: that is NO_VALID_IMPULSE (before Level 6.2 this
    # was labelled AWAITING_PULLBACK, which wrongly implied that a setup already existed and was waiting for its pullback; AWAITING_PULLBACK now means exactly SETUP_FORMING).
    return {"decision_context": "WAIT", "wait_reason": "NO_DIRECTION" if ctx_last in ("NONE",) else "NO_VALID_IMPULSE", "active": {}}
