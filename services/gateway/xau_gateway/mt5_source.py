"""Mode A: official MetaTrader5 Python connector. READ-ONLY.

Only these MT5 calls are used: initialize/shutdown/terminal_info/account_info (server, trade_mode, currency, leverage; equity and free
margin are kept IN MEMORY ONLY for the risk plan and never logged, stored or exposed)/symbols_get/symbol_select/symbol_info/
symbol_info_tick/copy_ticks_from/last_error and the pure calculators order_calc_profit/order_calc_margin (they send nothing).
No order function is referenced anywhere in this module (enforced by tests/unit/test_safety.py).

Terminal isolation: the terminal path is mandatory and its identity (exe path, broker server, build, symbol) is verified
after every (re)connect against the expected values in configs/source.json (or env). On mismatch the state becomes
SOURCE_MISMATCH and NO ticks are collected; we never fall back to another terminal.
"""
import logging
import queue
import threading
import time
import MetaTrader5 as mt5

from .identity import short_hash, verify_identity
from .models import Tick, tick_quality
from .symbol_spec import account_snapshot, spec_from_mt5
from .tick_cursor import RawTick, TickCursor
from .timeutil import OffsetEstimator

log = logging.getLogger("mt5_source")
PAGE = 50000


class MT5TickSource(threading.Thread):
    def __init__(self, terminal_path: str, symbol_hint="XAUUSD", expected: dict | None = None, poll_s=0.01,
                 out_q: queue.Queue | None = None, on_connect=None, max_catchup_s: float = 600.0, restore_fn=None):
        super().__init__(daemon=True, name="mt5-source")
        if not terminal_path:
            raise ValueError("terminal_path is mandatory (several MT5 terminals may be installed)")
        self.path, self.hint, self.poll_s = terminal_path, symbol_hint, poll_s
        self.expected = expected or {}
        self.q = out_q or queue.Queue(maxsize=50000)
        self.max_catchup_s = max_catchup_s  # longer downtime is NOT replayed as live; it stays a reported gap for backfill
        self.restore_fn = restore_fn  # (server, symbol) -> TickCursor built from persisted ticks; called after the real symbol is known
        self.on_connect = on_connect  # called after each verified connect (session bookkeeping)
        self.stop_ev = threading.Event()
        self.status = {"state": "CONNECTING", "server": None, "symbol": None, "error": None, "build": None,
                       "gaps": [], "dropped": 0, "digits": None, "server_utc_offset_s": None, "account_ref": None,
                       "last_data_monotonic": None, "last_tick_msc": None, "late_inserts": 0, "reconnects": 0,
                       "terminal_connected": None, "identity_verified": False}
        self.seq = 0
        self.symbol = None
        self.cur = TickCursor()
        self.recovering = False
        self.offset = OffsetEstimator()
        self.spec: dict | None = None        # broker symbol specification snapshot (no account data)
        self.account: dict | None = None     # {"equity", "free_margin"}: memory only, never exposed
        self.on_spec = None                  # callback(spec dict) to persist the snapshot in the store
        self.bar_fill = None                 # callback(mt5 module, symbol, server time s) -> dict: fills recent closed bars (read-only)
        self._acc_t = 0.0

    def _connect(self):
        self.status["identity_verified"] = False
        if not mt5.initialize(path=self.path):
            self.status.update(state="RECOVERING" if self.status["reconnects"] else "CONNECTING", error=str(mt5.last_error()))
            return False
        ti, ai = mt5.terminal_info(), mt5.account_info()
        if ti is None:
            self.status.update(state="DISCONNECTED", error="terminal_info unavailable")
            mt5.shutdown()
            return False
        bad = verify_identity(ti, ai, self.path, self.expected)
        if bad:
            self.status.update(state="SOURCE_MISMATCH", error=bad)
            mt5.shutdown()  # collect nothing from an unexpected terminal
            return False
        self.status["terminal_connected"] = bool(ti.connected)
        if not ti.connected:
            self.status.update(state="DISCONNECTED", error="terminal not connected to broker")
            mt5.shutdown()
            return False
        syms = [s.name for s in (mt5.symbols_get(f"*{self.hint}*") or [])]
        sym = (next((s for s in syms if s.upper() == self.hint.upper()), None)
               or next((s for s in syms if s.upper().startswith(self.hint.upper())), None))
        if not sym:
            self.status.update(state="BLOCKED", error=f"no symbol matching {self.hint}")
            mt5.shutdown()
            return False
        mt5.symbol_select(sym, True)
        si = mt5.symbol_info(sym)
        self.symbol = sym
        self.status.update(server=ai.server if ai else None, symbol=sym, error=None, build=ti.build, digits=si.digits,
                           point=si.point, tick_size=si.trade_tick_size, account_is_demo=(ai.trade_mode == 0) if ai else None,
                           account_ref=short_hash(ai.login) if ai else None, terminal_trade_allowed=ti.trade_allowed,
                           identity_verified=True)
        tk = mt5.symbol_info_tick(sym)
        self.connect_tick_msc = int(tk.time_msc) if tk else None   # server-time reference; no UTC conversion needed for catch-up/gaps
        if tk:  # informational only: carries a confidence, never used for integrity decisions
            self.offset.set_provisional(tk.time, time.time())
            self._publish_offset()
        try:
            self.spec = spec_from_mt5(mt5, sym)
            self.account = account_snapshot(mt5)
            self._acc_t = time.monotonic()
            if self.spec and self.on_spec:
                self.on_spec(self.spec)
        except Exception:  # noqa: BLE001  the spec is optional input of the risk plan: without it the plan is RISK_NOT_EVALUABLE
            log.exception("symbol spec / account snapshot failed")
        if self.on_connect:
            self.on_connect(dict(self.status))
        return True

    # ---- emit
    def _publish_offset(self):
        off, conf, res, n = self.offset.snapshot()
        self.status.update(server_utc_offset_s=off, server_utc_offset_confidence=conf, server_utc_offset_samples=n,
                           server_utc_offset_residual_s=None if res is None else round(res, 2))

    def _emit(self, rt: RawTick, late: bool):
        self.seq += 1
        qf = tick_quality(rt.bid, rt.ask, None, rt.time_msc)  # ordering is judged by the cursor (late flag), not here
        if late:
            qf = qf + ("LATE_INSERT",)
        tk = Tick("mt5_py_poll", self.status["server"] or "?", self.symbol, rt.time_msc, rt.bid, rt.ask, rt.last,
                  rt.volume, rt.flags, self.seq, time.monotonic_ns(), qf)
        try:
            self.q.put_nowait(tk)
        except queue.Full:
            self.status["dropped"] += 1
            self.status["queue_full_events"] = self.status.get("queue_full_events", 0) + 1
            if len(self.status["gaps"]) < 1000:   # bounded memory: the counters keep the truth beyond this
                self.status["gaps"].append({"kind": "GATEWAY_QUEUE_FULL", "seq": self.seq, "time_msc": rt.time_msc})

    def run(self):
        backoff = 1.0
        while not self.stop_ev.is_set():
            if not self._connect():
                if self.status["state"] == "SOURCE_MISMATCH":
                    self.stop_ev.wait(30)  # keep reporting the mismatch, do not hammer
                else:
                    self.stop_ev.wait(backoff)
                    backoff = min(backoff * 2, 15)
                continue
            backoff = 1.0
            if self.restore_fn and not self.cur.watermark_msc and self.status["server"] and self.symbol:
                self.cur = self.restore_fn(self.status["server"], self.symbol)
            ref = self.connect_tick_msc
            if self.cur.watermark_msc and ref is not None:
                behind_s = (ref - self.cur.watermark_msc) / 1000     # server time vs server time
                if behind_s > self.max_catchup_s:
                    self.status["gaps"].append({"kind": "RESTART_GAP_NOT_RECOVERED_LIVE", "seconds": round(behind_s),
                                                "from_msc": self.cur.watermark_msc, "action": "fill via backfill"})
                    self.cur = TickCursor(self.cur.overlap_ms)  # cold start; the hole is reported, never hidden
            if not self.cur.watermark_msc and ref is not None:
                # Cold start: replay the last 2 minutes (server time) so the current M1 bar is as complete as available.
                self.cur.initial_from_msc = ref - 120_000
            else:
                kind = "RECONNECT_CATCHUP" if self.status["reconnects"] else "RESTART_RECOVERY_FROM_PERSISTED_WATERMARK"
                self.status["gaps"].append({"kind": kind, "from_msc": self.cur.fetch_from_msc()})
            if self.bar_fill and ref is not None:
                try:   # read-only: closed bars between the stored history and now (no seam between history and live-built bars)
                    self.status["bar_fill"] = self.bar_fill(mt5, self.symbol, int(ref // 1000))
                except Exception:  # noqa: BLE001
                    log.exception("recent bar fill failed")
                    self.status["bar_fill"] = "FAILED"
            try:
                self._loop()
            except Exception as e:  # noqa: BLE001
                log.exception("source loop error")
                self.status.update(state="DISCONNECTED", error=repr(e))
            finally:
                mt5.shutdown()
            self.status["reconnects"] += 1
            self.recovering = True

    def _read(self, from_msc: int):
        arr = mt5.copy_ticks_from(self.symbol, from_msc // 1000, PAGE, mt5.COPY_TICKS_ALL)
        if arr is None:
            return None
        return [RawTick(int(t["time_msc"]), float(t["bid"]), float(t["ask"]), float(t["last"]), int(t["volume"]),
                        int(t["flags"])) for t in arr]

    def _loop(self):
        steady = False   # first iteration after (re)connect replays catch-up ticks: those are old, not offset samples
        while not self.stop_ev.is_set():
            cont = False
            while True:  # page forward while pages come back full (catch-up after downtime)
                rows = self._read(self.cur.fetch_from_msc(cont))
                if rows is None:
                    self.status.update(state="RECOVERING", error=str(mt5.last_error()))
                    return
                emitted = self.cur.ingest(rows, cont)
                for e in emitted:
                    self._emit(e.tick, e.late)
                    if e.late:
                        self.status["late_inserts"] += 1
                if emitted:
                    if steady and not cont and len(emitted) <= 50:  # a tick that first appeared now is fresh: valid offset sample
                        self.offset.add_fresh(emitted[-1].tick.time_msc / 1000, time.time())
                        self._publish_offset()
                    self.status["last_data_monotonic"] = time.monotonic()
                    self.status["last_tick_msc"] = self.cur.watermark_msc
                if len(rows) < PAGE:
                    break
                cont = True
            term = mt5.terminal_info()
            self.status["terminal_connected"] = bool(term and term.connected)
            if term is None or not term.connected:
                self.status.update(state="RECOVERING", error="broker connection lost")
                return
            self.status.update(state="CONNECTED", error=None)
            steady = True
            if time.monotonic() - self._acc_t > 30:      # refresh equity / free margin from THIS thread only (no parallel terminal calls)
                self._acc_t = time.monotonic()
                try:
                    self.account = account_snapshot(mt5)
                except Exception:  # noqa: BLE001
                    self.account = None
            self.stop_ev.wait(self.poll_s)
