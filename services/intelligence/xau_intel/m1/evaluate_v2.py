"""Forward evaluation of the V2 shadow log (protocol: docs/research/M1_ENTRY_V2_PREREGISTRATION.md, frozen). Pure functions: no store, no clock.

The evaluation is REFUSED (status INSUFFICIENT_EVIDENCE, no price is read, no statistic computed) until BOTH hold: at least `MIN_TRIGGERS` triggered events AND at
least `MIN_DAYS` days since the registration commit. Only then are outcomes simulated, on bars that did not exist at registration, with the frozen rules:
entry at the OPEN of the M1 bar after the trigger bar (shadow-1: BUY pays the ask, SELL sells the bid, SELL stops on the ask, gap-aware stops, conservative same-bar
ordering), SL = extreme/zone edge -/+ 0.25 ATR5, TP = V1 impulse extreme when one was active at the trigger else 2R, risk-1 + gate-1 on the reference account,
timeout 288 M1 bars, one open position per direction. Verdict: SHOWS_EVIDENCE only if every frozen criterion holds; never a profitability claim.
"""
from __future__ import annotations

import numpy as np

from ..backtest.engine import COSTS, plan_direct
from ..backtest.stats import day_bootstrap, summarize
from ..decision.shadow import simulate_outcome
from .entry_v2 import POLICY

MIN_TRIGGERS = 100
MIN_DAYS = 30
TIMEOUT_M1 = 288
N_SEEDS = 500
DAY = 86400


def triggers_of(events: list[dict]) -> list[dict]:
    seen, out = set(), []
    for e in sorted(events, key=lambda x: (x["known_at"], x["event_id"])):
        if e.get("stage") == "M1_TRIGGERED" and e.get("kind") != "WINDOW_STATE" and e["event_id"] not in seen:
            seen.add(e["event_id"])
            out.append(e)
    return out


def gate(events: list[dict], now_ts: int, registration_ts: int) -> dict | None:
    """None when the evaluation may run, else the INSUFFICIENT_EVIDENCE record (nothing else is computed)."""
    n = len(triggers_of(events))
    days = (now_ts - registration_ts) / DAY
    if n < MIN_TRIGGERS or days < MIN_DAYS:
        return {"status": "INSUFFICIENT_EVIDENCE", "triggers": n, "days_since_registration": round(days, 2), "needs": f">= {MIN_TRIGGERS} triggers AND >= {MIN_DAYS} days",
                "performance_claim": "NONE"}
    return None


def plan_for(e: dict, spread: float | None, risk_policy=None, gate_policy=None):
    sign = 1 if e["direction"] == "BUY" else -1
    a5 = float(e["atr5"])
    entry = float(e["trigger_close"])
    edge = e["zone"]["low"] if sign == 1 else e["zone"]["high"]
    ext = float(e["trigger_low"])
    sl = (min(ext, edge) - POLICY.sl_buffer_atr5 * a5) if sign == 1 else (max(ext, edge) + POLICY.sl_buffer_atr5 * a5)
    v1 = e.get("v1_target")
    tp = float(v1) if v1 is not None and sign * (float(v1) - entry) > 0 else entry + sign * POLICY.tp_rr * abs(entry - sl)
    kw = {} if risk_policy is None else {"rp": risk_policy, "gp": gate_policy}
    return plan_direct(e["direction"], entry, sl, tp, a5, spread, **kw)


def _sim(plan, i_trigger, m1, cost, optimistic=False):
    slip, comm, floor = cost
    sp = np.maximum(m1["spread"], floor) if floor else m1["spread"]
    p2 = {**plan, "slippage_allowance": slip, "value_per_price_unit_per_lot": 100.0}
    out = simulate_outcome(p2, i_trigger, m1["open"], m1["high"], m1["low"], m1["close"], sp, timeout_bars=TIMEOUT_M1, max_chase=plan["stop_distance"], planned_entry=plan["entry"],
                           conservative=True, commission_per_lot=comm, gap_stops=True, ask_side_stops=True, optimistic_ambiguous=optimistic)
    r = None if out.get("pnl_price") is None else float(out["pnl_price"]) / float(plan["stop_distance"])
    return out, r


def run_trades(events: list[dict], m1: dict) -> tuple[list[dict], dict]:
    """m1: dict(time, open, high, low, close, spread in price units), sorted. Returns (trades, counters)."""
    t = np.asarray(m1["time"], dtype=np.int64)
    cnt: dict[str, int] = {}
    busy = {"BUY": -1, "SELL": -1}
    trades = []
    for e in triggers_of(events):
        i = int(np.searchsorted(t, e["bar_time"]))
        if i >= len(t) or int(t[i]) != int(e["bar_time"]):
            cnt["NO_BAR"] = cnt.get("NO_BAR", 0) + 1
            continue
        if e["known_at"] < busy[e["direction"]]:
            cnt["SKIPPED_POSITION_OPEN"] = cnt.get("SKIPPED_POSITION_OPEN", 0) + 1
            continue
        plan, why = plan_for(e, float(m1["spread"][i]))
        if plan is None:
            k = "NOT_TRADED:" + why
            cnt[k] = cnt.get(k, 0) + 1
            continue
        sims = {k: _sim(plan, i, m1, c) for k, c in COSTS.items()}
        base, rb = sims["base"]
        if base["outcome"] in ("NO_FILL", "NO_DATA", "INCONCLUSIVE") or rb is None:
            k = f"NOT_COUNTED:{base['outcome']}"
            cnt[k] = cnt.get(k, 0) + 1
            continue
        busy[e["direction"]] = int(t[base["exit_idx"]]) + 60
        trades.append({"event_id": e["event_id"], "direction": e["direction"], "kind": e["kind"], "decision_time": int(e["known_at"]), "exit_time": busy[e["direction"]],
                       "stop_distance": plan["stop_distance"], "target_distance": abs(plan["take_profit"] - plan["entry"]), "outcome": base["outcome"],
                       "r": {k: (None if v[1] is None else round(v[1], 10)) for k, v in sims.items()}})
    return trades, cnt


def random_comparator(trades: list[dict], m1: dict, lo: int, hi: int, seeds: int = N_SEEDS, seed0: int = 20261014) -> list[float]:
    """B2: per seed one random M1 entry (random direction) per V2 trade with the SAME stop/target distances; mean R of each seed."""
    t = np.asarray(m1["time"], dtype=np.int64)
    ia, ib = int(np.searchsorted(t, lo)), int(np.searchsorted(t, hi - TIMEOUT_M1 * 60))
    out = []
    if not trades or ib - ia < 10:
        return out
    for k in range(seeds):
        rng = np.random.default_rng(seed0 + k)
        rs = []
        for tr in trades:
            i = int(rng.integers(ia, ib))
            sg = 1 if rng.random() < 0.5 else -1
            entry = float(m1["close"][i])
            plan, _ = plan_direct("BUY" if sg == 1 else "SELL", entry, entry - sg * tr["stop_distance"], entry + sg * tr["target_distance"], tr["stop_distance"] / 1.5, float(m1["spread"][i]))
            if plan is None:
                continue
            _, r = _sim(plan, i, m1, COSTS["base"])
            if r is not None:
                rs.append(r)
        if rs:
            out.append(float(np.mean(rs)))
    return out


def evaluate(events: list[dict], m1: dict, now_ts: int, registration_ts: int) -> dict:
    g = gate(events, now_ts, registration_ts)
    if g is not None:
        return g                                                       # refused: nothing below is computed, no bar is read
    trades, cnt = run_trades(events, m1)
    res = {"status": "EVALUATED", "triggers": len(triggers_of(events)), "trades": len(trades), "counters": cnt, "base": summarize(trades), "bootstrap": day_bootstrap(trades, "base"),
           "costs": {k: summarize(trades, k).get("mean_r") for k in COSTS}, "bootstrap_slip0.3": day_bootstrap(trades, "slip0.3"), "bootstrap_spread0.4": day_bootstrap(trades, "spread0.4")}
    lo, hi = registration_ts, now_ts
    b2 = random_comparator(trades, m1, lo, hi)
    mean = res["base"].get("mean_r")
    res["b2_random"] = {"seeds": len(b2), "p95": float(np.percentile(b2, 95)) if b2 else None, "v2_above_p95": bool(b2 and mean is not None and mean > np.percentile(b2, 95))}
    # chronological quarters of the forward period and weekly concentration
    q = []
    if trades:
        edges = np.linspace(min(x["decision_time"] for x in trades), max(x["decision_time"] for x in trades) + 1, 5)
        for a, b in zip(edges[:-1], edges[1:]):
            sub = [x for x in trades if a <= x["decision_time"] < b]
            q.append(summarize(sub).get("mean_r") if sub else None)
        weeks: dict = {}
        for x in trades:
            weeks[x["decision_time"] // (7 * DAY)] = weeks.get(x["decision_time"] // (7 * DAY), 0.0) + x["r"]["base"]
        tot = sum(abs(v) for v in weeks.values())
        res["max_week_share"] = None if tot == 0 else max(abs(v) for v in weeks.values()) / tot
    res["quarters_mean_r"] = q
    ok = (res["trades"] >= MIN_TRIGGERS and (mean or -1) > 0 and (res["costs"].get("slip0.3") or -1) > 0 and (res["costs"].get("spread0.4") or -1) > 0
          and (res["bootstrap"].get("ci95") or [-1])[0] > 0 and res["b2_random"]["v2_above_p95"] and sum(1 for v in q if v is not None and v > 0) >= 3
          and (res.get("max_week_share") or 1) <= 0.40)
    res["verdict"] = "SHOWS_EVIDENCE" if ok else ("NO_EVIDENCE_OF_EDGE" if res["trades"] >= MIN_TRIGGERS else "INSUFFICIENT_EVIDENCE")
    res["note"] = "forward shadow evidence only; B1 (V1 trades of the same period) requires results/v1 forward decisions: compare separately; never a profitability claim"
    return res
