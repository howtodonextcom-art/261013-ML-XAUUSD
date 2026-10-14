"""Research decision (candidate strategy `cand-1` = setup-1 + risk-1 + gate-1). BUY/SELL/WAIT/BLOCKED are RESEARCH decisions, not broker
orders: `execution_authorized` is always False and nothing here can send, modify or cancel an order.

A BUY/SELL requires ALL of: an active setup in state ENTRY_ELIGIBLE (strategy layer), every gate passing (gate layer: fresh data, market
open, spread, optional daily loss limit) and a risk plan with status OK. There is deliberately NO input for RSI, MACD or EMA crossovers:
an indicator on its own cannot create a decision.

Layers are reported separately and never hide each other:
  market   : higher-timeframe direction / regime / history (why there is or is no direction)
  strategy : where the setup lifecycle stands (what is missing, next required event)
  gate     : data freshness, market session, spread, daily loss, risk plan
If the setup is not eligible, the primary reason is the STRATEGY reason even when a gate also fails (the gate list is still shown).
If the setup is eligible but a gate/risk check fails the action is BLOCKED and `strategy_eligible` stays True.
Stale data never produces a new decision: WAIT / DATA_STALE.
"""
from __future__ import annotations

from dataclasses import dataclass

from .risk import EXECUTION_AUTHORIZED, RISK_VERSION, RiskPolicy, SymbolSpec, plan_trade
from ..setups.machine import SETUP_VERSION

GATE_VERSION = "gate-1"
STRATEGY_VERSION = f"cand-1[{SETUP_VERSION}+{RISK_VERSION}+{GATE_VERSION}]"


@dataclass(frozen=True)
class GatePolicy:
    version: str = GATE_VERSION
    max_spread_atr: float = 0.30            # spread / ATR above this blocks entry
    max_data_age_s: float = 10.0            # older data is stale
    require_market_open: bool = True
    daily_loss_limit_fraction: float | None = None   # None = not configured (never hard-coded; set from a verified programme config)


from ..setups.machine import POLICY as _SETUP_POLICY  # noqa: E402

WAIT_NEXT = {
    "NO_VALID_IMPULSE": f"an impulse leg of at least {_SETUP_POLICY.min_impulse_atr:g} ATR in the H1 direction must form first (setup-1 rule), then a pullback of at least {_SETUP_POLICY.pullback_min_atr:g} ATR",
    "NO_DIRECTION": "the higher timeframe (H1) structure and trend must agree on a direction",
    "AWAITING_PULLBACK": "an impulse leg in the H1 direction, then a pullback of at least 0.5 ATR from its extreme",
    "NO_RELEVANT_ZONE": "price must reach a confirmed support/resistance zone without breaking the impulse start",
    "PULLBACK_IN_PROGRESS": "price must reach a relevant zone without closing beyond the impulse start",
    "AWAITING_CONFIRMATION": "a confirmation bar (pin bar / engulfing / strong close) must close at the zone",
    "ENTRY_WINDOW_NOT_OPEN": "the entry window opens on the next closed bar",
    "SIGNAL_CONFLICT": "the conflicting higher-timeframe directions must resolve",
    "INSUFFICIENT_HISTORY": "more closed bars are needed on every timeframe",
    "DATA_STALE": "fresh data: nothing is evaluated on stale data",
}


def gate_checks(*, atr, spread, data_age_s, market_open, daily_loss_used_fraction, pol: GatePolicy) -> list[str]:
    g = []
    if data_age_s is None or data_age_s > pol.max_data_age_s:
        g.append("DATA_STALE")
    if pol.require_market_open and market_open is not True:
        g.append("MARKET_CLOSED" if market_open is False else "MARKET_SESSION_UNKNOWN")
    if spread is None or atr is None or atr <= 0:
        g.append("SPREAD_OR_ATR_UNKNOWN")
    elif spread / atr > pol.max_spread_atr:
        g.append(f"SPREAD_TOO_WIDE({spread / atr:.2f} ATR > {pol.max_spread_atr})")
    if pol.daily_loss_limit_fraction is not None:
        if daily_loss_used_fraction is None:
            g.append("DAILY_LOSS_UNKNOWN")
        elif daily_loss_used_fraction >= pol.daily_loss_limit_fraction:
            g.append(f"DAILY_LOSS_LIMIT_REACHED({daily_loss_used_fraction:.3f} >= {pol.daily_loss_limit_fraction})")
    return g


def _decide(status: dict, *, atr, spread, spec: SymbolSpec | None, equity, free_margin, data_age_s, market_open, price_now_bid=None,
           daily_loss_used_fraction=None, market: dict | None = None, snapshot_time: int | None = None, dataset_version: str = "unknown",
           risk_policy: RiskPolicy = RiskPolicy(), gate_policy: GatePolicy = GatePolicy(), extra_gates: list | None = None) -> dict:
    """`status` is machine.current_status(...). Returns the decision record (JSON-serialisable). `extra_gates` are additional gate reasons
    supplied by the caller (for example a failed recent-bar fill): they block an eligible setup like any other gate."""
    market = market or {}
    gates = gate_checks(atr=atr, spread=spread, data_age_s=data_age_s, market_open=market_open,
                        daily_loss_used_fraction=daily_loss_used_fraction, pol=gate_policy) + list(extra_gates or [])
    active = status.get("active", {})
    eligible = [e for e in active.values() if e["state"] == "ENTRY_ELIGIBLE"]
    ev = eligible[0] if len(eligible) == 1 else None
    base = {"kind": "RESEARCH_DECISION", "execution_authorized": EXECUTION_AUTHORIZED, "strategy_version": STRATEGY_VERSION,
            "dataset_version": dataset_version, "snapshot_time": snapshot_time, "market": market, "strategy_eligible": ev is not None,
            "reasons": {"market": [], "strategy": [], "gate": list(gates)}, "setup": None, "plan": None, "risk": None}
    for e in ([ev] if ev is not None else list(active.values())[:1]):          # the displayed setup is the one the decision is based on
        base["setup"] = {"setup_id": e["setup_id"], "direction": e["direction"], "state": e["state"], "evidence": e["evidence"],
                         "invalidation_level": e["invalidation_level"], "entry_level": e["entry_level"], "next_required_event": e["next_required_event"],
                         "known_at": e["known_at"], "policy_version": e["policy_version"], "zone": e.get("zone"), "impulse": e.get("impulse"),
                         "expires_at": e.get("expires_at"), "entry_window_ends_at": e.get("entry_window_ends_at")}
        break
    if market.get("history") == "INSUFFICIENT_HISTORY":
        base["reasons"]["market"].append("INSUFFICIENT_HISTORY")
    if "DATA_STALE" in gates:                                      # stale data: no new decision of any kind
        return {**base, "setup": None, "plan": None, "action": "WAIT", "primary_reason": "DATA_STALE", "layer": "gate",     # no levels from stale data
                "reasons": {**base["reasons"], "strategy": [status.get("wait_reason") or "UNKNOWN_WHEN_STALE"]}}
    if len(eligible) > 1 or status.get("wait_reason") == "SIGNAL_CONFLICT":
        base["reasons"]["strategy"].append("SIGNAL_CONFLICT")
        return {**base, "action": "WAIT", "primary_reason": "SIGNAL_CONFLICT", "layer": "strategy"}
    if ev is None:                                                 # setup not eligible: the STRATEGY reason is primary, gates only listed
        reason = status.get("wait_reason") or "NO_DIRECTION"
        layer = "market" if reason in ("NO_DIRECTION", "INSUFFICIENT_HISTORY") else "strategy"
        base["reasons"][layer].append(reason)
        return {**base, "action": "WAIT", "primary_reason": reason, "layer": layer}
    direction = ev["direction"]
    target = ev["impulse"]["high_price"]                           # structure target: the impulse extreme in the trade direction
    entry = price_now_bid if price_now_bid is not None else ev["entry_level"]
    rp = plan_trade(direction, entry, ev["invalidation_level"], target, atr, spread, spec, equity, free_margin, risk_policy)
    base["risk"] = {"status": rp.status, "reasons": rp.reasons, "warnings": rp.warnings}
    base["plan"] = rp.public_plan() or None          # never the full plan: see RiskPlan.public_plan
    block = list(gates) + ([f"RISK:{r}" for r in rp.reasons] if rp.status != "OK" else [])
    if block:
        base["reasons"]["gate"] = block
        if base["plan"]:
            base["plan"] = {k: v for k, v in base["plan"].items() if k != "lot"}       # hypothetical levels only: no size for a decision that is not eligible
        return {**base, "action": "BLOCKED", "primary_reason": block[0], "layer": "gate"}
    base["reasons"]["strategy"].append("ENTRY_ELIGIBLE")
    return {**base, "action": direction, "primary_reason": "ENTRY_ELIGIBLE", "layer": "strategy"}


GATE_NEXT = (                                            # (prefix of the primary reason, what must change)
    ("SPREAD_TOO_WIDE", "the spread must fall back below the limit (fraction of ATR)"),
    ("MARKET_CLOSED", "the market must reopen (ticks must flow)"),
    ("MARKET_SESSION_UNKNOWN", "fresh ticks must confirm the market is open"),
    ("DAILY_LOSS", "the daily loss limit blocks new decisions"),
    ("BAR_HISTORY_FILL_FAILED", "the recent-bar history fill must succeed"),
    ("SPREAD_OR_ATR_UNKNOWN", "spread and ATR must be known"),
    ("RISK:RR_TOO_LOW", "price must offer at least the minimum net reward-to-risk after costs"),
    ("RISK:SL_TOO_CLOSE", "the stop must be at least the broker stops level away"),
    ("RISK:INSUFFICIENT_MARGIN", "free margin must cover the position"),
    ("RISK:RISK_MIN_LOT_EXCEEDS_BUDGET", "the minimum lot must fit the per-trade risk budget"),
    ("RISK:", "the risk plan must become valid"),
)


def decide(status: dict, **kw) -> dict:
    """Decision record + `next_required`: the condition whose change would move the decision on (a gate fix for BLOCKED, the setup's own next
    event for a WAIT with a setup, the WAIT reason's condition otherwise; SIGNAL_CONFLICT always names the conflict, not the setup)."""
    d = _decide(status, **kw)
    st, pr = d.get("setup"), str(d.get("primary_reason"))
    if d["action"] in ("BUY", "SELL"):
        d["next_required"] = "decision only: no order is sent; the paper plan is hypothetical"
    elif d["action"] == "BLOCKED":
        d["next_required"] = next((v for k, v in GATE_NEXT if pr.startswith(k)), "the failed gate must clear")
    elif pr in ("SIGNAL_CONFLICT", "DATA_STALE") or not st:
        d["next_required"] = WAIT_NEXT.get(pr)
    else:
        d["next_required"] = st.get("next_required_event") or WAIT_NEXT.get(pr)
    return d
