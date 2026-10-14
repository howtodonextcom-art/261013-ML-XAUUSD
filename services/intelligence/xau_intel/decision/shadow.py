"""Paper (shadow) outcome of a research decision. Nothing here touches a broker; it only replays what price did AFTER the decision.

Fill model (no hindsight): the decision is known at the close of bar `decision_idx`; the hypothetical order is filled at the OPEN of the
next bar: BUY at open + spread + slippage (pays the ask), SELL at open - slippage (sells the bid). If that fill is farther than
`max_chase` from the planned entry the trade is NO_FILL (a missed opportunity, never counted as a win).

Exits, on the bid chart like the risk plan: BUY stop when low <= SL (exit at SL minus slippage), BUY target when high >= TP (exit at TP);
SELL stop when high >= SL (exit buys the ask: SL + spread + slippage), SELL target when low <= TP (exit at TP + spread). A bar whose range
touches BOTH levels is INCONCLUSIVE unless a tick path is supplied to order them; `conservative=True` labels it SL_FIRST_CONSERVATIVE
(a distinct label, never merged with SL_FIRST). After `timeout_bars` the position is closed at the bar close (TIMEOUT).

Outcomes: NO_FILL, TP_FIRST, SL_FIRST, SL_FIRST_CONSERVATIVE, TIMEOUT, INCONCLUSIVE, NO_DATA.
`gap_stops=True`: a bar that OPENS beyond the stop (weekend / daily-break gap) exits at that open, not at the stop level. `optimistic_ambiguous=True`
resolves a bar touching both levels as TP first (an upper bound used only for sensitivity, label TP_FIRST_OPTIMISTIC).
`r_multiple` = net price P/L divided by the planned loss distance WITH costs (risk plan `loss_distance_with_costs`); money uses the plan's
value per price unit and lot, minus commission.
"""
from __future__ import annotations

import numpy as np

SHADOW_VERSION = "shadow-1"


def _first_touch_with_ticks(ticks, sign, sl, tp, t0_ms, t1_ms):
    """ticks: iterable of (time_msc, bid) in order. Returns 'SL' / 'TP' / None for the first level touched within [t0_ms, t1_ms)."""
    for ms, bid in ticks:
        if ms < t0_ms:
            continue
        if ms >= t1_ms:
            break
        if sign == 1:
            if bid <= sl:
                return "SL"
            if bid >= tp:
                return "TP"
        else:
            if bid >= sl:
                return "SL"
            if bid <= tp:
                return "TP"
    return None


def simulate_outcome(plan: dict, decision_idx: int, o, h, l, c, spread, *, bar_ms: int | None = None, bar_times_ms=None, ticks=None,
                     timeout_bars: int = 60, max_chase: float | None = None, planned_entry: float | None = None,
                     conservative: bool = False, commission_per_lot: float = 0.0, gap_stops: bool = False,
                     optimistic_ambiguous: bool = False) -> dict:
    """Simulate one paper trade from `plan` (a risk plan dict with direction, stop_loss, take_profit, lot, ...). Arrays are the bars used
    for the simulation (typically M1) and `spread` is a per-bar spread in price units."""
    o, h, l, c, spread = (np.asarray(v, dtype=float) for v in (o, h, l, c, spread))
    n = len(c)
    sign = 1 if plan["direction"] == "BUY" else -1
    sl, tp = float(plan["stop_loss"]), float(plan["take_profit"])
    slip = float(plan.get("slippage_allowance", 0.0))
    r0 = float(plan["loss_distance_with_costs"])
    vpu, lot = float(plan["value_per_price_unit_per_lot"]), float(plan["lot"])
    out = {"outcome": "NO_DATA", "version": SHADOW_VERSION, "decision_idx": decision_idx, "fill_idx": None, "fill_price": None, "exit_idx": None,
           "exit_price": None, "exit_reason": None, "pnl_price": None, "pnl_money": None, "r_multiple": None, "bars_held": None,
           "ambiguous_bars": 0}
    i0 = decision_idx + 1
    if i0 >= n:
        return out
    fill = o[i0] + sign * (spread[i0] + slip) if sign == 1 else o[i0] - slip
    if sign * (fill - sl) <= 0:                                 # the stop is already breached at the fill price: no valid trade exists
        return {**out, "outcome": "NO_FILL", "exit_reason": "FILL_BEYOND_STOP", "fill_price": float(fill)}
    if sign * (tp - fill) <= 0:                                 # the target is already behind the fill price: no reward left
        return {**out, "outcome": "NO_FILL", "exit_reason": "FILL_BEYOND_TARGET", "fill_price": float(fill)}
    ref = planned_entry if planned_entry is not None else plan.get("entry")
    if max_chase is not None and ref is not None and sign * (fill - ref) > max_chase:
        return {**out, "outcome": "NO_FILL", "exit_reason": "CHASE_EXCEEDED", "fill_idx": None, "fill_price": float(fill)}
    out.update(fill_idx=i0, fill_price=float(fill))
    for j in range(i0, min(n, i0 + timeout_bars)):
        if sign == 1:
            hit_sl, hit_tp = l[j] <= sl, h[j] >= tp
        else:
            hit_sl, hit_tp = h[j] >= sl, l[j] <= tp
        if j == i0:
            # the entry bar: price may have touched the levels before the fill moment (open); only the part after the open counts, which
            # bars cannot separate -> treated like any bar (levels are never between the open and the fill by construction)
            pass
        which = None
        if gap_stops and j > i0 and sign * (o[j] - sl) <= 0:        # the market opened beyond the stop: filled at the open (worse than the stop)
            px = o[j] - slip if sign == 1 else o[j] + spread[j] + slip
            return _fill_result(out, sign, j, px, "SL_FIRST", "STOP_LOSS_GAP", r0, vpu, lot, commission_per_lot)
        if hit_sl and hit_tp and optimistic_ambiguous and ticks is None:
            out["ambiguous_bars"] += 1
            return _finish(out, plan, sign, j, "TP", "TP_FIRST_OPTIMISTIC", tp, spread[j], slip, r0, vpu, lot, commission_per_lot, conservative)
        if hit_sl and hit_tp:
            out["ambiguous_bars"] += 1
            if ticks is not None and bar_times_ms is not None:
                which = _first_touch_with_ticks(ticks, sign, sl, tp, bar_times_ms[j], bar_times_ms[j] + (bar_ms or 60_000))
            if which is None:
                return _finish(out, plan, sign, j, None, "SL_FIRST_CONSERVATIVE" if conservative else "INCONCLUSIVE", sl, spread[j], slip, r0, vpu, lot,
                               commission_per_lot, conservative)
        elif hit_sl:
            which = "SL"
        elif hit_tp:
            which = "TP"
        if which == "SL":
            return _finish(out, plan, sign, j, "SL", "SL_FIRST", sl, spread[j], slip, r0, vpu, lot, commission_per_lot, conservative)
        if which == "TP":
            return _finish(out, plan, sign, j, "TP", "TP_FIRST", tp, spread[j], slip, r0, vpu, lot, commission_per_lot, conservative)
    j = min(n, i0 + timeout_bars) - 1
    if j - i0 + 1 < timeout_bars:
        out.update(outcome="INCONCLUSIVE", exit_reason="DATA_ENDED_BEFORE_EXIT", bars_held=j - i0 + 1)
        return out
    px = c[j] if sign == 1 else c[j] + spread[j]               # exit at the close: sell the bid / buy the ask
    return _fill_result(out, sign, j, px, "TIMEOUT", "TIMEOUT", r0, vpu, lot, commission_per_lot)


def _finish(out, plan, sign, j, kind, label, level, spr, slip, r0, vpu, lot, comm, conservative):
    if label == "INCONCLUSIVE":
        out.update(outcome="INCONCLUSIVE", exit_reason="SL_AND_TP_TOUCHED_IN_ONE_BAR_NO_TICK_PATH", exit_idx=j, bars_held=j - out["fill_idx"] + 1)
        return out
    if kind is None or kind == "SL":                           # conservative-by-label also exits at the stop
        px = level - slip if sign == 1 else level + spr + slip
        return _fill_result(out, sign, j, px, label, "STOP_LOSS", r0, vpu, lot, comm)
    px = level if sign == 1 else level + spr
    return _fill_result(out, sign, j, px, label, "TAKE_PROFIT", r0, vpu, lot, comm)


def _fill_result(out, sign, j, exit_px, label, reason, r0, vpu, lot, comm):
    pnl_price = sign * (exit_px - out["fill_price"])
    money = pnl_price * lot * vpu - comm * lot
    pnl_price_net = money / (lot * vpu) if lot * vpu else pnl_price
    out.update(outcome=label, exit_idx=j, exit_price=float(exit_px), exit_reason=reason, pnl_price=float(pnl_price_net), pnl_money=float(money),
               r_multiple=float(pnl_price_net / r0) if r0 else None, bars_held=j - out["fill_idx"] + 1)
    return out
