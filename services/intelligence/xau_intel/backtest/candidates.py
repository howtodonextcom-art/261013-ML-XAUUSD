"""Candidates C0-C7 of the frozen pre-registration (docs/research/BACKTEST_PREREGISTRATION.md + BACKTEST_IMPLEMENTATION_CLARIFICATIONS.md)."""
from __future__ import annotations

import numpy as np

from ..setups.machine import SetupPolicy
from .engine import (M5, decisions_from_setup, last_closed_m5, plan_direct, run_trades, setup_run, spread_at)

CANDIDATES = ("C0", "C1", "C2", "C3", "C4", "C5", "C6", "C7")


def c4(bars, m5, ver, sr=None):
    sr = sr or setup_run(bars)
    return run_trades(decisions_from_setup(sr, m5, ver), m5), sr


def c5(bars, m5, ver):
    sr = setup_run(bars, SetupPolicy(require_zone=False))
    return run_trades(decisions_from_setup(sr, m5, ver), m5), sr


def c6(bars, m5, ver, sr=None):
    """Pre-registered ablation 'liquidity-sweep evidence removed': cand-1 never uses sweeps, so this IS C4 (null control, reported as such)."""
    return c4(bars, m5, ver, sr)


def c7(bars, m5, ver, sr=None):
    sr = sr or setup_run(bars)
    return run_trades(decisions_from_setup(sr, m5, ver), m5, direction_filter="BUY")


def c3(sr, m5):
    """H4 direction ONSET -> decision at the next M15 close; SL 1.5 ATR, TP 2.0 x stop distance."""
    ctx4, c, atr, t = sr["ctx4"], sr["c"], sr["atr"], sr["t"]
    sec = 900
    dec = []
    for j in range(1, len(c)):
        if ctx4[j] in ("UP", "DOWN") and ctx4[j - 1] not in ("UNKNOWN", ctx4[j]) and not np.isnan(atr[j]):
            direction = "BUY" if ctx4[j] == "UP" else "SELL"
            sgn = 1 if direction == "BUY" else -1
            close = int(t[j]) + sec
            entry, a = float(c[j]), float(atr[j])
            plan, why = plan_direct(direction, entry, entry - sgn * 1.5 * a, entry + sgn * 3.0 * a, a, spread_at(m5, close))
            dec.append({"setup_id": f"C3-{direction}-{close}", "decision_time": close, "atr": a, "direction": direction, "plan": plan, "reason": why})
    return run_trades(dec, m5)


def c1(c4_trades, sr, m5, lo, hi, seeds, seed0=20261014):
    """Random entries paired with C4's geometry. [lo, hi): decision-time range (server epoch s). Returns one dict per seed."""
    m5t = m5["time"]
    ia = int(np.searchsorted(m5t, lo, side="left"))
    ib = int(np.searchsorted(m5t, hi - 288 * M5, side="left"))        # leave a full timeout runway
    out = []
    if not c4_trades or ib - ia < 10:
        return out
    t15, atr15 = sr["t"], sr["atr"]
    for k in range(seeds):
        rng = np.random.default_rng(seed0 + k)
        dec = []
        for n, tr in enumerate(c4_trades):
            i = int(rng.integers(ia, ib))
            sgn = 1 if rng.random() < 0.5 else -1
            direction = "BUY" if sgn == 1 else "SELL"
            close = int(m5t[i]) + M5
            j = int(np.searchsorted(t15, close - 900, side="right")) - 1
            if j < 0 or np.isnan(atr15[j]):
                continue
            entry = float(m5["close"][i])
            tgt_d = abs(tr["tp"] - tr["entry"])
            plan, why = plan_direct(direction, entry, entry - sgn * tr["stop_distance"], entry + sgn * tgt_d, float(atr15[j]), spread_at(m5, close))
            dec.append({"setup_id": f"C1-{k}-{n}", "decision_time": close, "atr": float(atr15[j]), "direction": direction, "plan": plan, "reason": why})
        trades, cnt = run_trades(dec, m5)
        out.append({"seed": seed0 + k, "trades": trades, "counters": cnt})
    return out


def c2(m5, lo, hi):
    """Buy-and-hold of one fixed lot over [lo, hi): USD per ounce (buy at ask = open + spread, sell at the last bar close), no R."""
    t = m5["time"]
    ia, ib = int(np.searchsorted(t, lo, side="left")), int(np.searchsorted(t, hi, side="left")) - 1
    if ib <= ia:
        return None
    return {"usd_per_oz": float(m5["close"][ib] - (m5["open"][ia] + m5["spread"][ia])), "from": int(t[ia]), "to": int(t[ib])}
