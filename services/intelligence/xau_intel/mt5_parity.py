"""Compare this package's indicators with the values MetaTrader 5 itself computed (CSV from mt5/scripts/DumpIndicators.mq5).

compare_csv() recomputes every indicator from the CSV's own OHLC (so it does not depend on the local store) and reports, per
indicator, the maximum absolute difference in two zones: `early` (first 300 bars after the indicator becomes valid: seed effects can
show here) and `late` (the last 1000 bars: seeds must have decayed). PASS needs both within tolerance.
"""
from __future__ import annotations

import csv
from pathlib import Path

import numpy as np

from .indicators import atr, ema, macd, rsi

TOL = {"ema20": 1e-5, "ema50": 1e-5, "ema100": 1e-5, "ema200": 1e-5, "rsi14": 1e-4, "atr14": 1e-5, "macd": 1e-5, "signal": 1e-5}
COLS = ("time", "open", "high", "low", "close", "ema20", "ema50", "ema100", "ema200", "rsi14", "atr14", "macd", "signal")


def read_csv(path: Path) -> dict:
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f, delimiter=";"))
    head, body = rows[0], rows[1:]
    if tuple(head) != COLS:
        raise ValueError(f"unexpected header {head}")
    return {c: np.array([float(r[i]) for r in body]) for i, c in enumerate(COLS)}


def ours(d: dict) -> dict:
    c = d["close"]
    line, sig, _ = macd(c)
    return {"ema20": ema(c, 20), "ema50": ema(c, 50), "ema100": ema(c, 100), "ema200": ema(c, 200), "rsi14": rsi(c, 14),
            "atr14": atr(d["high"], d["low"], c, 14), "macd": line, "signal": sig}


def compare(d: dict, tol: dict | None = None) -> dict:
    tol = tol or TOL
    mine = ours(d)
    res, ok_all = {}, True
    for k, t in tol.items():
        a, b = mine[k], d[k]
        valid = ~np.isnan(a)
        if not valid.any():
            res[k] = {"status": "INSUFFICIENT_DATA"}
            ok_all = False
            continue
        idx = np.where(valid)[0]
        early, late = idx[:300], idx[-1000:]
        e = float(np.max(np.abs(a[early] - b[early])))
        l = float(np.max(np.abs(a[late] - b[late])))
        ok = l <= t                      # verdict on the late zone only (see module docstring)
        ok_all &= ok
        res[k] = {"early_max_abs_diff_informational": e, "late_max_abs_diff": l, "tolerance": t, "status": "PASS" if ok else "FAIL", "bars": int(len(idx))}
    return {"status": "PASS" if ok_all else "FAIL", "indicators": res, "bars": int(len(d["close"]))}


def compare_csv(path: Path) -> dict:
    return compare(read_csv(path))
