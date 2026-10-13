"""Data quality + certified M1 parity from the persisted store. Never deletes or edits data; findings go to quarantine/report."""
from __future__ import annotations

import numpy as np

from .candles import CandleEngine
from .storage import Store

PRICE_TOL = 1e-6  # official tolerance: prices must match exactly at tick-size resolution (float noise only)
SPREAD_ABNORMAL_MULT = 5.0
ROLLOVER_WINDOW = (23 * 3600 + 50 * 60, 5 * 60 + 24 * 3600)  # seconds-of-day, server time, spans midnight (candidate only)


def _tick_arrays(store: Store):
    t = store.read_table("ticks")
    if t.num_rows == 0:
        return None
    o = np.argsort(np.asarray(t["time_msc"]), kind="stable")
    return {k: np.asarray(t[k])[o] for k in ("time_msc", "bid", "ask", "flags")}


def covered_minutes(store: Store):
    """Set of minute-start (server epoch s) fully covered by an hourly tick chunk."""
    cov = set()
    for f in store.files("ticks"):
        if f["chunk"].startswith("h"):
            h = int(f["chunk"][1:])
            cov.update(range(h, h + 3600, 60))
    return cov


def certified_parity(store: Store, symbol: str = "XAUUSD") -> dict:
    tk = _tick_arrays(store)
    bars = store.read_table("bars_m1")
    if tk is None or bars.num_rows == 0:
        return {"status": "INSUFFICIENT_DATA"}
    eng = CandleEngine(("M1",), price="bid", max_closed=10**7)
    for i in range(len(tk["time_msc"])):
        eng.on_tick(int(tk["time_msc"][i]), float(tk["bid"][i]), float(tk["ask"][i]), int(tk["flags"][i]))
    mine = {c.t: c for c in eng.closed["M1"]}
    cov = covered_minutes(store)
    rows = {k: np.asarray(bars[k]) for k in ("time", "open", "high", "low", "close", "tick_volume")}
    res = {"compared": 0, "exact": 0, "excluded": [], "mismatches": []}
    quarantined = store.quarantined("bar_m1_parity")
    for i in range(len(rows["time"])):
        t = int(rows["time"][i])
        if t in quarantined:
            res["excluded"].append({"time": t, "reason": quarantined[t]})
            continue
        if t not in cov:
            res["excluded"].append({"time": t, "reason": "NO_TICK_COVERAGE_FOR_MINUTE"})
            continue
        c = mine.get(t)
        if c is None:  # bar still open locally (its closing tick never arrived) or no ticks at all
            res["excluded"].append({"time": t, "reason": "LOCAL_BAR_NOT_CLOSED_OR_NO_TICKS"})
            continue
        res["compared"] += 1
        dpx = max(abs(c.o - rows["open"][i]), abs(c.h - rows["high"][i]), abs(c.l - rows["low"][i]), abs(c.c - rows["close"][i]))
        dtv = int(rows["tick_volume"][i]) - c.tick_volume
        if dpx <= PRICE_TOL and dtv == 0:
            res["exact"] += 1
        else:
            res["mismatches"].append({"time": t, "price_delta": float(dpx), "tick_volume_delta": dtv,
                                      "mt5_tick_volume": int(rows["tick_volume"][i]), "local_tick_volume": c.tick_volume})
    q_n = sum(1 for x in res["excluded"] if x["reason"].startswith("QUARANTINED"))
    res["status"] = ("NOT_CERTIFIED" if res["mismatches"] or res["compared"] == 0
                     else "CERTIFIED_WITH_QUARANTINE" if q_n else "CERTIFIED")
    res["tolerance"] = {"price": PRICE_TOL, "tick_volume": 0}
    return res


def quality_report(store: Store) -> dict:
    out: dict = {}
    tk = _tick_arrays(store)
    if tk is None:
        return {"status": "INSUFFICIENT_DATA"}
    msc, bid, ask = tk["time_msc"], tk["bid"], tk["ask"]
    n = len(msc)
    out["ticks"] = n
    out["invalid_quotes"] = int(((bid <= 0) | (ask <= 0) | (bid > ask)).sum())
    out["zero_spread_ticks"] = int((ask == bid).sum())
    # duplicate-looking ticks: identical (msc,bid,ask,flags). Reported only: cannot prove they are true duplicates.
    key = np.rec.fromarrays([msc, bid, ask, tk["flags"]])
    _, cnt = np.unique(key, return_counts=True)
    out["duplicate_looking_ticks"] = int((cnt - 1).sum())
    gaps = np.diff(msc)
    out["tick_gap_max_s"] = float(gaps.max() / 1000) if len(gaps) else 0.0
    gi = np.where(gaps > 60_000)[0]
    out["tick_gaps_over_60s"] = [{"from_msc": int(msc[i]), "to_msc": int(msc[i + 1]), "seconds": float(gaps[i] / 1000)} for i in gi][:50]
    sp = ask - bid
    med = float(np.median(sp[sp > 0])) if (sp > 0).any() else 0.0
    out["spread_median"] = med
    out["abnormal_spread_ticks"] = int((sp > SPREAD_ABNORMAL_MULT * med).sum()) if med else 0
    # spike: single-tick bid move > 8x median absolute move and reverts within 3 ticks (candidate only)
    d = np.abs(np.diff(bid))
    thr = 8 * (np.median(d[d > 0]) if (d > 0).any() else 0)
    m = len(d) - 2
    out["spike_candidates"] = int(((d[:m] > thr) & (np.abs(bid[3:] - bid[:m]) < 0.3 * d[:m])).sum()) if thr and m > 0 else 0
    bars = store.read_table("bars_m1")
    if bars.num_rows:
        t = np.asarray(bars["time"])
        tv = np.asarray(bars["tick_volume"]).astype(float)
        spr = np.asarray(bars["spread"])
        sod = t % 86400
        in_roll = (sod >= ROLLOVER_WINDOW[0]) | (sod <= ROLLOVER_WINDOW[1] - 86400)
        mtv, mad = np.median(tv), np.median(np.abs(tv - np.median(tv))) or 1.0
        z = (tv - mtv) / (1.4826 * mad)
        out["bars"] = int(len(t))
        out["bar_gaps_minutes"] = int((np.diff(t) // 60 - 1).clip(min=0).sum())
        out["zero_spread_bars"] = int((spr == 0).sum())
        out["tick_volume_outliers_z>6"] = int((z > 6).sum())
        out["rollover_window_bars"] = int(in_roll.sum())
        out["rollover_suspects"] = [
            {"time": int(t[i]), "zero_spread": bool(spr[i] == 0), "tv_z": float(z[i])}
            for i in np.where(in_roll & ((spr == 0) | (z > 6)))[0]
        ][:50]
        hr = np.asarray(bars["high"]) - np.asarray(bars["low"])
        out["tick_size_check_ok"] = bool(np.allclose(np.round(np.asarray(bars["open"]) / 0.01) * 0.01, np.asarray(bars["open"]), atol=1e-6))
    out["policy"] = ("Findings are reported/quarantined, never deleted. A single feature never marks a bar as fake; "
                     "rollover suspects need >=2 independent features before research exclusion.")
    return out
