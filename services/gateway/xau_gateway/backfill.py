"""Historical backfill (read-only): MT5 M1 rates and ticks, chunked by UTC-hour of server time, resumable and idempotent.

CLI:  python -m xau_gateway.backfill --terminal "C:\\Program Files\\MetaTrader 5\\terminal64.exe" --hours 24 --bars-days 7
Recent hours (newer than --settle-s) are skipped: MT5 tick history is back-filled late (see docs/qa/M1_BAR_MISMATCH_RCA.md).
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import MetaTrader5 as mt5
import numpy as np

from .identity import load_source_config, verify_identity
from .storage import BAR_SCHEMA, DATASET_VERSION, TICK_SCHEMA, Store

HOUR = 3600


def _connect(path: str, expected: dict | None):
    """Same identity check as the live source (identity.verify_identity). Raises on SOURCE_MISMATCH; nothing is read."""
    if not mt5.initialize(path=path):
        raise RuntimeError(f"initialize failed: {mt5.last_error()}")
    bad = verify_identity(mt5.terminal_info(), mt5.account_info(), path, expected)
    if bad:
        mt5.shutdown()
        raise RuntimeError(f"SOURCE_MISMATCH: {bad}")
    return mt5.account_info().server


def backfill_ticks(store: Store, symbol: str, server: str, hours: int, settle_s: int, rate_limit_s=0.05, log=print):
    ti = mt5.symbol_info_tick(symbol)
    now = ti.time
    last_full = (now - settle_s) // HOUR * HOUR           # exclusive end: only hours fully older than settle window
    first = last_full - hours * HOUR
    res = {"written": 0, "identical": 0, "superseded_old": 0, "empty": 0, "rows": 0, "chunks": 0}
    for h in range(first, last_full, HOUR):
        t = mt5.copy_ticks_range(symbol, h, h + HOUR + 2, mt5.COPY_TICKS_ALL)
        if t is None:
            raise RuntimeError(f"copy_ticks_range failed: {mt5.last_error()}")
        t = t[(t["time_msc"] >= h * 1000) & (t["time_msc"] < (h + HOUR) * 1000)]  # exact [h, h+1h) window, ms precision
        n = len(t)
        if n == 0:
            res["empty"] += 1
            store.quarantine("tick_chunk", h, "EMPTY_HOUR", "no ticks returned (market closed or history missing)")
            continue
        q = np.where((t["bid"] <= 0) | (t["ask"] <= 0) | (t["bid"] > t["ask"]), "INVALID_QUOTE", "")
        cols = {"source_id": ["mt5_hist_ticks"] * n, "terminal_ref": [""] * n, "server": [server] * n,
                "symbol": [symbol] * n, "time_msc": t["time_msc"].astype("int64").tolist(), "bid": t["bid"].tolist(),
                "ask": t["ask"].tolist(), "last": t["last"].tolist(), "volume": t["volume"].astype("int64").tolist(),
                "flags": t["flags"].astype("int32").tolist(), "received_at_ns": [0] * n, "quality_flags": q.tolist(),
                "dataset_version": [DATASET_VERSION] * n, "capture_session_id": [""] * n,
                "provenance": ["MT5_HISTORY_TICKS"] * n}
        r = store.write_chunk("ticks", TICK_SCHEMA, cols, source_id="mt5_hist_ticks", server=server, symbol=symbol,
                              chunk=f"h{h}", key_col="time_msc", partition=f"date={time.strftime('%Y-%m-%d', time.gmtime(h))}")
        res[r["status"]] += 1
        res["rows"] += n
        res["chunks"] += 1
        store.set_checkpoint(f"ticks:{symbol}:last_hour", str(h))
        log(f"ticks hour {time.strftime('%Y-%m-%d %H:00', time.gmtime(h))}  rows={n:6d}  {r['status']}")
        time.sleep(rate_limit_s)
    res["range_server_time"] = [first, last_full]
    return res


def backfill_m1(store: Store, symbol: str, server: str, days: int, settle_s: int, log=print):
    ti = mt5.terminal_info()
    now = mt5.symbol_info_tick(symbol).time
    end = (now - settle_s) // 60 * 60
    start = end - days * 86400
    res = {"bars": 0, "chunks": 0, "identical": 0, "written": 0, "superseded_old": 0, "terminal_maxbars": ti.maxbars}
    day0 = start // 86400 * 86400
    for d in range(day0, end, 86400):
        a, b = max(d, start), min(d + 86400, end)
        r = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_M1, a, b - 1)
        if r is None or len(r) == 0:
            store.quarantine("bar_day", d, "NO_BARS", "copy_rates_range returned nothing")
            continue
        n = len(r)
        cols = {"source_id": ["mt5_hist_bars"] * n, "server": [server] * n, "symbol": [symbol] * n, "tf": ["M1"] * n,
                "time": r["time"].astype("int64").tolist(), "open": r["open"].tolist(), "high": r["high"].tolist(),
                "low": r["low"].tolist(), "close": r["close"].tolist(), "tick_volume": r["tick_volume"].astype("int64").tolist(),
                "spread": r["spread"].astype("int32").tolist(), "real_volume": r["real_volume"].astype("int64").tolist(),
                "dataset_version": [DATASET_VERSION] * n}
        w = store.write_chunk("bars_m1", BAR_SCHEMA, cols, source_id="mt5_hist_bars", server=server, symbol=symbol,
                              chunk=f"d{d}", key_col="time", partition=f"date={time.strftime('%Y-%m-%d', time.gmtime(d))}")
        res[w["status"]] += 1
        res["bars"] += n
        res["chunks"] += 1
        log(f"bars day {time.strftime('%Y-%m-%d', time.gmtime(d))} n={n} {w['status']}")
    store.set_checkpoint(f"bars:{symbol}:last_end", str(end))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--terminal", default=None, help="default: terminal_path from configs/source.json")
    ap.add_argument("--symbol", default="XAUUSD")
    ap.add_argument("--server", default=None, help="override expected broker server (default: configs/source.json)")
    ap.add_argument("--root", default=str(Path(__file__).resolve().parents[3] / "data" / "store"))
    ap.add_argument("--hours", type=int, default=24)
    ap.add_argument("--bars-days", type=int, default=7)
    ap.add_argument("--htf", action="store_true", help="also backfill native M5/M15/H1/H4 bars (default depth per timeframe)")
    ap.add_argument("--settle-s", type=int, default=900)
    a = ap.parse_args()
    cfg = load_source_config()
    terminal = a.terminal or cfg.get("terminal_path")
    if not terminal:
        raise SystemExit("no terminal: pass --terminal or create configs/source.json")
    expected = dict(cfg.get("expected") or {})
    if a.server:
        expected["server"] = a.server
    if not expected.get("server"):
        raise SystemExit("no expected server pinned: refusing to backfill from an unverified source")
    server = _connect(terminal, expected)
    try:
        mt5.symbol_select(a.symbol, True)
        store = Store(Path(a.root))
        si = mt5.symbol_info(a.symbol)
        store.set_meta(f"symbol:{a.symbol}:tick_size", str(si.trade_tick_size))  # used by quality checks (no hardcoded 0.01)
        store.set_meta(f"symbol:{a.symbol}:digits", str(si.digits))
        out = {"ticks": backfill_ticks(store, a.symbol, server, a.hours, a.settle_s),
               "bars": backfill_m1(store, a.symbol, server, a.bars_days, a.settle_s)}
        if a.htf:
            out["htf"] = {tf: backfill_bars(store, a.symbol, server, tf, d, a.settle_s) for tf, d in HTF_DEFAULT_DAYS.items()}
        print(json.dumps(out, indent=1))
    finally:
        mt5.shutdown()



MT5_TF = {"M1": "TIMEFRAME_M1", "M5": "TIMEFRAME_M5", "M15": "TIMEFRAME_M15", "H1": "TIMEFRAME_H1", "H4": "TIMEFRAME_H4"}
HTF_DEFAULT_DAYS = {"M5": 60, "M15": 120, "H1": 365, "H4": 730}  # bounded first run; widen only after size/speed are known
TF_SEC = {"M1": 60, "M5": 300, "M15": 900, "H1": 3600, "H4": 14400}


def backfill_bars(store: Store, symbol: str, server: str, tf: str, days: int, settle_s: int, log=print):
    """Native MT5 bars of any timeframe (kind bars_<tf>), 30-day chunks, only buckets that closed more than settle_s ago.
    Used for warm-up depth that M1 alone cannot give (M1 history is capped by terminal maxbars)."""
    if tf == "M1":
        return backfill_m1(store, symbol, server, days, settle_s, log)
    sec = TF_SEC[tf]
    now = mt5.symbol_info_tick(symbol).time
    end = (now - settle_s) // sec * sec
    start = end - days * 86400
    res = {"tf": tf, "bars": 0, "chunks": 0, "identical": 0, "written": 0, "superseded_old": 0}
    for d in range(start // 86400 * 86400, end, 30 * 86400):
        a, b = max(d, start), min(d + 30 * 86400, end)
        r = mt5.copy_rates_range(symbol, getattr(mt5, MT5_TF[tf]), a, b - 1)
        if r is None or len(r) == 0:
            store.quarantine("bar_chunk", d, "NO_BARS", f"{tf} copy_rates_range returned nothing", server, symbol)
            continue
        n = len(r)
        cols = {"source_id": [f"mt5_hist_bars"] * n, "server": [server] * n, "symbol": [symbol] * n, "tf": [tf] * n,
                "time": r["time"].astype("int64").tolist(), "open": r["open"].tolist(), "high": r["high"].tolist(),
                "low": r["low"].tolist(), "close": r["close"].tolist(), "tick_volume": r["tick_volume"].astype("int64").tolist(),
                "spread": r["spread"].astype("int32").tolist(), "real_volume": r["real_volume"].astype("int64").tolist(),
                "dataset_version": [DATASET_VERSION] * n}
        w = store.write_chunk(f"bars_{tf.lower()}", BAR_SCHEMA, cols, source_id="mt5_hist_bars", server=server, symbol=symbol,
                              chunk=f"{tf}-d{d}", key_col="time", partition=f"date={time.strftime('%Y-%m-%d', time.gmtime(d))}")
        res[w["status"]] += 1
        res["bars"] += n
        res["chunks"] += 1
        log(f"bars {tf} from {time.strftime('%Y-%m-%d', time.gmtime(a))} n={n} {w['status']}")
    return res

if __name__ == "__main__":
    main()
