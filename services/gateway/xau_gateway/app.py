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
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .candles import CandleEngine
from .latency import LatencyStats
from .mt5_source import MT5TickSource
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


S = State()
SOURCE: MT5TickSource | None = None
WRITER: LiveTickWriter | None = None
LOOP: asyncio.AbstractEventLoop | None = None


def load_cfg() -> dict:
    p = ROOT / "configs" / "source.json"
    cfg = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    if os.environ.get("MT5_TERMINAL_PATH"):
        cfg["terminal_path"] = os.environ["MT5_TERMINAL_PATH"]
    return cfg


def pipeline_worker(src: MT5TickSource):
    """Hot path: validate -> incremental candle update -> publish. Persistence is a separate thread (offer = non-blocking)."""
    while not src.stop_ev.is_set():
        try:
            tk = src.q.get(timeout=0.2)
        except queue.Empty:
            continue
        for qf in tk.quality_flags:
            S.quality_counts[qf] = S.quality_counts.get(qf, 0) + 1
        if WRITER is not None:
            WRITER.offer(tk)  # raw data is kept even if flagged
        if any(f in tk.quality_flags for f in BAD_FLAGS):
            continue  # flagged + counted; never used for live candles and never silently repaired
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


async def broadcast(text: str):
    dead = []
    for ws in list(S.clients):
        try:
            await asyncio.wait_for(ws.send_text(text), timeout=1.0)
        except Exception:  # noqa: BLE001
            dead.append(ws)
    for ws in dead:
        S.clients.discard(ws)


def connection_state(st: dict, age: float | None) -> str:
    """Separates terminal connection, identity, and data freshness. 5 s of silence is NOT 'disconnected'."""
    s = st.get("state")
    if s != "CONNECTED":
        return s or "CONNECTING"  # CONNECTING | RECOVERING | DISCONNECTED | SOURCE_MISMATCH | BLOCKED
    if not st.get("identity_verified"):
        return "SOURCE_MISMATCH"
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
    return {"connection": connection_state(st, age), "detail": st, "data_age_s": age,
            "idle_after_s": IDLE_AFTER_S, "stale_after_s": STALE_AFTER_S,
            "ticks_total": S.ticks_total, "tick_rate_hz": len(S.rate_window) / 5.0,
            "queue_depth": SOURCE.q.qsize() if SOURCE else 0, "quality_counts": S.quality_counts, "late_ticks_for_closed_bars": S.engine.late_closed_ticks,
            "gateway_latency_ms": S.lat.snapshot(),
            "latency_note": "receipt->publish inside gateway only (same-host monotonic clock); other stages measured separately",
            "persistence": {"written": WRITER.written, "dropped": WRITER.dropped, "errors": WRITER.errors[-3:]} if WRITER else None,
            "market_session": "UNKNOWN (no session evidence yet)",
            "mode": "READ_ONLY+SHADOW+PAPER_SIMULATION", "price_basis": S.engine.price}


def seed_from_store(store: Store, symbol: str, max_bars=1500):
    """Backfill the in-memory M1 history from persisted MT5 bars so the chart has real history.
    Seeded bars are marked source=MT5_HISTORY / completeness=HISTORICAL and are never mixed into live aggregation."""
    t = store.read_table("bars_m1")
    if t.num_rows == 0:
        return 0
    from .candles import Candle
    cols = {k: t[k].to_pylist() for k in ("time", "open", "high", "low", "close", "tick_volume")}
    order = sorted(range(len(cols["time"])), key=lambda i: cols["time"][i])[-max_bars:]
    S.engine.history = [Candle("M1", cols["time"][i], cols["open"][i], cols["high"][i], cols["low"][i], cols["close"][i],
                               cols["tick_volume"][i], state="CLOSED", source="MT5_HISTORY", completeness="HISTORICAL") for i in order]
    return len(order)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global SOURCE, WRITER, LOOP
    LOOP = asyncio.get_running_loop()
    cfg = load_cfg()
    if not cfg.get("terminal_path"):
        raise RuntimeError("terminal_path missing: set configs/source.json or MT5_TERMINAL_PATH")
    store = Store(Path(os.environ.get("XAU_DATA_DIR", ROOT / "data" / "store")))
    seed_from_store(store, cfg.get("symbol_hint", "XAUUSD"))
    WRITER = LiveTickWriter(store)
    WRITER.start()
    ck = Path(store.root / "cursor.json")
    SOURCE = MT5TickSource(cfg["terminal_path"], cfg.get("symbol_hint", "XAUUSD"), cfg.get("expected"), checkpoint=ck)
    if ck.exists():
        from .tick_cursor import TickCursor
        SOURCE.cur = TickCursor.from_json(ck.read_text(encoding="utf-8"))
        SOURCE.status["gaps"].append({"kind": "RESTART_FROM_CHECKPOINT", "watermark_msc": SOURCE.cur.watermark_msc})
    SOURCE.start()
    threading.Thread(target=pipeline_worker, args=(SOURCE,), daemon=True, name="pipeline").start()
    yield
    SOURCE.stop_ev.set()
    WRITER.stop_ev.set()


app = FastAPI(title="XAUUSD Gateway (read-only)", lifespan=lifespan)


@app.get("/api/health")
def api_health():
    return health()


@app.get("/api/candles/{tf}")
def api_candles(tf: str, limit: int = 500):
    with S.lock:
        closed = [c.to_dict() for c in S.engine.closed.get(tf, [])[-limit:]]
        cur = S.engine.open.get(tf)
        hist = []
        if tf == "M1":  # persisted MT5 bars strictly older than the first locally built bar; sources stay labelled
            first_live = closed[0]["time"] if closed else (cur.t if cur else None)
            hist = [c.to_dict() for c in getattr(S.engine, "history", []) if first_live is None or c.t < first_live]
        return {"tf": tf, "candles": hist[-limit:] + closed + ([cur.to_dict()] if cur else [])}


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
