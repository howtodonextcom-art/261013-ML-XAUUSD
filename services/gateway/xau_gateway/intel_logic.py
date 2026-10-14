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
    ev = [{k: e[k] for k in ("setup_id", "direction", "state", "prev_state", "known_at", "reasons", "entry_level", "invalidation_level")}
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


def log_new_v2_events(path, events: list, seen: set, live_from_known_at: int | None, v1_active: dict | None = None, server_utc_offset_s: int | None = None) -> int:
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
            for k in ("trigger_close", "trigger_low", "atr5", "evidence"):
                if k in e:
                    rec[k] = e[k]
            if server_utc_offset_s is not None:
                rec["server_utc_offset_s"] = int(server_utc_offset_s)
            if e.get("stage") == "M1_TRIGGERED" and e.get("kind") != "WINDOW_STATE":
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
