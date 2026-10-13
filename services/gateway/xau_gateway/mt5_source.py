"""Mode A: official MetaTrader5 Python connector. READ-ONLY.

Only these MT5 calls are used: initialize/shutdown/terminal_info/account_info (server + trade_mode only)/
symbols_get/symbol_select/symbol_info/symbol_info_tick/copy_ticks_from/last_error.
No order function is referenced anywhere in this module (enforced by tests/unit/test_safety.py).

Terminal isolation: the terminal path is mandatory and its identity (exe path, broker server, build, symbol) is verified
after every (re)connect against the expected values in configs/source.json (or env). On mismatch the state becomes
SOURCE_MISMATCH and NO ticks are collected; we never fall back to another terminal.
"""
import hashlib
import logging
import queue
import threading
import time
from pathlib import Path

import MetaTrader5 as mt5

from .models import Tick, tick_quality
from .tick_cursor import RawTick, TickCursor

log = logging.getLogger("mt5_source")
PAGE = 50000


def short_hash(x) -> str:
    return hashlib.sha256(str(x).encode()).hexdigest()[:8]  # account id is never logged in clear


class MT5TickSource(threading.Thread):
    def __init__(self, terminal_path: str, symbol_hint="XAUUSD", expected: dict | None = None, poll_s=0.01,
                 out_q: queue.Queue | None = None, checkpoint: Path | None = None):
        super().__init__(daemon=True, name="mt5-source")
        if not terminal_path:
            raise ValueError("terminal_path is mandatory (several MT5 terminals may be installed)")
        self.path, self.hint, self.poll_s = terminal_path, symbol_hint, poll_s
        self.expected = expected or {}
        self.q = out_q or queue.Queue(maxsize=50000)
        self.checkpoint = checkpoint
        self.stop_ev = threading.Event()
        self.status = {"state": "CONNECTING", "server": None, "symbol": None, "error": None, "build": None,
                       "gaps": [], "dropped": 0, "digits": None, "server_utc_offset_s": None, "account_ref": None,
                       "last_data_monotonic": None, "last_tick_msc": None, "late_inserts": 0, "reconnects": 0,
                       "terminal_connected": None, "identity_verified": False}
        self.seq = 0
        self.symbol = None
        self.cur = TickCursor()
        self.recovering = False

    # ---- identity
    def _verify_identity(self, ti, ai) -> str | None:
        exp = self.expected
        if Path(ti.path).resolve() != Path(self.path).resolve().parent:
            return f"terminal path {ti.path} != configured {Path(self.path).parent}"
        if exp.get("server") and (ai is None or ai.server != exp["server"]):
            return f"server {getattr(ai, 'server', None)} != expected {exp['server']}"
        if exp.get("build") and ti.build != exp["build"]:
            return f"build {ti.build} != expected {exp['build']}"
        if exp.get("account_ref") and ai is not None and short_hash(ai.login) != exp["account_ref"]:
            return "account identity differs from the pinned account_ref"
        return None

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
        bad = self._verify_identity(ti, ai)
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
        if tk:  # server UTC offset estimate (tick server-time vs local UTC), rounded to 15 min
            self.status["server_utc_offset_s"] = int(round((tk.time - time.time()) / 900) * 900)
        return True

    # ---- emit
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
            off = self.status["server_utc_offset_s"]
            if not self.cur.watermark_msc and off is not None:
                # Cold start: replay the last 2 minutes so the current M1 bar is as complete as available.
                self.cur.initial_from_msc = int((time.time() + off - 120) * 1000)
            elif self.status["reconnects"]:
                self.status["gaps"].append({"kind": "RECONNECT_CATCHUP", "from_msc": self.cur.fetch_from_msc()})
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
            self._save_checkpoint()
            self.stop_ev.wait(self.poll_s)

    def _save_checkpoint(self):
        if self.checkpoint and time.monotonic() - getattr(self, "_ck_t", 0) > 5:
            self._ck_t = time.monotonic()
            tmp = self.checkpoint.with_suffix(".tmp")
            tmp.write_text(self.cur.to_json(), encoding="utf-8")
            tmp.replace(self.checkpoint)  # atomic on NTFS
