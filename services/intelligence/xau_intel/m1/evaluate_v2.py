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
M1 = 60
N_SEEDS = 500
DAY = 86400


def normalize(e: dict) -> dict:
    """Records written before `log_schema` 2 carry SELL trigger prices in MIRRORED (negated) space (implementation defect found 2026-10-14, docs/research/M1_ENTRY_V2_AMENDMENTS.md).
    The repair is deterministic and lossless: real = -mirrored. The stored line is never edited."""
    if e.get("log_schema") == 2 or e.get("direction") != "SELL":
        return e
    out = dict(e)
    for k in ("trigger_close", "trigger_low"):
        if out.get(k) is not None:
            out[k] = -float(out[k])
    out["log_schema"] = "REPAIRED_FROM_1"
    return out


def read_log(text: str) -> tuple[list[dict], int]:
    """Parse the forward log tolerantly: (events, number of unreadable lines). Duplicates by event_id are kept once (first record wins)."""
    import json
    out, seen, bad = [], set(), 0
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            e = json.loads(line)
            eid = e["event_id"]
            e["known_at"]
        except Exception:  # noqa: BLE001
            bad += 1
            continue
        if eid not in seen:
            seen.add(eid)
            out.append(normalize(e))
    return out, bad


def events_to_utc(events: list[dict], resolve) -> tuple[list[dict], dict]:
    """Convert event stamps (SERVER time as logged) to UTC. The offset is the one recorded in the record itself (`server_utc_offset_s`); legacy records fall back to `resolve(server_ts)`
    (measured-evidence resolver; None = unprovable). Unprovable events are EXCLUDED and counted, never converted with a guess."""
    out, cnt = [], {}
    for e in events:
        off = e.get("server_utc_offset_s")
        if off is None:
            off = resolve(int(e["known_at"]))
        if off is None:
            cnt["EVENT_OFFSET_UNPROVABLE"] = cnt.get("EVENT_OFFSET_UNPROVABLE", 0) + 1
            continue
        out.append({**e, "bar_time": int(e["bar_time"]) - int(off), "known_at": int(e["known_at"]) - int(off), "utc_offset_applied_s": int(off)})
    return out, cnt


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


def _sim(plan, i_trigger, m1, cost, optimistic=False, timeout_bars=TIMEOUT_M1):
    slip, comm, floor = cost
    sp = np.maximum(m1["spread"], floor) if floor else m1["spread"]
    p2 = {**plan, "slippage_allowance": slip, "value_per_price_unit_per_lot": 100.0}
    out = simulate_outcome(p2, i_trigger, m1["open"], m1["high"], m1["low"], m1["close"], sp, timeout_bars=timeout_bars, max_chase=plan["stop_distance"], planned_entry=plan["entry"],
                           conservative=True, commission_per_lot=comm, gap_stops=True, ask_side_stops=True, optimistic_ambiguous=optimistic)
    r = None if out.get("pnl_price") is None else float(out["pnl_price"]) / float(plan["stop_distance"])
    return out, r


def window_view(m1: dict, t: np.ndarray, bar_time: int):
    """Gap-safe position window for a trigger bar at `bar_time` (amendment A8). Returns (view, timeout_bars, why):
    the entry bar must be the M1 bar at bar_time + 60 (else why = ENTRY_BAR_MISSING and no fill exists); the timeout is 288 M1 MINUTES of timeline (bars that do not
    exist inside a market closure do not extend the position); `timeout_bars` is shortened to the bars that exist when the data covers the whole window, and left at 288
    (so that a window that outruns the data ends INCONCLUSIVE/DATA_ENDED_BEFORE_EXIT) when it does not."""
    i = int(np.searchsorted(t, bar_time))
    if i >= len(t) or int(t[i]) != int(bar_time):
        return None, 0, "NO_BAR"
    if i + 1 >= len(t) or int(t[i + 1]) != int(bar_time) + M1:
        return None, 0, "ENTRY_BAR_MISSING"
    end_t = int(bar_time) + M1 + TIMEOUT_M1 * M1                   # the position may live in [entry bar open, end_t)
    j = int(np.searchsorted(t, end_t))
    data_covers = j < len(t)                                        # a bar at or after the window end exists: the window is complete, whatever holes it contains
    if not data_covers:
        return None, 0, "WINDOW_NOT_COMPLETE"                       # outcome-independent: a trade whose whole window is not yet stored is not counted, whether it would have exited early or not
    view = {k: np.asarray(v)[i:j] for k, v in m1.items()}
    view["ext_time"] = np.asarray(t)[i:j + 1]                        # the window PLUS the first bar at/after its end: a hole straddling the window end must be judged too (review round 12, H3)
    return view, len(view["time"]) - 1, "OK"


def genuine_gap_in(view_t: np.ndarray, closures=None) -> bool:
    """True when the position window holds a hole that is NOT covered by an evidenced market closure (so the price path there is unknown = missing data). `closures` is a list of
    (first_missing_bar_utc, last_missing_bar_utc) windows that matched a RECURRING closure signature (utcstore.closure_windows); without evidence (None / empty) every hole is
    missing data, however long: a long hole is never a closure by length alone (a feed outage of 3 hours is not a market break). The test looks at the whole window, never at
    the simulated exit, so it cannot select trades by their outcome (review round 11, H1)."""
    t = np.asarray(view_t, dtype=np.int64)
    holes = np.where(np.diff(t) > M1)[0]
    if len(holes) == 0:
        return False
    cl = sorted(closures or [])
    for k in holes:
        start, end = int(t[k]) + M1, int(t[k + 1]) - M1
        if not any(a <= start and end <= b for a, b in cl):
            return True
    return False


def run_trades(events: list[dict], m1: dict, closures=None) -> tuple[list[dict], dict]:
    """m1: dict(time, open, high, low, close, spread in price units), sorted. Returns (trades, counters)."""
    t = np.asarray(m1["time"], dtype=np.int64)
    cnt: dict[str, int] = {}
    busy = {"BUY": -1, "SELL": -1}
    trades = []
    for e in triggers_of(events):
        view, tb, why0 = window_view(m1, t, int(e["bar_time"]))
        if view is None:
            k = {"NO_BAR": "NO_BAR", "ENTRY_BAR_MISSING": "NOT_COUNTED:ENTRY_BAR_MISSING", "WINDOW_NOT_COMPLETE": "NOT_COUNTED:WINDOW_NOT_COMPLETE"}[why0]
            cnt[k] = cnt.get(k, 0) + 1
            continue
        if genuine_gap_in(view["ext_time"], closures):
            cnt["NOT_COUNTED:MISSING_DATA_IN_WINDOW"] = cnt.get("NOT_COUNTED:MISSING_DATA_IN_WINDOW", 0) + 1
            continue
        if e["known_at"] < busy[e["direction"]]:
            cnt["SKIPPED_POSITION_OPEN"] = cnt.get("SKIPPED_POSITION_OPEN", 0) + 1
            continue
        try:
            plan, why = plan_for(e, float(view["spread"][0]))
        except (TypeError, ValueError, KeyError):
            cnt["NOT_TRADED:BAD_RECORD"] = cnt.get("NOT_TRADED:BAD_RECORD", 0) + 1
            continue
        if plan is None:
            k = "NOT_TRADED:" + why
            cnt[k] = cnt.get(k, 0) + 1
            continue
        sims = {k: _sim(plan, 0, view, c, timeout_bars=tb) for k, c in COSTS.items()}
        bad = [k for k, (o, r) in sims.items() if o["outcome"] in ("NO_FILL", "NO_DATA", "INCONCLUSIVE") or r is None]
        if bad:                                                      # like-for-like: a trade that cannot be counted under one cost scenario is out of ALL of them
            k = f"NOT_COUNTED:{sims['base'][0]['outcome'] if 'base' in bad else 'COST_SCENARIO_' + bad[0]}"
            cnt[k] = cnt.get(k, 0) + 1
            continue
        base = sims["base"][0]
        busy[e["direction"]] = int(view["time"][base["exit_idx"]]) + 60
        trades.append({"event_id": e["event_id"], "direction": e["direction"], "kind": e["kind"], "decision_time": int(e["known_at"]), "exit_time": busy[e["direction"]],
                       "stop_distance": plan["stop_distance"], "target_distance": abs(plan["take_profit"] - plan["entry"]), "atr5": float(e["atr5"]), "outcome": base["outcome"],
                       "r": {k: round(v[1], 10) for k, v in sims.items()}})
    return trades, cnt


def random_comparator(trades: list[dict], m1: dict, lo: int, hi: int, seeds: int = N_SEEDS, seed0: int = 20261014, closures=None) -> list[float]:
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
            view, tb, w = window_view(m1, t, int(t[i]))
            if view is None or genuine_gap_in(view["ext_time"], closures):
                continue
            entry = float(view["close"][0])
            plan, _ = plan_direct("BUY" if sg == 1 else "SELL", entry, entry - sg * tr["stop_distance"], entry + sg * tr["target_distance"], tr["atr5"], float(view["spread"][0]))
            if plan is None:
                continue
            o, r = _sim(plan, 0, view, COSTS["base"], timeout_bars=tb)
            if r is not None and o["outcome"] not in ("NO_FILL", "NO_DATA", "INCONCLUSIVE"):
                rs.append(r)
        if rs:
            out.append(float(np.mean(rs)))
    return out


REGISTRATION_UTC = 1791960048            # commit afd688e (frozen)
LEGACY_OFFSET_S = 10800                  # server offset measured at registration (HIGH); applies to records written before offsets were stored


def clock(events: list[dict], now_utc: int, registration_utc: int = REGISTRATION_UTC) -> dict:
    """UTC <-> server-time bases without assuming a single offset (amendment A3/A9). The 30-day gate is a pure UTC difference. The registration instant in server time
    uses the offset recorded with the EARLIEST record (the server time zone in force around registration); `now` in server time uses the offset of the LATEST record, so a
    DST switch inside the forward period moves `now` by the real hour and never corrupts the gate. Bars/events are always compared in server time as recorded."""
    offs = [(e["known_at"], int(e["server_utc_offset_s"])) for e in sorted(events, key=lambda x: x["known_at"]) if e.get("server_utc_offset_s") is not None]
    off_reg = offs[0][1] if offs else LEGACY_OFFSET_S
    off_now = offs[-1][1] if offs else LEGACY_OFFSET_S
    return {"now_utc": int(now_utc), "reg_utc": int(registration_utc), "now_server": int(now_utc) + off_now, "reg_server": int(registration_utc) + off_reg,
            "offset_at_registration_s": off_reg, "offset_now_s": off_now}


def evaluate(events: list[dict], m1: dict, now_ts: int, registration_ts: int, gate_now_utc: int | None = None, gate_reg_utc: int | None = None, closures=None) -> dict:
    """now_ts / registration_ts are SERVER-time stamps (bars are server time). The gate uses the UTC pair when given (always, in production)."""
    g = gate(events, gate_now_utc if gate_now_utc is not None else now_ts, gate_reg_utc if gate_reg_utc is not None else registration_ts)
    if g is not None:
        return g                                                       # refused: nothing below is computed, no bar is read
    mt = np.asarray(m1["time"], dtype=np.int64)
    if len(mt) != len(np.unique(mt)) or bool(np.any(np.diff(mt) <= 0)):
        return {"status": "REFUSED_NON_MONOTONIC_BAR_TIMES", "note": "duplicate or backward M1 server times (a DST fall-back hour in the forward period?): the evaluation will not interleave two different hours; "
                "a UTC-keyed bar store is needed first (docs/research/M1_ENTRY_V2_AMENDMENTS.md A9)", "performance_claim": "NONE"}
    trades, cnt = run_trades(events, m1, closures)
    res = {"status": "EVALUATED", "triggers": len(triggers_of(events)), "trades": len(trades), "counters": cnt, "base": summarize(trades), "bootstrap": day_bootstrap(trades, "base"),
           "costs": {k: summarize(trades, k).get("mean_r") for k in COSTS}, "bootstrap_slip0.3": day_bootstrap(trades, "slip0.3"), "bootstrap_spread0.4": day_bootstrap(trades, "spread0.4")}
    lo, hi = registration_ts, now_ts
    b2 = random_comparator(trades, m1, lo, hi, closures=closures)
    mean = res["base"].get("mean_r")
    res["b2_random"] = {"seeds": len(b2), "p95": float(np.percentile(b2, 95)) if b2 else None, "v2_above_p95": bool(b2 and mean is not None and mean > np.percentile(b2, 95))}
    # chronological quarters of the forward period and weekly concentration
    q = []
    if trades:
        edges = np.linspace(registration_ts, now_ts + 1, 5)          # four chronological quarters of the FORWARD PERIOD (registration to now), as registered
        for a, b in zip(edges[:-1], edges[1:]):
            sub = [x for x in trades if a <= x["decision_time"] < b]
            q.append(summarize(sub).get("mean_r") if sub else None)
        weeks: dict = {}
        for x in trades:
            weeks[x["decision_time"] // (7 * DAY)] = weeks.get(x["decision_time"] // (7 * DAY), 0.0) + x["r"]["base"]
        tot = sum(weeks.values())                                       # frozen wording: no single week more than 40% of TOTAL R
        res["max_week_share"] = None if tot <= 0 else max(weeks.values()) / tot
    res["quarters_mean_r"] = q
    ok = (res["trades"] >= MIN_TRIGGERS and (mean or -1) > 0 and (res["costs"].get("slip0.3") or -1) > 0 and (res["costs"].get("spread0.4") or -1) > 0
          and (res["bootstrap"].get("ci95") or [-1])[0] > 0 and res["b2_random"]["v2_above_p95"] and sum(1 for v in q if v is not None and v > 0) >= 3
          and res.get("max_week_share") is not None and res["max_week_share"] <= 0.40)
    res["verdict"] = "SHOWS_EVIDENCE" if ok else ("NO_EVIDENCE_OF_EDGE" if res["trades"] >= MIN_TRIGGERS else "INSUFFICIENT_EVIDENCE")
    res["note"] = "forward shadow evidence only; B1 (V1 trades of the same period) requires results/v1 forward decisions: compare separately; never a profitability claim"
    return res
