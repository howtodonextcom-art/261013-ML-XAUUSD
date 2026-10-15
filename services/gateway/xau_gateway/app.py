"""FastAPI gateway: MT5 ticks -> candle engine -> WebSocket (+ off-path Parquet persistence).
Read-only API (GET + WS only), bound to 127.0.0.1 by default. No trading logic lives here."""
import asyncio
import copy
from collections import deque
import json
import os
import queue
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from . import auth as authmod
from .candles import CandleEngine
from .utcstore import add_offset_evidence
from .intel_logic import load_v1_events, log_v1_events, v1_event_from_decision, V1_EVENTS_DEFAULT_LIMIT
from .intel_logic import build_c2_view, build_v2_view, perf_stats, compute_heavy, load_seen_v2, log_new_v2_events, make_decision, overlays, strict
from .latency import LatencyStats
from .mt5_source import MT5TickSource
from .identity import load_source_config
from .quality import HIST_BARS, LIVE_TICKS
from .storage import LiveTickWriter, Store
from .symbol_spec import save_spec

ROOT = Path(__file__).resolve().parents[3]
STATIC = ROOT / "apps" / "dashboard-static"
IDLE_AFTER_S = float(os.environ.get("XAU_IDLE_AFTER_S", "5"))     # no ticks while terminal is connected => IDLE, not DISCONNECTED
STALE_AFTER_S = float(os.environ.get("XAU_STALE_AFTER_S", "60"))  # long silence while connected => STALE (needs attention)
BAD_FLAGS = ("CROSSED_QUOTE", "NONPOSITIVE_PRICE")


class State:
    def __init__(self):
        self.engine = CandleEngine()
        self.lat = LatencyStats()
        self.last_tick: dict | None = None
        self.ticks_total = 0
        self.rate_window: list[float] = []
        self.quality_counts: dict[str, int] = {}
        self.clients: set[WebSocket] = set()
        self.lock = threading.Lock()
        self.pipeline_errors = 0
        self.pipeline_last_error = None
        self.pipeline_alive = time.monotonic()   # heartbeat of the pipeline thread (updated even when idle)


S = State()
HIST_DICTS: dict[str, dict[int, dict]] = {}
INTEL_TFS = ("M15", "H1", "H4")
V2_TFS = ("M1", "M5", "M15", "H1", "H4")
V2_REGISTRATION_UTC = 1791960048          # commit afd688e: forward evidence only counts events that became knowable AFTER this instant (docs/research/M1_ENTRY_V2_PREREGISTRATION.md)
V2: dict = {"result": None, "m1_t": None, "result_t": None, "seen": set(), "error": None, "log_from": None, "logged": 0, "job": None}
V1EV: dict = {"seen": set(), "seeded": False, "recent": [], "logged": 0, "error": None}      # V1 research decision events (append-only history; Level 6.2)
V1_EVENTS_PATH = ROOT / "data" / "decisions" / "v1_events.jsonl"
C2_REGISTRATION_UTC = 1792022334          # docs/research/SCALPING_C2_C3_PREREGISTRATION.md (+ AMENDMENTS): C2 forward evidence counts only events known AFTER this instant
C2: dict = {"result": None, "result_t": None, "seen": set(), "error": None, "logged": 0, "log_from": None, "live_from": None, "lat_ready_ms": deque(maxlen=500), "lat_pub_ms": deque(maxlen=500), "compute_ms": deque(maxlen=500), "pub_t": None, "timeouts": 0, "skipped": 0}
V2_COMPUTE_MS: deque = deque(maxlen=500)
V1_HEAVY_MS: deque = deque(maxlen=200)
C2_ENABLED = os.environ.get("XAU_C2_DISABLE", "").strip() != "1"          # A/B switch for the latency comparison only; C2 is on by default
V2_TIMEOUT_S = 10.0                       # the shadow job has its OWN worker process and a short deadline: it can never hold the V1 heavy analysis back
INTEL_EVENT = threading.Event()          # set when a setup/direction/conflict timeframe bar closes: the heavy analysis must be rerun
INTEL: dict = {"payload": None, "heavy": None, "error": None, "updated_monotonic": None, "heavy_at": 0.0, "retry_at": 0.0, "seq": int(time.time() * 1000), "pub": None}      # seq starts at the wall clock (ms): it keeps increasing across gateway restarts
INTEL_MAX_AGE_S = 10.0
ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1"}        # loopback only; a foreign Host (DNS rebinding) or Origin (cross-site WebSocket) is refused
AUTH_LIMITER = authmod.RateLimiter(10, 60.0)


class _RedactToken:
    """uvicorn's access log would record the one-time `/?token=...` query string: redact it however the server was started."""
    import re as _re
    _pat = _re.compile(r"token=[^&\s\"]+")

    def filter(self, record) -> bool:
        try:
            if isinstance(record.args, tuple):
                record.args = tuple(self._pat.sub("token=REDACTED", a) if isinstance(a, str) else a for a in record.args)
            if isinstance(record.msg, str):
                record.msg = self._pat.sub("token=REDACTED", record.msg)
        except Exception:  # noqa: BLE001  logging must never break a request
            pass
        return True


import logging as _logging
_logging.getLogger("uvicorn.access").addFilter(_RedactToken())
PUBLIC_PATHS = ("/static/", "/favicon.ico")               # no secret in them; everything else needs credentials


def allowed_hosts() -> set:
    """Loopback names, plus operator-approved private names/IPs (env XAU_ALLOWED_HOSTS="mac-tunnel,100.64.1.2") but ONLY while authentication is on."""
    extra = {h.strip().lower() for h in os.environ.get("XAU_ALLOWED_HOSTS", "").split(",") if h.strip()} if authmod.auth_enabled() else set()
    return ALLOWED_HOSTS | extra


def _authority(value: str | None):
    """(hostname, port) of a Host header or an Origin URL; None when it is malformed (userinfo, bad port, empty host, non-ascii...)."""
    from urllib.parse import urlsplit
    try:
        v = value.strip()
        u = urlsplit(v if "://" in v else "//" + v)
        if u.scheme not in ("", "http", "https") or "@" in u.netloc or u.path not in ("", "/") or u.query or u.fragment:
            return None
        return (u.hostname or "").lower(), u.port
    except ValueError:
        return None


def _host_ok(value: str | None) -> bool:
    """Loopback authority only (exact names, numeric port). An absent header (non-browser client) is allowed."""
    if value is None or value == "":
        return True
    a = _authority(value)
    return a is not None and a[0] in allowed_hosts()


def _origin_matches_host(origin: str | None, host: str | None) -> bool:
    """Same-origin discipline: an Origin must be loopback AND its port must equal the Host header's port (another local web app on a different
    port is a different origin and is refused)."""
    if not origin:
        return True
    o, h = _authority(origin), _authority(host or "")
    ok = allowed_hosts()
    return o is not None and h is not None and o[0] in ok and h[0] in ok and o[1] == h[1]


def request_allowed(host: str | None, origin: str | None) -> bool:
    return host is not None and _host_ok(host) and _host_ok(origin) and _origin_matches_host(origin, host)


def publish_intel(payload: dict) -> None:
    """Single publication point: payload and its age are ONE tuple assigned atomically (a reader never pairs a payload with the wrong age)."""
    INTEL["seq"] += 1
    payload = {**payload, "seq": INTEL["seq"]}
    INTEL["pub"] = (payload, time.monotonic())
    INTEL["payload"], INTEL["updated_monotonic"] = payload, INTEL["pub"][1]          # mirrors for health()/tests; readers use `pub`


def served_intel() -> dict | None:
    """What leaves the process: the cached payload with its age; older than INTEL_MAX_AGE_S the BACKEND itself replaces it by a stale WAIT
    without setup, plan, overlays or any 'eligible/OK' field (a stalled engine must never keep serving BUY/SELL to any client)."""
    pub = INTEL["pub"]
    if pub is None:
        return None
    p, t = pub
    age = time.monotonic() - t
    if age > INTEL_MAX_AGE_S:
        d = p.get("decision") or {}
        p = {**p, "overlays": {"zone": None, "lines": [], "direction": None}, "setup_events": [], "market": None, "m1_shadow": None, "scalp_c2": None, "v1_current_id": None,
             "decision": {**d, "action": "WAIT", "primary_reason": "DATA_STALE", "layer": "gate", "setup": None, "plan": None, "risk": None, "strategy_eligible": False,
                          "next_required": "fresh data: the analysis engine has not produced a result for more than 10 s", "snapshot_time": None, "setup_bar_time": None,
                          "reasons": {"market": [], "strategy": [], "gate": ["DATA_STALE", "INTEL_ENGINE_STALLED"]}}}
    return {**p, "intel_age_s": age}


def load_cfg() -> dict:
    cfg = load_source_config()
    if os.environ.get("MT5_TERMINAL_PATH"):
        cfg["terminal_path"] = os.environ["MT5_TERMINAL_PATH"]
    return cfg


def process_tick(tk) -> None:
    """One tick through the hot path. Exceptions are contained and counted (never kill the thread, never hidden): the raw tick
    is offered to the writer BEFORE the engine runs, so a candle/publish bug cannot lose raw data."""
    try:
        for qf in tk.quality_flags:
            S.quality_counts[qf] = S.quality_counts.get(qf, 0) + 1
        if WRITER is not None:
            WRITER.offer(tk)  # raw data is kept even if flagged
        if any(f in tk.quality_flags for f in BAD_FLAGS):
            return  # flagged + counted; never used for live candles and never silently repaired
        # LATE_INSERT ticks are real ticks that arrived out of order: the engine applies them to the open bar only.
        with S.lock:
            events = S.engine.on_tick(tk.time_msc, tk.bid, tk.ask, tk.flags)
            S.last_tick = tk.to_dict()
            S.ticks_total += 1
            now = time.monotonic()
            S.rate_window.append(now)
            while S.rate_window and now - S.rate_window[0] > 5:
                S.rate_window.pop(0)
            if any(e == "close" and c.tf in INTEL_TFS for e, c in events):
                INTEL_EVENT.set()          # only a flag: the heavy work happens in the intel thread, never in this hot path
        msg = {"type": "tick", "tick": S.last_tick, "candles": [{"event": e, **c.to_dict()} for e, c in events]}
        msg["pub_ms_after_receipt"] = (time.monotonic_ns() - tk.gateway_received_ns) / 1e6
        msg["pub_wall_ms"] = time.time() * 1000.0                      # same host clock as the browser: delivery latency needs no skew correction
        msg["recv_wall_ms"] = msg["pub_wall_ms"] - msg["pub_ms_after_receipt"]
        S.lat.add(msg["pub_ms_after_receipt"])
        if LOOP is not None and S.clients:
            asyncio.run_coroutine_threadsafe(broadcast(json.dumps(msg, allow_nan=False)), LOOP)
    except Exception as e:  # noqa: BLE001
        S.pipeline_errors += 1
        S.pipeline_last_error = f"{type(e).__name__}: {e}"


def pipeline_worker(src: MT5TickSource):
    """Hot path thread: validate -> incremental candle update -> publish. Persistence is a separate thread (offer = non-blocking)."""
    while not src.stop_ev.is_set():
        S.pipeline_alive = time.monotonic()
        try:
            tk = src.q.get(timeout=0.2)
        except queue.Empty:
            continue
        process_tick(tk)


def degraded_reasons(writer) -> list[str]:
    """Reasons the feed must not be shown as plain healthy even though the terminal is connected."""
    r = []
    if S.pipeline_errors:
        r.append(f"PIPELINE_ERRORS:{S.pipeline_errors} last={S.pipeline_last_error}")
    if time.monotonic() - S.pipeline_alive > 5:
        r.append("PIPELINE_STALLED")
    if writer is not None:
        if writer.hole:
            r.append(f"PERSISTENCE_HOLE:{writer.dropped} ticks lost")
        elif writer.pending_failures:
            r.append(f"PERSISTENCE_RETRYING:{writer.pending_failures}")
    return r


async def broadcast(text: str):
    dead = []
    for ws in list(S.clients):
        try:
            await asyncio.wait_for(ws.send_text(text), timeout=1.0)
        except Exception:  # noqa: BLE001
            dead.append(ws)
    for ws in dead:
        S.clients.discard(ws)


def connection_state(st: dict, age: float | None, degraded: list[str] | None = None) -> str:
    """Separates terminal connection, identity, and data freshness. 5 s of silence is NOT 'disconnected'."""
    s = st.get("state")
    if s != "CONNECTED":
        return s or "CONNECTING"  # CONNECTING | RECOVERING | DISCONNECTED | SOURCE_MISMATCH | BLOCKED
    if not st.get("identity_verified"):
        return "SOURCE_MISMATCH"
    if degraded:
        return "DEGRADED"  # terminal connected, but our own pipeline/persistence is faulty: never plain CONNECTED_*
    if age is None:
        return "CONNECTED_IDLE"
    if age > STALE_AFTER_S:
        return "STALE"
    return "CONNECTED_IDLE" if age > IDLE_AFTER_S else "CONNECTED_ACTIVE"


def health() -> dict:
    st = dict(SOURCE.status) if SOURCE else {"state": "NOT_STARTED"}
    last = st.pop("last_data_monotonic", None)
    age = (time.monotonic() - last) if last else None
    st["gaps"] = st.get("gaps", [])[-20:]
    deg = degraded_reasons(WRITER)
    return {"connection": connection_state(st, age, deg), "degraded_reasons": deg, "detail": {k: v for k, v in st.items() if k != "account_ref"},   # the 32-bit account hash is brute-forceable: not published
             "data_age_s": age,
            "idle_after_s": IDLE_AFTER_S, "stale_after_s": STALE_AFTER_S,
            "ticks_total": S.ticks_total, "last_tick": S.last_tick, "tick_rate_hz": len(S.rate_window) / 5.0,
            "queue_depth": SOURCE.q.qsize() if SOURCE else 0, "quality_counts": S.quality_counts, "late_ticks_for_closed_bars": S.engine.late_closed_ticks,
            "gateway_latency_ms": S.lat.snapshot(),
            "latency_note": "receipt->publish inside gateway only (same-host monotonic clock); other stages measured separately",
            "persistence": {"written": WRITER.written, "dropped": WRITER.dropped, "hole": WRITER.hole, "failed_flushes": WRITER.failed_flushes, "pending_failures": WRITER.pending_failures, "errors": WRITER.errors[-3:]} if WRITER else None, "pipeline": {"errors": S.pipeline_errors, "last_error": S.pipeline_last_error},
            "intel": {"ready": INTEL["payload"] is not None, "error": INTEL["error"],
                      "age_s": (time.monotonic() - INTEL["updated_monotonic"]) if INTEL["updated_monotonic"] else None,
                      "spec_loaded": bool(SOURCE and SOURCE.spec), "account_loaded": bool(SOURCE and SOURCE.account)},   # booleans only: no account figures
            "market_session": "UNKNOWN (no session evidence yet)",
            "mode": "READ_ONLY+SHADOW+PAPER_SIMULATION", "price_basis": S.engine.price}


def seed_from_store(store: Store, symbol: str, server: str | None, max_bars=2000):
    """Seed per-timeframe history from persisted MT5 bars of THIS server/symbol only (audit risk G).
    Quarantined M1 bars stay visible but are labelled; seeded bars are never mixed into live aggregation."""
    S.engine.history = {}
    if not server:
        return {}
    from .candles import Candle
    counts = {}
    for tf in ("M1", "M5", "M15", "H1", "H4"):
        t = store.read_table(f"bars_{tf.lower()}", source_id=HIST_BARS, server=server, symbol=symbol)
        if t.num_rows == 0:
            continue
        quarantined = store.quarantined("bar_m1_parity", server, symbol) if tf == "M1" else {}
        cols = {k: t[k].to_pylist() for k in ("time", "open", "high", "low", "close", "tick_volume")}
        order = sorted(range(len(cols["time"])), key=lambda i: cols["time"][i])[-max_bars:]
        S.engine.history[tf] = [Candle(tf, cols["time"][i], cols["open"][i], cols["high"][i], cols["low"][i], cols["close"][i],
                                       cols["tick_volume"][i], state="CLOSED", source="MT5_HISTORY",
                                       completeness=("HISTORICAL_QUARANTINED" if cols["time"][i] in quarantined else "HISTORICAL"))
                                for i in order]
        counts[tf] = len(order)
    HIST_DICTS.clear()
    HIST_DICTS.update({tf: {c.t: c.to_dict() for c in cs} for tf, cs in S.engine.history.items()})
    return counts


def merged_candles(tf: str, limit: int) -> list[dict]:
    """History (MT5 bars) + live-built bars, one bar per bucket. A live bar that began mid-bucket never overrides
    complete history for that bucket; otherwise live wins (it is newer than the settled history)."""
    hist = HIST_DICTS.get(tf, {})            # history is immutable: serialized once at seed time, never rebuilt per request
    out = dict(hist)
    live = list(S.engine.closed.get(tf, []))[-limit - 2:]
    cur = S.engine.open.get(tf)
    if cur:
        live.append(cur)
    for c in live:
        if c.t in out and c.completeness == "PARTIAL_STARTED_MID_BAR" and c.state == "CLOSED":
            continue
        out[c.t] = c.to_dict()
    keys = sorted(out)[-limit:]
    return [out[t] for t in keys]


def closed_bars(tf: str) -> dict:
    """Closed bars for the analysis: MT5 history (authoritative) then live-built CLOSED bars strictly after the last history bar.
    The forming bar is never included. Copies are taken under the lock; the arrays are then private to the caller."""
    import numpy as np
    with S.lock:
        hist = list(getattr(S.engine, "history", {}).get(tf, []))
        live = list(S.engine.closed.get(tf, []))
    last = hist[-1].t if hist else -1
    rows = hist + [c for c in live if c.t > last and c.completeness != "PARTIAL_STARTED_MID_BAR"]   # a bar that began mid-bucket is never analysed
    return {k: np.array([getattr(c, a) for c in rows], dtype=float) for k, a in (("time", "t"), ("open", "o"), ("high", "h"), ("low", "l"), ("close", "c"))}


def fill_recent_bars(mt5mod, symbol: str, now_tick_time_s: int) -> dict:
    """Runs in the MT5 source thread right after a (re)connect: closed bars between the stored history and now are read from MT5 itself
    (read-only copy_rates_range) and appended in memory, so no seam gap exists between history and live-built bars."""
    from .candles import Candle, TF_SECONDS
    filled = {}
    const = {"M1": mt5mod.TIMEFRAME_M1, "M5": mt5mod.TIMEFRAME_M5, "M15": mt5mod.TIMEFRAME_M15, "H1": mt5mod.TIMEFRAME_H1, "H4": mt5mod.TIMEFRAME_H4}
    for tf, sec in TF_SECONDS.items():
        hist = S.engine.history.setdefault(tf, [])
        start = (hist[-1].t + sec) if hist else now_tick_time_s - 3 * sec * 220
        r = mt5mod.copy_rates_range(symbol, const[tf], int(start), int(now_tick_time_s))
        if r is None or len(r) == 0:
            continue
        add = [Candle(tf, int(x["time"]), float(x["open"]), float(x["high"]), float(x["low"]), float(x["close"]), int(x["tick_volume"]),
                      state="CLOSED", source="MT5_HISTORY", completeness="HISTORICAL")
               for x in r if int(x["time"]) + sec <= now_tick_time_s]          # closed bars only
        if add:
            with S.lock:
                hist.extend(add)
                HIST_DICTS.setdefault(tf, {}).update({c.t: c.to_dict() for c in add})
            filled[tf] = len(add)
    INTEL_EVENT.set()
    return filled


def load_policies():
    from xau_intel.decision.decide import GatePolicy
    from xau_intel.decision.risk import RiskPolicy
    p = ROOT / "configs" / "risk" / "policy.json"
    cfg = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    r, g = dict(cfg.get("risk", {})), dict(cfg.get("gate", {}))
    return RiskPolicy(**{k: v for k, v in r.items() if k in RiskPolicy.__dataclass_fields__}), GatePolicy(**{k: v for k, v in g.items() if k in GatePolicy.__dataclass_fields__})


SOURCE: MT5TickSource | None = None
WRITER: LiveTickWriter | None = None
LOOP: asyncio.AbstractEventLoop | None = None


_HEAVY: dict = {"pool": None, "v2pool": None, "c2pool": None}
HEAVY_TIMEOUT_S = 60.0


def _heavy_pool(key: str = "pool"):
    from concurrent.futures import ProcessPoolExecutor
    import multiprocessing as mp
    if _HEAVY.get(key) is None:
        from .workers import worker_init
        _HEAVY[key] = ProcessPoolExecutor(max_workers=1, mp_context=mp.get_context("spawn"), initializer=worker_init, initargs=(os.getpid(),))
    return _HEAVY[key]


def _discard_pool(key: str = "pool") -> None:
    """Drop the pool AND kill its worker(s): a hung worker must not survive a timeout, keep the gateway from exiting or pile up with the next ones."""
    pool, _HEAVY[key] = _HEAVY.get(key), None
    if pool is None:
        return
    procs = list(getattr(pool, "_processes", {}).values())          # grabbed first: kill_workers() clears the table
    try:
        if hasattr(pool, "kill_workers"):
            pool.kill_workers()                                       # public API (Python 3.14+)
    except Exception:  # noqa: BLE001
        pass
    for proc in procs:                                              # fallback / belt and braces (also covers older Pythons)
        try:
            proc.kill()
        except Exception:  # noqa: BLE001  already gone
            pass
    pool.shutdown(wait=False, cancel_futures=True)


def heavy_warm() -> None:
    """Start the worker process and import the analysis modules in it BEFORE the first bar close (spawn + imports take about a second)."""
    if os.environ.get("XAU_HEAVY_INPROC", "").strip() != "1":
        try:
            _heavy_pool().submit(os.getpid).result(timeout=HEAVY_TIMEOUT_S)
        except Exception:  # noqa: BLE001  the first real call reports the failure visibly
            _discard_pool()
        try:
            _heavy_pool("c2pool").submit(os.getpid).result(timeout=HEAVY_TIMEOUT_S)
        except Exception:  # noqa: BLE001
            _discard_pool("c2pool")
        try:
            _heavy_pool("v2pool").submit(os.getpid).result(timeout=HEAVY_TIMEOUT_S)     # the shadow worker too: spawn + imports must not eat its 10 s deadline
        except Exception:  # noqa: BLE001
            _discard_pool("v2pool")
    _discard_pool("c2pool")


def run_in_worker(fn, *args, key: str = "pool", timeout: float = HEAVY_TIMEOUT_S):
    """Run a pure analysis function in a worker PROCESS (GIL isolation); XAU_HEAVY_INPROC=1 keeps it in-process. Same failure handling as run_heavy.
    `key` selects the pool: the V2 shadow job uses its own ("v2pool"), so a hung shadow job never delays or kills the V1 analysis."""
    if os.environ.get("XAU_HEAVY_INPROC", "").strip() == "1":
        return fn(*args)
    try:
        return _heavy_pool(key).submit(fn, *args).result(timeout=timeout)
    except Exception:
        _discard_pool(key)
        raise


def _c2_job(bars: dict, now_server: int, m1_t: int) -> None:
    """C2 (separate strategy, own worker pool and 10 s deadline, own log, own error slot): a slow or failing C2 can never cost V2 its result."""
    from xau_intel.scalp.c2 import run_c2
    try:
        t_job = time.monotonic()
        c2 = strict(run_in_worker(run_c2, bars, now_server, key="c2pool", timeout=V2_TIMEOUT_S))
        C2["compute_ms"].append((time.monotonic() - t_job) * 1000)
        if C2["log_from"] is None:
            C2["log_from"] = now_server                              # the first compute after start: everything older is re-derived history, never evidence
        off = (SOURCE.status.get("server_utc_offset_s") if SOURCE else None)
        reg_server = None if off is None else C2_REGISTRATION_UTC + int(off)
        lf = None if reg_server is None else max(C2["log_from"], reg_server)
        C2["live_from"] = lf
        if not (SOURCE and SOURCE.status.get("server_utc_offset_fresh")):
            off = None
        path = ROOT / "data" / "scalp" / "c2_events.jsonl"
        if not C2.get("seeded"):
            C2["seen"] |= load_seen_v2(path)
            C2["seeded"] = True
        C2["logged"] += log_new_v2_events(path, c2.get("events", []), C2["seen"], lf, None, off, extra_keys=("strategy_id", "alignment", "h4_conflict", "h1", "h4", "m5_structure", "atr15"), with_v1_target=False)
        C2["result"], C2["result_t"], C2["error"] = c2, m1_t, None
        if off is not None and len(C2["compute_ms"]) > 1:                                  # the first job after a start also pays the worker spawn: not a steady-state sample
            C2["lat_ready_ms"].append(max(0.0, (time.time() - (m1_t + 60 - int(off))) * 1000))     # closed-bar eligibility -> result ready (wall clock)
    except Exception as e:  # noqa: BLE001
        C2["error"] = type(e).__name__
        C2["timeouts"] += 1                                            # failures and 10 s timeouts are counted, not silently left out of the latency sample


def _v2_job(bars: dict, now_server: int, m1_t: int, v1_active: dict | None = None) -> None:
    """Compute the shadow result (worker process, own pool, short deadline) and append new forward events. Errors are recorded by TYPE and never propagate."""
    from xau_intel.m1.entry_v2 import run_v2
    try:
        t_job = time.monotonic()
        res = strict(run_in_worker(run_v2, bars, now_server, key="v2pool", timeout=V2_TIMEOUT_S))
        V2_COMPUTE_MS.append((time.monotonic() - t_job) * 1000)
        if V2["log_from"] is None:
            V2["log_from"] = now_server                              # the first compute after start: everything older is re-derived history, never evidence
        off = (SOURCE.status.get("server_utc_offset_s") if SOURCE else None)
        reg_server = None if off is None else V2_REGISTRATION_UTC + int(off)
        lf = None if reg_server is None else max(V2["log_from"], reg_server)
        if not (SOURCE and SOURCE.status.get("server_utc_offset_fresh")):
            off = None                                           # an offset that is not fresh-HIGH never stamps a record: the evaluator resolves it from measured evidence (or excludes the event)
        path = ROOT / "data" / "shadow" / "v2_events.jsonl"
        if not V2.get("seeded"):
            V2["seen"] |= load_seen_v2(path)
            V2["seeded"] = True
        V2["logged"] += log_new_v2_events(path, res.get("events", []), V2["seen"], lf, v1_active, off)
        V2["result"], V2["result_t"], V2["error"] = res, m1_t, None
    except Exception as e:  # noqa: BLE001
        V2["error"] = type(e).__name__


def v1_event_step(dec: dict, tick: dict, now_server: int, heavy: dict) -> str | None:
    """Record the first publication of a BUY/SELL (or eligible-but-BLOCKED) decision. Returns the id of the CURRENT actionable decision (BUY/SELL right now), else None."""
    if not V1EV["seeded"]:
        evs, _bad = load_v1_events(V1_EVENTS_PATH)
        V1EV["seen"] |= {e["decision_id"] for e in evs}
        V1EV["recent"] = evs[-200:]
        V1EV["seeded"] = True
    fresh_off = SOURCE.status.get("server_utc_offset_s") if (SOURCE and SOURCE.status.get("server_utc_offset_fresh")) else None
    ev = v1_event_from_decision(dec, bid=tick.get("bid"), published_at=now_server, published_wall_ms=int(time.time() * 1000), evaluated_at=heavy.get("evaluated_at"),
                                server_utc_offset_s=fresh_off)
    if ev is not None and ev["decision_id"] not in V1EV["seen"]:
        try:
            if log_v1_events(V1_EVENTS_PATH, [ev], V1EV["seen"]):                     # remembered only after the durable write succeeded
                V1EV["recent"].append(ev)
                V1EV["recent"] = V1EV["recent"][-200:]
                V1EV["logged"] += 1
            V1EV["error"] = None
        except Exception as e:  # noqa: BLE001  a failing history log never changes the decision; the error TYPE is published as `v1_log_error` and shown on the card; retried on the next cycle
            V1EV["error"] = type(e).__name__
    return ev["decision_id"] if ev is not None and ev["action"] in ("BUY", "SELL") else None


def v2_step(tick: dict, now_server: int, heavy: dict, spread, risk_policy, gate_policy) -> dict | None:
    """M1 Entry Intelligence V2 (SHADOW). Recomputed when a new CLOSED M1 bar exists; the forming bar only feeds the display-only observation. A failure here is
    contained: it never touches the V1 decision, it just removes the shadow section (and records the exception TYPE)."""
    with S.lock:
        lst = S.engine.closed.get("M1") or []
        hist = (getattr(S.engine, "history", {}) or {}).get("M1") or []
        m1_t = max([lst[-1].t if lst else -1, hist[-1].t if hist else -1])
        cur = S.engine.open.get("M1")
        partial = None if cur is None else {"open": cur.o, "high": cur.h, "low": cur.l, "close": cur.c}
    if m1_t < 0:
        return None
    if C2_ENABLED and os.environ.get("XAU_HEAVY_INPROC", "").strip() != "1" and C2.get("m1_attempt") != m1_t:      # C2 launches on its own cadence: a slow V2 job cannot starve it
        C2["m1_attempt"] = m1_t
        if C2.get("job") is None or not C2["job"].is_alive():
            C2["job"] = threading.Thread(target=_c2_job, args=({tf: closed_bars(tf) for tf in V2_TFS}, now_server, m1_t), name="c2-shadow", daemon=True)
            C2["job"].start()
        else:
            C2["skipped"] += 1
    if V2["m1_t"] != m1_t:
        bars = {tf: closed_bars(tf) for tf in V2_TFS}
        v1_active = copy.deepcopy(heavy["status"].get("active"))      # V1 state as known NOW (at launch), not when the job finishes
        if os.environ.get("XAU_HEAVY_INPROC", "").strip() == "1":
            V2["m1_t"] = m1_t
            _v2_job(bars, now_server, m1_t, v1_active)               # tests / debugging: synchronous
            if C2_ENABLED:
                _c2_job(bars, now_server, m1_t)
            if V2["error"]:
                raise RuntimeError(V2["error"])
        elif V2["job"] is None or not V2["job"].is_alive():
            V2["m1_t"] = m1_t                                        # marked attempted only when a job really starts (also on failure: one retry per closed bar)
            V2["job"] = threading.Thread(target=_v2_job, args=(bars, now_server, m1_t, v1_active), name="v2-shadow", daemon=True)
            V2["job"].start()                                         # the intel worker publishes V1 now; the shadow section follows when the job finishes
    res = V2["result"]
    if res is None or V2["result_t"] is None or m1_t - V2["result_t"] > 60:
        return None                                                  # nothing computed yet, or older than one closed bar: show no shadow section rather than an old one
    return build_v2_view(res, partial=partial, spread=spread, v1_active=heavy["status"].get("active"), risk_policy=risk_policy, gate_policy=gate_policy, now_server=now_server)


def c2_step(tick: dict, now_server: int, spread, risk_policy, gate_policy) -> dict | None:
    """C2 view from the result the shadow job computed (same closed-M1 cadence). Missing or older than one closed bar: no section."""
    res = C2["result"]
    with S.lock:
        lst = S.engine.closed.get("M1") or []
        m1_t = lst[-1].t if lst else -1
        cur = S.engine.open.get("M1")
        partial = None if cur is None else {"t": cur.t, "open": cur.o, "high": cur.h, "low": cur.l, "close": cur.c}
    if res is None or C2["result_t"] is None or m1_t - C2["result_t"] > 60:
        return None
    off = SOURCE.status.get("server_utc_offset_s") if (SOURCE and SOURCE.status.get("server_utc_offset_fresh")) else None
    if off is not None and C2["pub_t"] != C2["result_t"]:
        C2["pub_t"] = C2["result_t"]
        if len(C2["compute_ms"]) > 1:
            C2["lat_pub_ms"].append(max(0.0, (time.time() - (C2["result_t"] + 60 - int(off))) * 1000))   # closed-bar eligibility -> first payload that carries the result
    return build_c2_view(res, partial=partial, spread=spread, risk_policy=risk_policy, gate_policy=gate_policy, now_server=now_server, live_from=C2["live_from"])


def run_heavy(bars: dict, now_server: int) -> dict:
    """The heavy recompute runs in a separate PROCESS: in the same process it holds the GIL and delays the tick path by up to ~27 ms
    (benchmarks/gil_contention.py: scheduling-delay p99 19.6 ms in-process vs 0.11 ms in a process). XAU_HEAVY_INPROC=1 keeps it in-process (tests, debugging).
    A dead or hung worker raises (the intel worker publishes INTEL_ENGINE_ERROR) and the pool is recreated for the next attempt."""
    if os.environ.get("XAU_HEAVY_INPROC", "").strip() == "1":
        return compute_heavy(bars, now_server)
    try:
        return _heavy_pool().submit(compute_heavy, bars, now_server).result(timeout=HEAVY_TIMEOUT_S)
    except Exception:
        _discard_pool()
        raise


def _error_payload(e: Exception, dataset_version: str) -> dict:
    """The record published while the engine is failing (exception TYPE only). Built defensively: if even this raised, the worker thread would die."""
    name = type(e).__name__
    try:
        ts = int(S.last_tick["time_msc"] // 1000) if S.last_tick else None
        return strict({"type": "intel", "evaluated_at": ts, "mode": "READ_ONLY+SHADOW+PAPER_SIMULATION", "overlays": {"zone": None, "lines": [], "direction": None},
                       "market": None, "analysis": {}, "setup_events": [], "bars": {},
                       "decision": {"kind": "RESEARCH_DECISION", "execution_authorized": False, "action": "WAIT", "primary_reason": "INTEL_ENGINE_ERROR", "layer": "gate",
                                    "strategy_eligible": False, "strategy_version": "n/a", "dataset_version": dataset_version, "setup": None, "plan": None, "risk": None,
                                    "next_required": "the analysis engine must recover", "reasons": {"market": [], "strategy": [], "gate": ["INTEL_ENGINE_ERROR:" + name]}}})
    except Exception:  # noqa: BLE001
        return {"type": "intel", "mode": "READ_ONLY+SHADOW+PAPER_SIMULATION", "overlays": {"zone": None, "lines": [], "direction": None}, "setup_events": [],
                "decision": {"action": "WAIT", "primary_reason": "INTEL_ENGINE_ERROR", "layer": "gate", "execution_authorized": False, "strategy_eligible": False,
                             "setup": None, "plan": None, "risk": None, "reasons": {"market": [], "strategy": [], "gate": ["INTEL_ENGINE_ERROR"]}}}


def intel_worker(src: MT5TickSource, dataset_version: str):
    """Analysis thread (never the tick hot path): heavy recompute on a closed setup/direction/conflict bar (or every 120 s as a fallback),
    cheap decision refresh every ~2 s with the CURRENT bid/spread/data age."""
    from .symbol_spec import to_symbol_spec
    risk_policy, gate_policy = load_policies()
    while not src.stop_ev.is_set():
        triggered = INTEL_EVENT.wait(timeout=2.0)
        if src.stop_ev.is_set():
            break
        try:
            tick = S.last_tick
            if tick is None:
                INTEL_EVENT.clear()          # nothing to analyse yet: do not spin on a set event
                continue
            now_server = int(tick["time_msc"] // 1000)
            if triggered or INTEL["heavy"] is None or time.monotonic() - INTEL["heavy_at"] > 120:
                if INTEL["heavy"] is None and time.monotonic() < INTEL["retry_at"]:
                    INTEL_EVENT.clear()                                # else a set event makes wait() return at once: a hot loop (review round 6b)
                    raise RuntimeError("HEAVY_RECOMPUTE_BACKOFF")      # keep publishing the error until a recompute succeeds
                INTEL_EVENT.clear()
                bars = {tf: closed_bars(tf) for tf in INTEL_TFS}
                _t_h = time.monotonic()
                INTEL["heavy"] = run_heavy(bars, now_server)
                V1_HEAVY_MS.append((time.monotonic() - _t_h) * 1000)
                INTEL["heavy_at"] = time.monotonic()
            heavy = INTEL["heavy"]
            last = src.status.get("last_data_monotonic")
            age = (time.monotonic() - last) if last else None
            spec = to_symbol_spec(src.spec) if src.spec else None
            acc = src.account or {}
            extra = ["BAR_HISTORY_FILL_FAILED"] if src.status.get("bar_fill") == "FAILED" else []
            dec = make_decision(heavy, spread=tick.get("spread"), bid=tick.get("bid"), data_age_s=age, spec=spec, equity=acc.get("equity"),
                                free_margin=acc.get("free_margin"), risk_policy=risk_policy, gate_policy=gate_policy, dataset_version=dataset_version,
                                now_server_s=now_server, extra_gates=extra)
            try:
                v2view = v2_step(tick, now_server, heavy, tick.get("spread"), risk_policy, gate_policy)
            except Exception as e2:  # noqa: BLE001  the shadow layer can never break the V1 decision
                v2view, V2["error"] = None, type(e2).__name__
            try:
                c2view = c2_step(tick, now_server, tick.get("spread"), risk_policy, gate_policy)
            except Exception as e4:  # noqa: BLE001
                c2view, C2["error"] = None, type(e4).__name__
            if dec.get("primary_reason") == "DATA_STALE":
                c2view = None
                v2view = None                                        # a stalled feed removes the shadow section at the source too, not only in the browser
            v1_current = None
            try:
                v1_current = v1_event_step(dec, tick, now_server, heavy)
            except Exception as e3:  # noqa: BLE001  the history layer can never break the decision itself
                V1EV["error"] = type(e3).__name__
            payload = strict({"type": "intel", "decision": dec, "v1_events": list(V1EV["recent"])[-V1_EVENTS_DEFAULT_LIMIT:], "v1_current_id": v1_current, "v1_log_error": V1EV["error"], "overlays": overlays(dec), "market": heavy.get("market"), "zones": heavy.get("zones", []), "m1_shadow": v2view, "scalp_c2": c2view, "c2_error": C2["error"], "c2_perf": {"eligibility_to_ready_ms": perf_stats(C2["lat_ready_ms"]), "eligibility_to_publication_ms": perf_stats(C2["lat_pub_ms"]), "c2_compute_ms": perf_stats(C2["compute_ms"]), "v2_compute_ms": perf_stats(V2_COMPUTE_MS), "v1_heavy_ms": perf_stats(V1_HEAVY_MS), "c2_enabled": C2_ENABLED, "c2_failed_or_timed_out": C2["timeouts"], "c2_bars_skipped_job_busy": C2["skipped"]},
                              "status": {k: v for k, v in heavy["status"].items() if k != "active"},
                              "analysis": {tf: {k: v.get(k) for k in ("regime", "reasons", "structure_trend", "ema_alignment", "rsi", "atr", "events_recent", "liquidity_recent")}
                                           for tf, v in heavy["analysis"].items()},
                              "setup_events": heavy["setup_events"], "setup_events_total": heavy.get("setup_events_total", 0), "setup_events_cap": len(heavy["setup_events"]), "evaluated_at": now_server, "setup_bar_time": heavy.get("setup_bar_time"),
                              "bars": heavy["bars"], "mode": "READ_ONLY+SHADOW+PAPER_SIMULATION"})
            INTEL["error"] = None
            publish_intel(payload)
        except Exception as e:  # noqa: BLE001  contained: a failing engine must be VISIBLE, never a silently frozen old decision
            INTEL["error"] = type(e).__name__               # type only: exception text could carry account numbers
            if str(e) != "HEAVY_RECOMPUTE_BACKOFF":
                INTEL["retry_at"] = time.monotonic() + 10.0    # no hot retry loop
            INTEL["heavy"] = None                          # a failed recompute never lets the pre-error setup keep producing decisions
            payload = _error_payload(e, dataset_version)
            publish_intel(payload)
        out = served_intel()
        if out is not None and LOOP is not None and S.clients:
            asyncio.run_coroutine_threadsafe(broadcast(json.dumps(out, allow_nan=False)), LOOP)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global SOURCE, WRITER, LOOP
    LOOP = asyncio.get_running_loop()
    if authmod.auth_off_requested() and not authmod.is_loopback_host(os.environ.get("XAU_HOST", "")):
        raise RuntimeError("refusing XAU_AUTH=off: it is honoured only with an explicit loopback XAU_HOST; a non-loopback binding requires authentication")
    if authmod.auth_enabled():
        authmod.ensure_token()
    heavy_warm()
    cfg = load_cfg()
    if not cfg.get("terminal_path"):
        raise RuntimeError("terminal_path missing: set configs/source.json or MT5_TERMINAL_PATH")
    symbol = cfg.get("symbol_hint", "XAUUSD")
    server = (cfg.get("expected") or {}).get("server")
    store = Store(Path(os.environ.get("XAU_DATA_DIR", ROOT / "data" / "store")))
    seed_from_store(store, symbol, server)
    session_id = store.new_session(LIVE_TICKS, server or "?", symbol, None, note="gateway start")
    WRITER = LiveTickWriter(store, LIVE_TICKS, session_id=session_id)
    WRITER.start()

    def on_connect(status: dict):  # record the server UTC offset observed for this capture session (DST-safe)
        store.set_meta(f"session:{session_id}:server_utc_offset_s", str(status.get("server_utc_offset_s")))

    def restore(srv: str, sym: str):  # keyed by the server/symbol the terminal ACTUALLY reported (e.g. XAUUSD.r), not the hint
        return store.restore_cursor(source_id=LIVE_TICKS, server=srv, symbol=sym)

    SOURCE = MT5TickSource(cfg["terminal_path"], symbol, cfg.get("expected"), on_connect=on_connect, restore_fn=restore)
    def _record_evidence(off, conf, n, res):                     # in a daemon thread: a contended sqlite write must never stall the tick-polling thread
        threading.Thread(target=add_offset_evidence, args=(store, server or "?", int(time.time()), off, conf, "gateway_live", session_id), daemon=True, name="offset-evidence").start()
    SOURCE.on_offset = _record_evidence
    SOURCE.on_spec = lambda spec: save_spec(store, spec)          # the exact broker specification is stored for offline replay
    SOURCE.bar_fill = fill_recent_bars                            # called in the source thread after each connect (read-only)
    SOURCE.status["capture_session_id"] = session_id
    SOURCE.start()
    threading.Thread(target=pipeline_worker, args=(SOURCE,), daemon=True, name="pipeline").start()
    from .storage import DATASET_VERSION
    threading.Thread(target=intel_worker, args=(SOURCE, DATASET_VERSION), daemon=True, name="intel").start()
    yield
    SOURCE.stop_ev.set()
    _discard_pool()
    _discard_pool("v2pool")
    _discard_pool("histpool")
    WRITER.stop_ev.set()
    WRITER.join(15)  # drain the buffer before exit


app = FastAPI(title="XAUUSD Gateway (read-only)", lifespan=lifespan)


@app.middleware("http")
async def loopback_host_only(request, call_next):
    if not request_allowed(request.headers.get("host"), request.headers.get("origin")):
        return Response(status_code=403, content="forbidden host/origin")
    if not authmod.auth_enabled() and not authmod.peer_is_loopback(request.client.host if request.client else None):
        # FAIL-CLOSED on the real peer address: with authentication switched off, a non-loopback peer is never served, whatever XAU_HOST / the bind say
        return Response(status_code=403, content="authentication is disabled: only loopback peers are served")
    if authmod.auth_enabled() and not request.url.path.startswith(PUBLIC_PATHS):
        token = authmod.ensure_token()
        client = request.client.host if request.client else "?"
        if request.url.path == "/" and "token" in request.query_params:          # one-time bootstrap: exchange the token for an HttpOnly session cookie
            if authmod.query_token_ok(request.query_params.get("token"), token):             # the right token always works: an attacker's failures cannot lock the owner out
                r = Response(status_code=303, headers={"location": "/"})
                r.set_cookie(authmod.COOKIE, authmod.session_value(token), httponly=True, samesite="strict", path="/", max_age=authmod.SESSION_DAYS * 86400)
                return r
            if AUTH_LIMITER.blocked(client):
                return Response(status_code=429, content="too many failed attempts")
            AUTH_LIMITER.fail(client)
            return Response(status_code=401, content="invalid token")
        if not authmod.credentials_ok(request.headers, token):
            if AUTH_LIMITER.blocked(client):
                return Response(status_code=429, content="too many failed attempts")
            if request.headers.get("authorization"):
                AUTH_LIMITER.fail(client)                                         # a wrong bearer token counts; a missing credential does not
            if request.url.path.startswith("/api/"):
                return Response(status_code=401, content='{"error":"authentication required"}', media_type="application/json")
            return Response(status_code=401, media_type="text/plain",
                            content="Authentication required. Open the URL printed by scripts/windows/run_gateway.ps1 (it carries the one-time token), or run scripts/windows/open_dashboard.ps1.")
    return await call_next(request)


@app.get("/api/health")
def api_health():
    return health()


@app.get("/api/candles/{tf}")
def api_candles(tf: str, limit: int = 500):
    if tf not in S.engine.tfs:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"unknown timeframe {tf}")
    lim = min(max(limit, 1), 5000)
    with S.lock:
        body = {"tf": tf, "candles": merged_candles(tf, lim)}
    return Response(content=json.dumps(body, separators=(",", ":")), media_type="application/json")  # skip jsonable_encoder (slow)


_IND_CACHE: dict = {}


@app.get("/api/indicators/{tf}")
def api_indicators(tf: str, limit: int = 600):
    """EMA 20/50/200 of the CLOSED bars (the same `xau_intel.indicators.ema` the analysis uses) for the chart overlays: values are defined only where the
    indicator is valid (NaN -> null). The forming bar is never included, so an overlay point never changes after it is published."""
    if tf not in S.engine.tfs:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"unknown timeframe {tf}")
    import numpy as np
    from xau_intel.indicators import ema
    lim = min(max(limit, 1), 2000)
    b = closed_bars(tf)
    n = len(b["time"])
    key = (tf, int(b["time"][-1]) if n else -1, lim)
    if key not in _IND_CACHE:
        _IND_CACHE.clear()
        out = {"tf": tf, "time": [int(x) for x in b["time"][-lim:]]}
        for p in (20, 50, 200):
            v = ema(b["close"], p)[-lim:] if n else np.array([])
            out[f"ema{p}"] = [None if not np.isfinite(x) else round(float(x), 5) for x in v]
        _IND_CACHE[key] = json.dumps(out, allow_nan=False, separators=(",", ":"))
    return Response(content=_IND_CACHE[key], media_type="application/json")


def research_status() -> dict:
    """Static research/verification status for the History & Research panel: read from the committed result files, never computed from live data."""
    def read(rel):
        try:
            return json.loads((ROOT / rel).read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return None
    p6, p7 = read("results/p6/devval.json"), read("results/p7/ml_devval.json")
    return {"v1_backtest": {"verdict": (p6 or {}).get("validation_gate", {}).get("verdict", "UNKNOWN"), "validation_trades": (p6 or {}).get("validation_gate", {}).get("c4_val_trades"),
                            "holdout": "OPENED" if (ROOT / "results" / "p6" / "holdout_opened.json").exists() else "SEALED"},
            "ml_shadow": {"verdict": (p7 or {}).get("verdict", "UNKNOWN"), "validation_auc": (((p7 or {}).get("validation") or {}).get("M1") or {}).get("auc"), "feeds_decision": False},
            "m1_entry_v2": {"status": "FORWARD_SHADOW_COLLECTING", "forward_events_logged_this_run": V2["logged"], "evaluation_rule": ">= 100 triggers AND >= 30 days after registration",
                            "performance_claim": "NONE"},
            "mt5_live": {"mode_ab": "LIVE_AB_NOT_TESTED", "indicator_parity": "PARITY_NOT_TESTED"},
            "release": "RESEARCH BETA: not a profitable trading system; no live-order capability"}


@app.get("/api/research")
def api_research():
    return Response(content=json.dumps(research_status(), allow_nan=False, separators=(",", ":")), media_type="application/json")


SETUP_HIST: dict = {"lock": threading.Lock(), "sig": None, "replay": None, "error": None, "fail_until": 0.0}
REPLAY_FAIL_BACKOFF_S = 60.0


def _store_signature(store: Store, server: str, symbol: str, tail: tuple) -> str:
    import hashlib
    h = hashlib.sha256()
    for tf in ("M15", "H1", "H4"):
        for f in store.files(f"bars_{tf.lower()}", source_id=HIST_BARS, server=server, symbol=symbol):
            h.update((f["path"] + f["sha256"]).encode())
    h.update(repr(tail).encode())
    return h.hexdigest()


def _replay_bars(store: Store, server: str, symbol: str) -> tuple[dict, tuple]:
    """Deep stored history (fixed start) + the closed bars the running gateway holds that are NEWER than the stored ones, so the replay reaches the newest closed bar."""
    import numpy as np
    from .setup_history import load_store_bars
    bars = load_store_bars(store, server, symbol)
    tail = []
    for tf in ("M15", "H1", "H4"):
        mem = closed_bars(tf)
        last = int(bars[tf]["time"][-1]) if len(bars[tf]["time"]) else -1
        if len(mem["time"]):
            newer = mem["time"] > last
            if newer.any():
                bars[tf] = {k: np.concatenate([np.asarray(bars[tf][k], dtype=float if k != "time" else np.int64), np.asarray(mem[k], dtype=float if k != "time" else np.int64)[newer]]) for k in ("time", "open", "high", "low", "close")}
        tail.append(int(bars[tf]["time"][-1]) if len(bars[tf]["time"]) else None)
    return bars, tuple(tail)


def replay_cached() -> dict | None:
    """Deterministic replay of the stored bars, cached per (store signature, newest bar per timeframe), computed in a worker process (never in the tick path).
    A failure is remembered for REPLAY_FAIL_BACKOFF_S: callers get None quickly instead of recomputing (and waiting up to 60 s) on every request."""
    cfg = load_cfg()
    server, symbol = (cfg.get("expected") or {}).get("server"), cfg.get("symbol_hint", "XAUUSD")
    if not server:
        return None
    store = Store(Path(os.environ.get("XAU_DATA_DIR", ROOT / "data" / "store")))
    with SETUP_HIST["lock"]:
        if time.monotonic() < SETUP_HIST["fail_until"]:
            return None
        from .setup_history import replay_events
        try:
            bars, tail = _replay_bars(store, server, symbol)
            sig = _store_signature(store, server, symbol, tail)
            if SETUP_HIST["sig"] == sig and SETUP_HIST["replay"] is not None:
                return SETUP_HIST["replay"]
            res = run_in_worker(replay_events, bars, key="histpool", timeout=60.0)
            SETUP_HIST.update(sig=sig, replay=res, error=None)
            return res
        except Exception as e:  # noqa: BLE001
            SETUP_HIST.update(error=type(e).__name__, fail_until=time.monotonic() + REPLAY_FAIL_BACKOFF_S)
            return None


@app.get("/api/setup_events")
def api_setup_events(frm: int | None = Query(None, alias="from"), to: int | None = None, limit: int = 500, cursor: int | None = None, replay: int = 1):
    """Setup lifecycle events (F/C/X/I/M history) for a time range, paged. Query: `frm` / `to` = known_at bounds in server-time epoch seconds, `limit` (max 2000), `cursor` = the
    `next_cursor` of the previous page. The history is the deterministic REPLAY of the stored bars (plus the newest closed bars); LIVE_ENGINE events are added only beyond what the replay reaches.
    Every event carries its provenance. Setup observations only: none is a BUY/SELL decision."""
    from .setup_history import compose, page
    heavy = INTEL.get("heavy") or {}
    live = heavy.get("setup_events_all") or []
    rep = replay_cached() if replay else None
    allev, comp = compose(live, (rep or {}).get("events", []), (rep or {}).get("coverage_end"))
    pg = page(allev, frm, to, limit, cursor)
    meta = {"kind": "SETUP_EVENTS", "execution_authorized": False, "total_events": len(allev), "live_engine_events": len(live), "replay_events": len((rep or {}).get("events", [])), "timeline": comp, "setup_version": (rep or {}).get("setup_version") or (live[0]["policy_version"] if live else None),
            "replay_bars_m15": (rep or {}).get("bars_m15"), "replay_error": SETUP_HIST["error"], "time_basis": "MT5 server time (epoch seconds); known_at = close of the confirming setup-timeframe bar",
            "note": "setup observations, not decisions; REPLAY = deterministic causal replay of stored bars (canonical history, not a live recording); LIVE_ENGINE events only beyond the replay"}
    return Response(content=json.dumps(strict({**meta, **pg}), allow_nan=False, separators=(",", ":")), media_type="application/json")


@app.get("/api/decisions")
def api_decisions(limit: int = 200):
    """V1 research decision EVENTS (history). Every record is a past publication: none of them is a current signal (the current one, if any, is `v1_current_id` of /api/intel)."""
    limit = max(1, min(int(limit), 1000))
    evs, bad = load_v1_events(V1_EVENTS_PATH, limit)
    body = {"kind": "V1_RESEARCH_DECISION_EVENTS", "historical": True, "execution_authorized": False, "events": evs, "unreadable_lines": bad, "log_schema": 1}
    return Response(content=json.dumps(strict(body), allow_nan=False, separators=(",", ":")), media_type="application/json")


@app.get("/api/intel")
def api_intel():
    out = served_intel()
    if out is None:
        return Response(content=json.dumps({"type": "intel", "status": "NOT_READY", "error": INTEL["error"]}, allow_nan=False), media_type="application/json")
    return Response(content=json.dumps(out, allow_nan=False, separators=(",", ":")), media_type="application/json")


@app.websocket("/ws")
async def ws(ws: WebSocket):
    if not request_allowed(ws.headers.get("host"), ws.headers.get("origin")):
        await ws.close(code=1008)                      # cross-site page or DNS-rebinding host: refused before accept
        return
    if not authmod.auth_enabled() and not authmod.peer_is_loopback(ws.client.host if ws.client else None):
        await ws.close(code=1008)                      # authentication off + non-loopback peer: refused (fail-closed on the real peer address)
        return
    if authmod.auth_enabled() and not authmod.credentials_ok(ws.headers, authmod.ensure_token()):
        client = ws.client.host if ws.client else "?"
        if ws.headers.get("authorization"):
            AUTH_LIMITER.fail(client)                  # a wrong bearer token on the handshake counts like on HTTP (no unthrottled guessing over /ws)
        await ws.close(code=1008)                      # unauthenticated handshake: refused before accept
        return
    await ws.accept()
    S.clients.add(ws)
    try:
        await ws.send_text(json.dumps({"type": "health", **health()}))
        out = served_intel()
        if out is not None:                            # the served payload carries its age; the backend turns an old one into a stale WAIT
            await ws.send_text(json.dumps(out, allow_nan=False))
        while True:
            await asyncio.sleep(1.0)
            await ws.send_text(json.dumps({"type": "health", **health()}))
    except (WebSocketDisconnect, Exception):  # noqa: BLE001
        S.clients.discard(ws)


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/favicon.ico")
def favicon():
    from fastapi.responses import Response
    return Response(status_code=204)


if STATIC.exists():
    app.mount("/static", StaticFiles(directory=STATIC), name="static")
