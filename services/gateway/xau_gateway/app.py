"""FastAPI gateway: MT5 ticks -> candle engine -> WebSocket (+ off-path Parquet persistence).
Read-only API (GET + WS only), bound to 127.0.0.1 by default. No trading logic lives here."""
import asyncio
import json
import os
import queue
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from .candles import CandleEngine
from .intel_logic import compute_heavy, make_decision, overlays, strict
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
INTEL_EVENT = threading.Event()          # set when a setup/direction/conflict timeframe bar closes: the heavy analysis must be rerun
INTEL: dict = {"payload": None, "heavy": None, "error": None, "updated_monotonic": None, "heavy_at": 0.0, "retry_at": 0.0, "seq": 0}
INTEL_MAX_AGE_S = 10.0
ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1", "testserver"}        # loopback only; a foreign Host (DNS rebinding) or Origin (cross-site WebSocket) is refused


def _host_ok(value: str | None) -> bool:
    if not value:
        return True                                   # non-browser clients send no Origin
    v = value.split("://", 1)[-1].split("/", 1)[0]
    host = v[1:v.index("]")] if v.startswith("[") else v.rsplit(":", 1)[0] if v.count(":") == 1 else v
    return host in ALLOWED_HOSTS


def publish_intel(payload: dict) -> None:
    """Single publication point: the age timestamp is written BEFORE the payload so a reader never sees a payload without its age."""
    INTEL["seq"] += 1
    payload = {**payload, "seq": INTEL["seq"]}
    INTEL["updated_monotonic"] = time.monotonic()
    INTEL["payload"] = payload


def served_intel() -> dict | None:
    """What leaves the process: the cached payload with its age; older than INTEL_MAX_AGE_S the BACKEND itself replaces it by a stale WAIT
    without setup, plan or overlays (a stalled engine must never keep serving BUY/SELL to any client)."""
    p, t = INTEL["payload"], INTEL["updated_monotonic"]
    if p is None or t is None:
        return None
    age = time.monotonic() - t
    if age > INTEL_MAX_AGE_S:
        d = p.get("decision") or {}
        p = {**p, "overlays": {"zone": None, "lines": [], "direction": None},
             "decision": {**d, "action": "WAIT", "primary_reason": "DATA_STALE", "layer": "gate", "setup": None, "plan": None,
                          "reasons": {"market": [], "strategy": [], "gate": ["DATA_STALE", "INTEL_ENGINE_STALLED"]}}}
    return {**p, "intel_age_s": age}
SOURCE: MT5TickSource | None = None
WRITER: LiveTickWriter | None = None
LOOP: asyncio.AbstractEventLoop | None = None


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
    return {"connection": connection_state(st, age, deg), "degraded_reasons": deg, "detail": st, "data_age_s": age,
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
                    raise RuntimeError("HEAVY_RECOMPUTE_BACKOFF")      # keep publishing the error until a recompute succeeds
                INTEL_EVENT.clear()
                bars = {tf: closed_bars(tf) for tf in INTEL_TFS}
                INTEL["heavy"] = compute_heavy(bars, now_server)
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
            payload = strict({"type": "intel", "decision": dec, "overlays": overlays(dec), "market": heavy.get("market"),
                              "status": {k: v for k, v in heavy["status"].items() if k != "active"},
                              "analysis": {tf: {k: v.get(k) for k in ("regime", "reasons", "structure_trend", "ema_alignment", "rsi", "atr", "events_recent", "liquidity_recent")}
                                           for tf, v in heavy["analysis"].items()},
                              "setup_events": heavy["setup_events"], "evaluated_at": now_server, "setup_bar_time": heavy.get("setup_bar_time"),
                              "bars": heavy["bars"], "mode": "READ_ONLY+SHADOW+PAPER_SIMULATION"})
            INTEL["error"] = None
            publish_intel(payload)
        except Exception as e:  # noqa: BLE001  contained: a failing engine must be VISIBLE, never a silently frozen old decision
            INTEL["error"] = type(e).__name__               # type only: exception text could carry account numbers
            if str(e) != "HEAVY_RECOMPUTE_BACKOFF":
                INTEL["retry_at"] = time.monotonic() + 10.0    # no hot retry loop
            INTEL["heavy"] = None                          # a failed recompute never lets the pre-error setup keep producing decisions
            payload = strict({"type": "intel", "evaluated_at": int(S.last_tick["time_msc"] // 1000) if S.last_tick else None, "mode": "READ_ONLY+SHADOW+PAPER_SIMULATION",
                              "overlays": {"zone": None, "lines": [], "direction": None}, "market": None, "analysis": {}, "setup_events": [], "bars": {},
                              "decision": {"kind": "RESEARCH_DECISION", "execution_authorized": False, "action": "WAIT", "primary_reason": "INTEL_ENGINE_ERROR",
                                           "layer": "gate", "strategy_eligible": False, "strategy_version": "n/a", "dataset_version": dataset_version, "setup": None, "plan": None,
                                           "risk": None, "reasons": {"market": [], "strategy": [], "gate": ["INTEL_ENGINE_ERROR:" + type(e).__name__]}}})
            publish_intel(payload)
        out = served_intel()
        if out is not None and LOOP is not None and S.clients:
            asyncio.run_coroutine_threadsafe(broadcast(json.dumps(out, allow_nan=False)), LOOP)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global SOURCE, WRITER, LOOP
    LOOP = asyncio.get_running_loop()
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
    SOURCE.on_spec = lambda spec: save_spec(store, spec)          # the exact broker specification is stored for offline replay
    SOURCE.bar_fill = fill_recent_bars                            # called in the source thread after each connect (read-only)
    SOURCE.status["capture_session_id"] = session_id
    SOURCE.start()
    threading.Thread(target=pipeline_worker, args=(SOURCE,), daemon=True, name="pipeline").start()
    from .storage import DATASET_VERSION
    threading.Thread(target=intel_worker, args=(SOURCE, DATASET_VERSION), daemon=True, name="intel").start()
    yield
    SOURCE.stop_ev.set()
    WRITER.stop_ev.set()
    WRITER.join(15)  # drain the buffer before exit


app = FastAPI(title="XAUUSD Gateway (read-only)", lifespan=lifespan)


@app.middleware("http")
async def loopback_host_only(request, call_next):
    if not _host_ok(request.headers.get("host")) or not _host_ok(request.headers.get("origin")):
        return Response(status_code=403, content="forbidden host/origin")
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


@app.get("/api/intel")
def api_intel():
    out = served_intel()
    if out is None:
        return Response(content=json.dumps({"type": "intel", "status": "NOT_READY", "error": INTEL["error"]}, allow_nan=False), media_type="application/json")
    return Response(content=json.dumps(out, allow_nan=False, separators=(",", ":")), media_type="application/json")


@app.websocket("/ws")
async def ws(ws: WebSocket):
    if not (_host_ok(ws.headers.get("origin")) and _host_ok(ws.headers.get("host"))):
        await ws.close(code=1008)                      # cross-site page or DNS-rebinding host: refused before accept
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
