"""Deterministic point-in-time replay (P6). Pure functions over arrays of CLOSED bars: no MT5, no store, no clock, no randomness
(except seeded generators passed in explicitly).

Pipeline (the same code paths as the live product): zig-zag swings -> setup-1 lifecycle -> status at the decision bar -> `decide()`
(gate-1 + risk-1) -> shadow-1 fill/exit simulation on M5 bars. A decision is made at the CLOSE of an M15 bar and filled at the OPEN of the
M5 bar that starts at that close. See docs/research/BACKTEST_IMPLEMENTATION_CLARIFICATIONS.md (frozen before any run).
"""
from __future__ import annotations

import hashlib
import json

import numpy as np

from ..decision.decide import GatePolicy, decide, gate_checks
from ..decision.risk import RiskPolicy, SymbolSpec, plan_trade
from ..decision.shadow import simulate_outcome
from ..indicators import atr as atr_fn
from ..setups.machine import SetupPolicy, current_status, run_setups
from ..setups.trend_series import align_to, direction_series
from ..structure import TF_SEC, zigzag_swings

ENGINE_VERSION = "replay-1"
HYP_EQUITY = 100_000.0
# measured on MetaQuotes-Demo XAUUSD (docs/qa, tests/unit/test_risk.py): contract 100, value 100 per 1.00 per lot, step 0.01, stops level 600 points
XAU_SPEC = SymbolSpec("XAUUSD", 0.01, 0.1, 100.0, 0.01, 100.0, 0.01, 0.01, 100.0, 600, 100.0, None, None)
RISK = RiskPolicy(risk_fraction=0.005, min_net_rr=1.5, slippage_spread_mult=0.5, commission_per_lot=0.0)
GATE = GatePolicy()
TIMEOUT_M5 = 288
CHASE_ATR = 1.0
M5 = 300
# name -> (slippage USD/oz per side, commission USD per lot round turn)
# the 3rd value is a SPREAD FLOOR in USD/oz (0 = recorded spread only): the stored M5 spread is often 0.04 or 0.00 (docs/research/BACKTEST_REPORT_DEVVAL.md), so fixed-spread sensitivity is mandatory
COSTS = {"base": (0.1, 0.0, 0.0), "slip0": (0.0, 0.0, 0.0), "slip0.3": (0.3, 0.0, 0.0), "comm7": (0.1, 7.0, 0.0), "spread0.2": (0.1, 0.0, 0.2), "spread0.4": (0.1, 0.0, 0.4)}
_FLOORED: dict = {}


def _spread_array(m5: dict, floor: float):
    if not floor:
        return m5["spread"]
    k = (id(m5["spread"]), floor)
    if k not in _FLOORED:
        _FLOORED.clear()
        _FLOORED[k] = np.maximum(m5["spread"], floor)
    return _FLOORED[k]


def canon(o) -> str:
    """Canonical JSON: sorted keys, finite numbers only; the hash of this is the determinism fingerprint."""
    def f(v):
        if isinstance(v, np.generic):
            return v.item()
        if isinstance(v, (np.ndarray,)):
            return v.tolist()
        raise TypeError(type(v))
    return json.dumps(o, sort_keys=True, default=f, allow_nan=False, separators=(",", ":"))


def digest(o) -> str:
    return hashlib.sha256(canon(o).encode()).hexdigest()


def setup_run(bars: dict, policy: SetupPolicy = SetupPolicy(), setup_tf="M15", dir_tf="H1", conflict_tf="H4") -> dict:
    """Run the setup lifecycle over closed bars (`bars[tf]` = dict time/open/high/low/close; time = bar OPEN time, server epoch seconds)."""
    sb, db, cb = bars[setup_tf], bars[dir_tf], bars[conflict_tf]
    o, h, l, c, t = (np.asarray(sb[k], dtype=float) for k in ("open", "high", "low", "close", "time"))
    d1 = direction_series(db["open"], db["high"], db["low"], db["close"], db["time"], dir_tf)
    d4 = direction_series(cb["open"], cb["high"], cb["low"], cb["close"], cb["time"], conflict_tf)
    ctx = align_to(t, setup_tf, db["time"], dir_tf, d1)
    ctx4 = align_to(t, setup_tf, cb["time"], conflict_tf, d4)
    conflict = ((ctx == "UP") & (ctx4 == "DOWN")) | ((ctx == "DOWN") & (ctx4 == "UP"))
    sw = zigzag_swings(h, l, c, t, setup_tf, k=2.5)
    res = run_setups(o, h, l, c, t, setup_tf, sw, ctx, ctx_conflict=conflict, policy=policy)
    return {"res": res, "ctx": ctx, "ctx4": ctx4, "conflict": conflict, "atr": atr_fn(h, l, c, 14), "o": o, "h": h, "l": l, "c": c, "t": t,
            "setup_tf": setup_tf, "dir_tf": dir_tf, "conflict_tf": conflict_tf, "swings": sw, "dir_series": d1}


def last_closed_m5(m5t: np.ndarray, close_time: int) -> int:
    """Index of the last M5 bar fully closed at `close_time` (its open + 300 <= close_time); -1 if none."""
    return int(np.searchsorted(m5t, close_time - M5, side="right")) - 1


def spread_at(m5: dict, close_time: int, max_age_s: int = 2 * M5) -> float | None:
    """Spread (price units) of the last closed M5 bar, None when that bar is older than `max_age_s` (no fresh spread known)."""
    i = last_closed_m5(m5["time"], close_time)
    if i < 0 or close_time - (m5["time"][i] + M5) > max_age_s:
        return None
    return float(m5["spread"][i])


def sim_trade(plan: dict, close_time: int, m5: dict, atr_value: float, cost: tuple[float, float], *, optimistic: bool = False) -> dict:
    """Fill at the open of the M5 bar that starts exactly at `close_time` and walk forward. `plan` needs direction/entry/stop_loss/take_profit/
    stop_distance/spread/lot. Returns the shadow outcome plus `r` (net price P/L / planned structural stop distance) or None when dropped."""
    slip, comm, *rest = cost
    floor = rest[0] if rest else 0.0
    m5t = m5["time"]
    di = last_closed_m5(m5t, close_time)
    i0 = di + 1
    if i0 >= len(m5t) or int(m5t[i0]) != int(close_time):
        return {"outcome": "NO_FILL", "exit_reason": "NO_BAR_AT_FILL", "r": None}
    p2 = {**plan, "slippage_allowance": slip, "value_per_price_unit_per_lot": 100.0}
    out = simulate_outcome(p2, di, m5["open"], m5["high"], m5["low"], m5["close"], _spread_array(m5, floor), timeout_bars=TIMEOUT_M5,
                           max_chase=CHASE_ATR * atr_value, planned_entry=plan["entry"], conservative=True, commission_per_lot=comm,
                           gap_stops=True, optimistic_ambiguous=optimistic, ask_side_stops=True)
    out["r"] = None if out.get("pnl_price") is None else float(out["pnl_price"]) / float(plan["stop_distance"])
    out["fill_time"] = None if out.get("fill_idx") is None else int(m5t[out["fill_idx"]])
    out["exit_time"] = None if out.get("exit_idx") is None else int(m5t[out["exit_idx"]]) + M5
    return out


def eligible_decisions(sr: dict, m5: dict, *, dataset_version: str, rp: RiskPolicy = RISK, gp: GatePolicy = GATE, spec: SymbolSpec = XAU_SPEC) -> list[dict]:
    """One decision record per setup at its FIRST ENTRY_ELIGIBLE event, built with the real decide() (status computed from events <= that bar)."""
    ev = sr["res"]["events"]
    first: dict[str, dict] = {}
    for e in ev:
        if e["state"] == "ENTRY_ELIGIBLE" and e["setup_id"] not in first:
            first[e["setup_id"]] = e
    out = []
    for sid, e in sorted(first.items(), key=lambda kv: (kv[1]["bar_idx"], kv[1]["direction"])):
        j = e["bar_idx"]
        close = int(e["known_at"])
        status = current_status({"events": [x for x in ev if x["bar_idx"] <= j]}, j + 1, str(sr["ctx"][j]), bool(sr["conflict"][j]), True)
        sp = spread_at(m5, close)
        d = decide(status, atr=float(sr["atr"][j]), spread=sp, spec=spec, equity=HYP_EQUITY, free_margin=HYP_EQUITY, data_age_s=0.0, market_open=True,
                   price_now_bid=float(sr["c"][j]), market={"direction": str(sr["ctx"][j])}, snapshot_time=close, dataset_version=dataset_version,
                   risk_policy=rp, gate_policy=gp)
        out.append({"setup_id": sid, "bar_idx": j, "decision_time": close, "atr": float(sr["atr"][j]), "decision": d})
    return out


def plan_direct(direction: str, entry: float, sl: float, tp: float, atr_value: float, spread: float | None, *, rp: RiskPolicy = RISK,
                gp: GatePolicy = GATE, spec: SymbolSpec = XAU_SPEC) -> tuple[dict | None, str]:
    """Gate-1 + risk-1 for the candidates that do not come from a setup (C1, C3). Returns (public plan or None, reason)."""
    g = gate_checks(atr=atr_value, spread=spread, data_age_s=0.0, market_open=True, daily_loss_used_fraction=None, pol=gp)
    if g:
        return None, "GATE:" + g[0].split("(")[0]
    p = plan_trade(direction, entry, sl, tp, atr_value, spread, spec, HYP_EQUITY, HYP_EQUITY, rp)
    if p.status != "OK":
        return None, "RISK:" + (p.reasons[0].split(":")[0] if p.reasons else p.status)
    return p.public_plan(), "OK"


def run_trades(decisions: list[dict], m5: dict, *, direction_filter: str | None = None) -> tuple[list[dict], dict]:
    """decisions: list of {setup_id, decision_time, atr, plan(public)|None, direction, reason}. Applies: BLOCKED/WAIT skipped (counted), one open
    position at a time (occupancy from the BASE-cost simulation), NO_FILL and DATA_ENDED dropped (counted). All cost levels are simulated for
    the same trade set. Returns (trades, counters)."""
    cnt: dict[str, int] = {}

    def bump(k):
        cnt[k] = cnt.get(k, 0) + 1
    trades = []
    busy_until = -1
    for d in sorted(decisions, key=lambda x: (x["decision_time"], x["setup_id"])):
        if d["plan"] is None:
            bump(f"NOT_TRADED:{d['reason']}")
            continue
        if direction_filter and d["direction"] != direction_filter:
            bump("FILTERED_DIRECTION")
            continue
        if d["decision_time"] < busy_until:
            bump("SKIPPED_POSITION_OPEN")
            continue
        sims = {k: sim_trade(d["plan"], d["decision_time"], m5, d["atr"], c) for k, c in COSTS.items()}
        b = sims["base"]
        if b["outcome"] == "NO_FILL":
            bump(f"NO_FILL:{b['exit_reason']}")
            continue
        if b["outcome"] in ("INCONCLUSIVE", "NO_DATA") or b["r"] is None:
            bump(f"DROPPED:{b['outcome']}:{b.get('exit_reason')}")
            continue
        opt = sim_trade(d["plan"], d["decision_time"], m5, d["atr"], COSTS["base"], optimistic=True)
        busy_until = b["exit_time"]
        trades.append({"setup_id": d["setup_id"], "direction": d["direction"], "decision_time": int(d["decision_time"]), "fill_time": b["fill_time"],
                       "exit_time": b["exit_time"], "entry": d["plan"]["entry"], "sl": d["plan"]["stop_loss"], "tp": d["plan"]["take_profit"],
                       "stop_distance": d["plan"]["stop_distance"], "net_rr_plan": d["plan"].get("net_rr"), "outcome": b["outcome"], "exit_reason": b["exit_reason"],
                       "bars_held": b["bars_held"], "ambiguous_bars": b["ambiguous_bars"], "fill_price": b["fill_price"], "exit_price": b["exit_price"],
                       "r": {k: (None if v["r"] is None else round(v["r"], 10)) for k, v in sims.items()}, "r_optimistic": None if opt["r"] is None else round(opt["r"], 10),
                       "regime": d.get("regime")})
    return trades, cnt


def decisions_from_setup(sr: dict, m5: dict, dataset_version: str, **kw) -> list[dict]:
    """Adapter: setup decisions -> the generic form of run_trades."""
    out = []
    for r in eligible_decisions(sr, m5, dataset_version=dataset_version, **kw):
        d = r["decision"]
        ok = d["action"] in ("BUY", "SELL") and d.get("plan")
        out.append({"setup_id": r["setup_id"], "decision_time": r["decision_time"], "atr": r["atr"], "direction": (d.get("setup") or {}).get("direction"),
                    "plan": d["plan"] if ok else None, "reason": ":".join(str(d["primary_reason"]).split(":")[:2]).split("(")[0].strip(), "action": d["action"], "regime": (d.get("market") or {}).get("direction")})
    return out
