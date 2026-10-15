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
TF_SEC_SETUP = 900         # M15: swings known at the close of the last setup bar
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
    ev = [{**{k: e[k] for k in ("setup_id", "direction", "state", "prev_state", "known_at", "reasons", "entry_level", "invalidation_level")},
           "event_id": f"{e['setup_id']}|{e['state']}|{int(e['known_at'])}", "provenance": "LIVE_ENGINE"}
          for e in res["events"][-recent_events:]]
    zones = []
    if not np.isnan(a[-1]):
        from xau_intel.setups.zones import build_zones
        known = [x for x in sw if not x.window_start_artifact and x.known_at <= int(t[-1]) + TF_SEC_SETUP]
        px = float(c[-1])
        zs = build_zones(known, float(a[-1]), 0.5, 0.25, 2)
        for z in sorted(zs, key=lambda q: abs(q.center - px))[:6]:
            zones.append({"low": float(z.low), "high": float(z.high), "center": float(z.center), "touches": int(z.touches), "known_at": int(z.known_at),
                          "side": "SUPPORT" if z.high <= px else "RESISTANCE" if z.low >= px else "AT_PRICE"})
    return {**out, "status": status, "market": market, "atr": None if np.isnan(a[-1]) else float(a[-1]), "setup_events": ev, "zones": zones,
            "setup_bar_time": int(t[-1]), "setup_events_total": len(res["events"]),
            "setup_events_all": [compact_setup_event(e, "LIVE_ENGINE") for e in res["events"]]}      # the realtime payload keeps only the newest `recent_events`; the full list feeds /api/setup_events


from .setup_history import compact as compact_setup_event  # noqa: E402


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


# ------------------------------------------------------------------ M1 Entry Intelligence V2 (SHADOW): view and forward log
V2_LOG_PATH_DEFAULT = None


def build_v2_view(v2: dict | None, *, partial: dict | None, spread, v1_active: dict | None, risk_policy: RiskPolicy, gate_policy: GatePolicy, now_server: int | None = None) -> dict | None:
    """The public shadow section. It is a pure view of the run_v2 result: it never touches the V1 decision, never returns a BUY/SELL action, and a plan (levels and
    R:R on the reference account, no lot) only exists while a CLOSED M1 trigger is knowable and its entry window is open. Nothing here is an order."""
    from xau_intel.decision.risk import RiskPolicy as _RP  # noqa: F401
    from xau_intel.backtest.engine import plan_direct
    from xau_intel.m1.entry_v2 import LABEL, POLICY, forming_observation
    if v2 is None:
        return None
    primary = v2.get("primary")
    view = {"version": v2["version"], "label": LABEL, "kind": "SHADOW_OBSERVATION", "execution_authorized": False, "context": v2.get("context"), "primary": primary,
            "directions": v2.get("directions", {}), "events_recent": v2.get("events", [])[-8:], "funnel": v2.get("funnel", {}), "plan": None, "entry_check": None,
            "forming": forming_observation(partial, (v2.get("atr") or {}).get("M1"), v2)}
    if not primary:
        return view
    st = v2["directions"].get(primary) or {}
    trig = st.get("trigger")
    if st.get("stage") in ("M1_TRIGGERED", "ENTRY_WINDOW") and trig and st.get("zone") and now_server is not None and now_server >= int(trig["window_ends_at"]):
        view["entry_check"] = {"stage": "WINDOW_EXPIRED", "plan_status": "ENTRY_WINDOW_ELAPSED", "research_entry_ready": False,
                               "note": "the entry window elapsed while no new closed M1 bar arrived: no plan is shown (a shadow observation, never an order)"}
    elif st.get("stage") in ("M1_TRIGGERED", "ENTRY_WINDOW") and trig and st.get("zone"):
        sign = 1 if primary == "BUY" else -1
        a5 = float(trig["atr5"])
        entry = float(trig["bar_close"])
        zone_edge = st["zone"]["low"] if sign == 1 else st["zone"]["high"]
        extreme = float(trig["bar_extreme"])
        sl = (min(extreme, zone_edge) - POLICY.sl_buffer_atr5 * a5) if sign == 1 else (max(extreme, zone_edge) + POLICY.sl_buffer_atr5 * a5)
        v1t = ((v1_active or {}).get(primary) or {}).get("impulse", {}).get("high_price")
        tp = float(v1t) if v1t is not None and sign * (float(v1t) - entry) > 0 else entry + sign * POLICY.tp_rr * abs(entry - sl)
        plan, why = plan_direct(primary, entry, sl, tp, a5, spread, rp=risk_policy, gp=gate_policy)
        view["plan"] = _sanitize(plan) if plan else None
        if view["plan"]:
            view["plan"]["risk_fraction"] = risk_policy.risk_fraction
            view["plan"]["sizing"] = "REFERENCE_ACCOUNT" if not reveal_size() else "LIVE_ACCOUNT"
            view["plan"]["target_source"] = "V1_IMPULSE_EXTREME" if v1t is not None and tp == float(v1t) else "2R_FROM_STOP"
        view["entry_check"] = {"stage": st["stage"], "plan_status": why,
                               "research_entry_ready": st["stage"] == "ENTRY_WINDOW" and why == "OK",
                               "note": "re-evaluated with the current spread at every refresh; a shadow observation, never an order"}
    return view


def _pct(vals: list, q: float):
    if not vals:
        return None
    v = sorted(vals)
    return round(float(v[min(len(v) - 1, int(round(q * (len(v) - 1))))]), 1)


def perf_stats(vals) -> dict:
    try:
        vals = [float(x) for x in tuple(vals)]                   # tuple() is one atomic copy: a job thread appending cannot break the payload build
    except RuntimeError:
        vals = []
    return {"n": len(vals), "p50": _pct(vals, 0.5), "p95": _pct(vals, 0.95), "p99": _pct(vals, 0.99)}


def _quote_check(quote: dict | None, side: str, entry: float, sl: float, a5: float, band_atr5: float, max_age_s: float) -> dict:
    """Display-time comparison of the CURRENT quote with the registered plan. Uses only registered numbers: the 0.25 ATR5 entry band and the planned stop.
    BUY would be filled at the ask, SELL at the bid; the bid-chart band of the registered rule is tested on the bid."""
    if quote is None:
        return {"status": "NOT_COMPARED"}                       # caller supplied no quote at all (unit tests / tools): nothing is claimed
    if quote.get("bid") is None or quote.get("ask") is None:
        return {"status": "NO_QUOTE"}
    sign = 1 if side == "BUY" else -1
    bid, ask = float(quote["bid"]), float(quote["ask"])
    age = quote.get("age_s")
    out = {"bid": bid, "ask": ask, "age_s": age, "fill_side_price": ask if sign == 1 else bid, "delta_vs_planned_entry": (ask if sign == 1 else bid) - entry,
           "delta_atr5": ((ask if sign == 1 else bid) - entry) / a5 if a5 else None, "band_atr5": band_atr5}
    if age is None or age > max_age_s:
        return {**out, "status": "QUOTE_STALE"}
    if sign * ((bid if sign == 1 else ask) - sl) <= 0:      # a BUY stop is hit by the bid, a SELL stop by the ask
        return {**out, "status": "BEYOND_STOP"}
    if sign * (bid - entry) > band_atr5 * a5:
        return {**out, "status": "DRIFTED"}
    return {**out, "status": "IN_BAND"}


def build_c2_view(c2: dict | None, *, partial: dict | None, spread, risk_policy: RiskPolicy, gate_policy: GatePolicy, now_server: int | None = None, live_from: int | None = None, quote: dict | None = None, max_quote_age_s: float = 10.0) -> dict | None:
    """The public scalping-candidate section (SHADOW, research only). A pure view of the run_c2 result: it never touches the V1 decision or the V2 section, never
    returns an order. Semantics (Level 6.5.1), from weakest to strongest:
      WATCH BUY/SELL      side + zone, no closed M1 trigger yet
      M1_TRIGGERED        a closed M1 bar fired a research trigger: NOT yet through the Risk Gate, NOT a signal
      ENTRY_WINDOW        the trigger window is open and price is still inside the entry band
      signal BUY/SELL     ONLY when the trigger is a live forward event (known after the registration and after this process started) AND the paper plan passed the Risk Gate
      signal BLOCKED      the same live trigger, but the plan fails the broker stops level / R:R / spread limit (the stop is never widened)
    A trigger re-derived from the startup window (known before `live_from`) is shown as RE_DERIVED history: never a signal, never a plan.
    The plan levels come from the trigger bar close exactly like the registered evaluator (plan_for); the registered FILL is the next M1 bar open."""
    from xau_intel.backtest.engine import plan_direct
    from xau_intel.scalp.c2 import LABEL, POLICY
    if c2 is None:
        return None
    side = c2.get("side")
    dirs = c2.get("directions", {})
    st = dirs.get(side) if side else None
    now = now_server

    def prov(e):
        return "LIVE_FORWARD" if (live_from is not None and e.get("known_at", 0) >= live_from) else "RE_DERIVED"

    evs = []
    for e in c2.get("events", [])[-8:]:
        cur = bool(e.get("stage") == "M1_TRIGGERED" and e.get("kind") != "WINDOW_STATE" and now is not None and e["known_at"] <= now < e["known_at"] + 60 * POLICY.entry_window_m1)
        evs.append({**e, "provenance": prov(e), "current": cur and prov(e) == "LIVE_FORWARD"})   # a re-derived trigger is never "current"
    view = {"strategy_id": c2["strategy_id"], "version": c2["version"], "label": LABEL, "kind": "SCALP_RESEARCH_OBSERVATION", "execution_authorized": False,
            "m5_structure": c2.get("m5_structure"), "m1_momentum": c2.get("m1_momentum"), "m15": c2.get("m15"), "h1_h4": c2.get("h1_h4"), "side": side,
            "stage": (st or {}).get("stage", "NO_SIDE"), "candidate": "WAIT", "signal": None, "missing": None, "expires_at": None, "plan": None, "block_reasons": [],
            "risk_status": "NOT_EVALUATED: no closed M1 trigger", "provenance": None, "zone": None, "directions": dirs, "events_recent": evs, "funnel": c2.get("funnel", {}),
            "evaluated_at": c2.get("now"), "display_only_forming": None, "live_from": live_from,
            "entry_basis": "Levels come from the trigger bar close (registered plan); the registered fill is the NEXT M1 bar open, ask/bid-aware, with the chase limit = stop distance"}
    if partial:
        view["display_only_forming"] = {k: partial.get(k) for k in ("t", "open", "high", "low", "close")}
    if not st:
        view["missing"] = "M5 structure must show UP (BUY side) or DOWN (SELL side); RANGE/UNKNOWN gives no side"
        return view
    view["zone"] = st.get("zone")
    view["missing"] = st.get("next_required")
    trig = st.get("trigger")
    if st.get("stage") in ("M1_TRIGGERED", "ENTRY_WINDOW") and not (trig and st.get("zone")):
        view["stage"] = "NO_SIDE"                                    # an incomplete trigger state is never shown as a trigger
    if st.get("stage") == "WATCH":
        view["candidate"] = "WATCH " + side
    elif st.get("stage") in ("M1_TRIGGERED", "ENTRY_WINDOW") and trig and st.get("zone"):
        view["expires_at"] = int(trig["window_ends_at"])
        view["provenance"] = "LIVE_FORWARD" if (live_from is not None and trig["known_at"] >= live_from) else "RE_DERIVED"
        view["alignment"], view["trigger"] = trig.get("alignment"), {k: trig.get(k) for k in ("kind", "flags", "known_at", "window_ends_at")}
        if now is not None and now >= view["expires_at"]:
            view["candidate"], view["missing"], view["risk_status"] = "WAIT", "entry window elapsed; waiting for a new closed M1 trigger", "NOT_EVALUATED: window elapsed"
            view["stage"] = "WINDOW_ELAPSED"
            return view
        sign = 1 if side == "BUY" else -1
        a5 = float(trig["atr5"])
        entry, extreme = float(trig["bar_close"]), float(trig["bar_extreme"])
        zone_edge = st["zone"]["low"] if sign == 1 else st["zone"]["high"]
        sl = (min(extreme, zone_edge) - POLICY.sl_buffer_atr5 * a5) if sign == 1 else (max(extreme, zone_edge) + POLICY.sl_buffer_atr5 * a5)
        tp = entry + sign * POLICY.tp_rr * abs(entry - sl)
        plan, why = plan_direct(side, entry, sl, tp, a5, spread, rp=risk_policy, gp=gate_policy)
        trig_bar_t = int(trig["known_at"]) - 60
        if partial and partial.get("t") == trig_bar_t + 60 and partial.get("open") is not None:
            view["expected_fill"] = {"price": float(partial["open"]), "basis": "open of the M1 bar after the trigger (the registered fill, before spread and slippage)", "delta_vs_plan_entry": float(partial["open"]) - entry}
        if view["provenance"] != "LIVE_FORWARD":
            view.pop("expected_fill", None)                       # no fill figures for history
            view["candidate"] = "WAIT"
            view["missing"] = "this trigger was re-derived from the startup window (not a live forward event): history only, no signal and no plan"
            view["risk_status"] = "NOT_EVALUATED: re-derived history"
        elif st["stage"] != "ENTRY_WINDOW":
            view["candidate"], view["missing"] = "WAIT", "price moved outside the entry band after the closed M1 trigger; no entry is shown until it returns inside"
            view["risk_status"] = "NOT_EVALUATED: outside the entry band"
        elif plan and why == "OK":
            view["plan"] = _sanitize(plan)
            view["plan"]["sizing"] = "REFERENCE_ACCOUNT" if not reveal_size() else "LIVE_ACCOUNT"
            view["signal"], view["candidate"], view["missing"] = side, "WAIT", "nothing: live closed-M1 trigger inside its entry window and through the paper preflight (research only)"
            view["risk_status"] = f"PAPER PREFLIGHT PASSED: stop {abs(entry - sl):.2f} USD, net R:R {float(view['plan'].get('net_rr') or 0):.2f} (reference account; live quote and real account NOT verified)"
            qc = _quote_check(quote, side, entry, sl, a5, POLICY.window_chase_atr5, max_quote_age_s)
            view["quote_check"] = qc
            if qc["status"] in ("DRIFTED", "BEYOND_STOP", "QUOTE_STALE", "NO_QUOTE"):
                # the paper state is no longer current: nothing is shown as a live signal (registered thresholds only: the 0.25 ATR5 entry band and the planned stop)
                view["signal"], view["candidate"], view["plan"] = None, "WAIT", None
                view["superseded"] = qc["status"]
                view["missing"] = {"DRIFTED": "the live price moved beyond the registered entry band after the trigger: this paper signal is no longer current",
                                   "BEYOND_STOP": "the live price is beyond the planned stop: this paper signal is no longer current",
                                   "QUOTE_STALE": "the live quote is too old to compare with the plan: this paper signal is not shown as current",
                                   "NO_QUOTE": "no live bid/ask is available to compare with the plan: this paper signal is not shown as current"}[qc["status"]]
                view["risk_status"] = "NOT CURRENT: " + qc["status"]
                view.pop("expected_fill", None)
            else:
                view["live_quote_verified"] = qc["status"] == "IN_BAND"
        else:
            view["signal"], view["block_reasons"] = "BLOCKED", [str(why)]
            view["candidate"], view["missing"] = "WAIT", "BLOCKED: " + str(why) + " (the stop is never widened)"
            view["risk_status"] = "BLOCKED: " + str(why)
            if plan:
                view["plan"] = _sanitize(plan)
    return view


class _file_lock:
    """Cross-thread and cross-process exclusive lock via an O_EXCL lock file next to the log; a lock older than 30 s is considered stale (crashed holder)."""
    def __init__(self, path, timeout: float = 10.0):
        self.lock, self.timeout = str(path) + ".lock", timeout

    def __enter__(self):
        import os
        import time
        t0 = time.monotonic()
        while True:
            try:
                self.fd = os.open(self.lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                return self
            except (FileExistsError, PermissionError):                  # Windows reports a lock file that is being deleted as PermissionError
                try:
                    if time.time() - os.path.getmtime(self.lock) > 30:
                        os.remove(self.lock)
                        continue
                except OSError:
                    pass
                if time.monotonic() - t0 > self.timeout:
                    raise TimeoutError("forward log lock busy")
                time.sleep(0.005)

    def __exit__(self, *exc):
        import os
        os.close(self.fd)
        try:
            os.remove(self.lock)
        except OSError:
            pass


def load_seen_v2(path) -> set:
    """event_ids already in the forward log (corrupt or torn lines are skipped, never fatal): called once at start so a restart cannot write duplicates."""
    import json
    from pathlib import Path
    seen: set = set()
    path = Path(path)
    if not path.exists():
        return seen
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            seen.add(json.loads(line)["event_id"])
        except Exception:  # noqa: BLE001  a corrupt line is evidence damage to report, not a reason to stop logging
            continue
    return seen


def log_new_v2_events(path, events: list, seen: set, live_from_known_at: int | None, v1_active: dict | None = None, server_utc_offset_s: int | None = None, extra_keys: tuple = (), with_v1_target: bool = True) -> int:
    """Append-only forward log (one JSON line per event). ONLY events that became knowable at or after `live_from_known_at` are written: the window scan of a
    freshly started gateway re-derives history, which is inside the sealed holdout period and must never enter the forward evidence. Deduplicated by event_id.
    An id is marked as seen ONLY after the batch was written, flushed and fsynced; a write error raises and leaves every id unmarked (retried on the next bar).
    A torn last line (crash mid-write) is closed with a newline first so the next record starts on its own line."""
    import json
    import os
    from pathlib import Path
    if live_from_known_at is None:
        return 0
    lines, ids, errors = [], [], []
    for e in events:
        if e["known_at"] < live_from_known_at or e["event_id"] in seen or e["event_id"] in ids:
            continue
        try:
            rec = {k: e[k] for k in ("event_id", "version", "direction", "stage", "kind", "bar_time", "known_at", "zone", "reasons", "log_schema") if k in e}
            for k in ("trigger_close", "trigger_low", "atr5", "evidence", *extra_keys):
                if k in e:
                    rec[k] = e[k]
            if server_utc_offset_s is not None:
                rec["server_utc_offset_s"] = int(server_utc_offset_s)
            if with_v1_target and e.get("stage") == "M1_TRIGGERED" and e.get("kind") != "WINDOW_STATE":
                hp = (((v1_active or {}).get(e["direction"]) or {}).get("impulse") or {}).get("high_price")      # the frozen TP rule needs the V1 impulse extreme active at the trigger
                if hp is not None:
                    rec["v1_target"] = float(hp)
            lines.append(json.dumps(strict(rec), sort_keys=True, allow_nan=False) + chr(10))
            ids.append(e["event_id"])
        except Exception as ex:  # noqa: BLE001  one unserialisable record must not block the batch every bar: it is reported in <log>.errors, never silently dropped
            errors.append({"event_id": str(e.get("event_id")), "error": type(ex).__name__, "known_at": e.get("known_at")})
            seen.add(e["event_id"])
    if errors:
        with open(str(path) + ".errors", "a", encoding="utf-8") as f_err:
            f_err.write("".join(json.dumps(x) + chr(10) for x in errors))
    if not lines:
        return 0
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _file_lock(path):                                               # appends from two writers (threads or processes) are serialised: Windows O_APPEND is not atomic across handles
        prefix = ""
        if path.exists() and path.stat().st_size > 0:
            with open(path, "rb") as r:
                r.seek(-1, os.SEEK_END)
                if r.read(1) != bytes([10]):
                    prefix = chr(10)
        data = (prefix + "".join(lines)).encode("utf-8")
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_BINARY", 0), 0o644)
        try:
            written = 0
            while written < len(data):
                written += os.write(fd, data[written:])
            os.fsync(fd)
        finally:
            os.close(fd)
    seen.update(ids)
    return len(lines)


# ------------------------------------------------------------------ V1 Research Decision Events (Level 6.2)
# An append-only history of the moments at which the PRODUCTION decision engine published a BUY/SELL (strategy-eligible, risk and every hard gate PASS, fresh data) or
# an eligible-but-BLOCKED setup. One event per (setup, action) for BUY/SELL and per (setup, blocking reason) for BLOCKED: the first publication of that state, never one per
# 2-second refresh or per tick. Nothing here is reconstructed from setup markers: an event exists only if the decision was really published. No equity, lot or money field.
V1_EVENT_SCHEMA = 1
V1_EVENTS_DEFAULT_LIMIT = 50
_V1_DROP = MONEY_KEYS + ("lot", "risk_money", "equity", "free_margin")


def _blocked_code(primary: str) -> str:
    """'RISK:RR_TOO_LOW: net 1.1 < 1.5 (gross 1.3)' -> 'RISK:RR_TOO_LOW'; 'SPREAD_TOO_WIDE(0.60 ATR > 0.3)' -> 'SPREAD_TOO_WIDE' (numbers vary tick to tick, the code does not)."""
    p = str(primary).split("(")[0]
    parts = p.split(":")
    return (parts[0] + ":" + parts[1].strip()) if parts[0] == "RISK" and len(parts) > 1 else parts[0].strip()


def v1_event_from_decision(dec: dict, *, bid, published_at: int, published_wall_ms: int, evaluated_at, setup_tf: str = "M15", server_utc_offset_s: int | None = None) -> dict | None:
    """The event record for this decision, or None when the decision is not an event. Pure."""
    if not dec or dec.get("primary_reason") == "DATA_STALE":
        return None
    setup, action = dec.get("setup"), dec.get("action")
    if not setup or not setup.get("setup_id"):
        return None
    gates = (dec.get("reasons") or {}).get("gate") or []
    risk = dec.get("risk") or {}
    if action in ("BUY", "SELL"):
        if not dec.get("strategy_eligible") or gates or risk.get("status") != "OK" or dec.get("primary_reason") != "ENTRY_ELIGIBLE":
            return None
        did = f"{setup['setup_id']}|{action}"
    elif action == "BLOCKED":
        if not dec.get("strategy_eligible"):
            return None
        did = f"{setup['setup_id']}|BLOCKED|{_blocked_code(dec.get('primary_reason'))}"
    else:
        return None
    plan = {k: v for k, v in (dec.get("plan") or {}).items() if k not in _V1_DROP}
    known = setup.get("known_at")
    ev = {"log_schema": V1_EVENT_SCHEMA, "decision_id": did, "setup_id": setup["setup_id"], "action": action, "direction": setup.get("direction"),
          "event_time": int(published_at), "known_at": None if known is None else int(known), "evaluated_at": None if evaluated_at is None else int(evaluated_at),
          "published_at": int(published_at), "published_wall_ms": int(published_wall_ms), "source_timeframe": setup_tf, "price": None if bid is None else float(bid),
          "strategy_version": dec.get("strategy_version"), "dataset_version": dec.get("dataset_version"), "primary_reason": dec.get("primary_reason"),
          "risk_status": risk.get("status"), "gates": list(gates), "plan": plan or None, "sizing": dec.get("sizing"),
          "valid": {"expires_at": setup.get("expires_at"), "entry_window_ends_at": setup.get("entry_window_ends_at"), "invalidation_level": setup.get("invalidation_level"),
                    "entry_level": setup.get("entry_level"), "zone": setup.get("zone")},
          "publish_latency_s": None if known is None else int(published_at) - int(known), "kind": "RESEARCH_DECISION_EVENT", "execution_authorized": False}
    ev["late_publication"] = bool(known is not None and int(published_at) - int(known) > 120)      # e.g. a gateway restart while a setup was already eligible: published_at is when it was FIRST PUBLISHED by this process
    if server_utc_offset_s is not None:
        ev["server_utc_offset_s"] = int(server_utc_offset_s)
    return strict(ev)


def load_v1_events(path, limit: int | None = None) -> tuple[list[dict], int]:
    """(events oldest-first, unreadable lines). Duplicates by decision_id keep the first record. Tolerates a torn last line."""
    import json
    from pathlib import Path
    path = Path(path)
    if not path.exists():
        return [], 0
    out, seen, bad = [], set(), 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            e = json.loads(line)
            did = e["decision_id"]
        except Exception:  # noqa: BLE001
            bad += 1
            continue
        if did not in seen:
            seen.add(did)
            out.append(e)
    return (out if limit is None else out[-limit:]), bad


def log_v1_events(path, events: list[dict], seen: set) -> int:
    """Durable append (same rules as the V2 forward log): lock, single O_APPEND write, fsync, ids marked seen only after the write succeeded."""
    import json
    import os
    from pathlib import Path
    fresh = [e for e in events if e["decision_id"] not in seen]
    if not fresh:
        return 0
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(e, sort_keys=True, allow_nan=False) + chr(10) for e in fresh]
    with _file_lock(path, timeout=2.0):                                  # short: the decision worker must never wait long (a failure is retried on the next 2 s cycle and surfaced as v1_log_error)
        prefix = ""
        if path.exists() and path.stat().st_size > 0:
            with open(path, "rb") as r:
                r.seek(-1, os.SEEK_END)
                if r.read(1) != bytes([10]):
                    prefix = chr(10)
        data = (prefix + "".join(lines)).encode("utf-8")
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_BINARY", 0), 0o644)
        try:
            written = 0
            while written < len(data):
                written += os.write(fd, data[written:])
            os.fsync(fd)
        finally:
            os.close(fd)
    seen.update(e["decision_id"] for e in fresh)
    return len(fresh)
