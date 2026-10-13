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
from .latency import LatencyStats
from .mt5_source import MT5TickSource
from .identity import load_source_config
from .quality import HIST_BARS, LIVE_TICKS
from .storage import LiveTickWriter, Store

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
        msg = {"type": "tick", "tick": S.last_tick, "candles": [{"event": e, **c.to_dict()} for e, c in events]}
        msg["pub_ms_after_receipt"] = (time.monotonic_ns() - tk.gateway_received_ns) / 1e6
        S.lat.add(msg["pub_ms_after_receipt"])
        if LOOP is not None and S.clients:
            asyncio.run_coroutine_threadsafe(broadcast(json.dumps(msg)), LOOP)
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
    SOURCE.status["capture_session_id"] = session_id
    SOURCE.start()
    threading.Thread(target=pipeline_worker, args=(SOURCE,), daemon=True, name="pipeline").start()
    yield
    SOURCE.stop_ev.set()
    WRITER.stop_ev.set()
    WRITER.join(15)  # drain the buffer before exit


app = FastAPI(title="XAUUSD Gateway (read-only)", lifespan=lifespan)


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


@app.websocket("/ws")
async def ws(ws: WebSocket):
    await ws.accept()
    S.clients.add(ws)
    try:
        await ws.send_text(json.dumps({"type": "health", **health()}))
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
