"""Glue between stored/live closed bars and the intelligence package. Pure functions (no MT5, no threads, no network): the service in
app.py only feeds them data and publishes the result. The BACKEND is the only place a BUY/SELL/WAIT/BLOCKED decision is made; the
dashboard just displays this record.

compute_heavy : runs when a setup/direction/conflict timeframe bar closes (indicators, structure, setup lifecycle). Uses closed bars only.
make_decision : cheap, runs often with the CURRENT bid/spread/data age: gates and the risk plan are re-evaluated; the setup state is the
                one of the last closed bar (a setup changes state only at bar closes).
Privacy: equity, free margin and any money derived from them never appear in the output (lots, R:R and the risk FRACTION do).
"""
from __future__ import annotations

import os

import numpy as np

from xau_intel.decision.decide import STRATEGY_VERSION, GatePolicy, decide
from xau_intel.decision.risk import RiskPolicy, SymbolSpec
from xau_intel.indicators import atr as atr_fn
from xau_intel.regime_snapshot import MIN_BARS, analyse_snapshot, build_snapshot
from xau_intel.setups.machine import current_status, run_setups
from xau_intel.setups.trend_series import align_to, direction_series
from xau_intel.structure import zigzag_swings

INTEL_VERSION = "intel-1"
MONEY_KEYS = ("risk_budget", "estimated_loss_at_sl", "margin_estimate", "loss_per_lot", "margin_per_lot_estimate")


def _tail(b: dict, n: int) -> dict:
    return {k: np.asarray(v)[-n:] for k, v in b.items()}


def compute_heavy(bars: dict, now_server_s: int, *, setup_tf="M15", dir_tf="H1", conflict_tf="H4", max_setup_bars=3000, max_ctx_bars=5000,
                  recent_events=12) -> dict:
    """bars: tf -> dict(time, open, high, low, close) of CLOSED bars (any further bars are removed by the snapshot rule)."""
    snap = build_snapshot(bars, now_server_s)           # the time filter comes FIRST: any window is cut from bars closed at `now_server_s` only
    analysis = analyse_snapshot(snap)
    sb, db, cb = snap.tfs[setup_tf], snap.tfs[dir_tf], snap.tfs[conflict_tf]
    n = len(sb.close)
    out = {"intel_version": INTEL_VERSION, "evaluated_at": int(now_server_s), "setup_tf": setup_tf, "direction_tf": dir_tf, "conflict_tf": conflict_tf,
           "bars": {tf: len(b.close) for tf, b in snap.tfs.items()}, "analysis": analysis["timeframes"]}
    if n < 2:
        return {**out, "status": {"decision_context": "WAIT", "wait_reason": "INSUFFICIENT_HISTORY", "active": {}}, "market": {"history": "INSUFFICIENT_HISTORY"},
                "atr": None, "setup_events": [], "setup_bar_time": None}
    s0 = max(0, n - max_setup_bars)
    o, h, l, c, t = (np.asarray(x[s0:], dtype=float) for x in (sb.open, sb.high, sb.low, sb.close, sb.time))
    d1 = direction_series(db.open, db.high, db.low, db.close, db.time, dir_tf)
    d4 = direction_series(cb.open, cb.high, cb.low, cb.close, cb.time, conflict_tf)
    ctx = align_to(t, setup_tf, db.time, dir_tf, d1)
    ctx4 = align_to(t, setup_tf, cb.time, conflict_tf, d4)
    conflict = ((ctx == "UP") & (ctx4 == "DOWN")) | ((ctx == "DOWN") & (ctx4 == "UP"))
    sw = zigzag_swings(h, l, c, t, setup_tf, k=2.5)
    res = run_setups(o, h, l, c, t, setup_tf, sw, ctx, ctx_conflict=conflict)
    history_ok = all(len(b.close) >= MIN_BARS for b in (sb, db, cb))
    status = current_status(res, len(c), str(ctx[-1]), bool(conflict[-1]), history_ok)
    a = atr_fn(h, l, c, 14)
    regimes = {tf: v.get("regime") for tf, v in analysis["timeframes"].items()}
    market = {"direction_tf": dir_tf, "direction": str(ctx[-1]), "conflict_tf": conflict_tf, "conflict_direction": str(ctx4[-1]),
              "conflict": bool(conflict[-1]), "regime": regimes, "history": "OK" if history_ok else "INSUFFICIENT_HISTORY"}
    ev = [{k: e[k] for k in ("setup_id", "direction", "state", "prev_state", "known_at", "reasons", "entry_level", "invalidation_level")}
          for e in res["events"][-recent_events:]]
    return {**out, "status": status, "market": market, "atr": None if np.isnan(a[-1]) else float(a[-1]), "setup_events": ev,
            "setup_bar_time": int(t[-1]), "setup_events_total": len(res["events"])}


def reveal_size() -> bool:
    """Size hiding is the DEFAULT (privacy mode): the published plan carries levels and R:R but no lot. Only an explicit operator decision at start-up
    (env XAU_REVEAL_SIZE=1) publishes the lot; there is no per-request switch, so a client can never ask for it."""
    return os.environ.get("XAU_REVEAL_SIZE", "").strip() == "1"


def _sanitize(d: dict | None, reveal: bool | None = None) -> dict | None:
    if d is None:
        return None
    reveal = reveal_size() if reveal is None else reveal
    drop = MONEY_KEYS if reveal else MONEY_KEYS + ("lot",)
    return {k: v for k, v in d.items() if k not in drop}


def strict(o):
    """Recursively replace NaN/Infinity (not valid JSON for the browser) by None and numpy scalars by Python numbers."""
    import math
    if isinstance(o, dict):
        return {k: strict(v) for k, v in o.items()}
    if isinstance(o, np.ndarray):
        o = o.tolist()
    if isinstance(o, (list, tuple)):
        return [strict(v) for v in o]
    if isinstance(o, np.generic):
        o = o.item()
    if isinstance(o, float) and not math.isfinite(o):
        return None
    return o


def make_decision(heavy: dict, *, spread, bid, data_age_s, spec: SymbolSpec | None, equity, free_margin, risk_policy: RiskPolicy, gate_policy: GatePolicy,
                  dataset_version: str = "unknown", now_server_s: int | None = None, extra_gates: list | None = None) -> dict:
    """Decision record for the CURRENT moment from a cached heavy result. Only the public plan is returned (see RiskPlan.public_plan)."""
    sizing = "LIVE_ACCOUNT"
    if not reveal_size():
        # PRIVACY MODE: the research plan is sized on a hypothetical reference account, so the public decision is a pure function of market data. The real
        # equity / free margin are not used at all: no lot, no affordability BLOCKED flip, no margin verdict can reveal them (review Level 5.1).
        equity = free_margin = risk_policy.reference_equity
        sizing = "REFERENCE_ACCOUNT"
    d = decide(heavy["status"], atr=heavy.get("atr"), spread=spread, spec=spec, equity=equity, free_margin=free_margin, data_age_s=data_age_s,
               market_open=True if (data_age_s is not None and data_age_s <= gate_policy.max_data_age_s) else None, price_now_bid=bid,
               market=heavy.get("market"), snapshot_time=heavy.get("evaluated_at") if now_server_s is None else now_server_s,
               dataset_version=dataset_version, risk_policy=risk_policy, gate_policy=gate_policy, extra_gates=extra_gates)
    d = dict(d)
    d["plan"] = _sanitize(d.get("plan"))
    if d["plan"]:
        d["plan"]["risk_fraction"] = risk_policy.risk_fraction
        d["plan"]["size_hidden"] = not reveal_size()
    if d.get("risk") and not reveal_size():
        d["risk"] = {**d["risk"], "warnings": [w for w in d["risk"].get("warnings", []) if not str(w).startswith("LOT_")]}      # a capped lot would reveal a large account
    d["sizing"] = sizing
    d["setup_bar_time"] = heavy.get("setup_bar_time")
    d["session_note"] = "market session is inferred only from tick flow; no calendar is assumed"
    return d


def overlays(decision: dict) -> dict:
    """Chart overlays derived by the backend from the decision (the browser draws them, it never computes them)."""
    if "DATA_STALE" in (decision.get("reasons", {}).get("gate") or []) or decision.get("primary_reason") == "DATA_STALE":
        return {"zone": None, "lines": [], "direction": None}          # a stale decision publishes no levels at all
    s, p = decision.get("setup"), decision.get("plan")
    z = None
    if s:
        z = s.get("zone")
    lines = []
    if p:
        lines = [{"kind": "ENTRY", "price": p["entry"]}, {"kind": "SL", "price": p["stop_loss"]}, {"kind": "TP", "price": p["take_profit"]}]
    elif s and s.get("entry_level") is not None:
        lines = [{"kind": "ENTRY", "price": s["entry_level"]}, {"kind": "SL", "price": s["invalidation_level"]}]
    return {"zone": z, "lines": lines, "direction": s["direction"] if s else None}
