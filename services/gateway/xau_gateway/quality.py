"""Data quality + certified M1 parity from the persisted store.
Never deletes or edits data; findings go to the quarantine table / report.
All reads are isolated by source, server and symbol (see Store.read_table)."""
from __future__ import annotations

import numpy as np

from .timeutil import session_boundary_bars

from .candles import CandleEngine
from .storage import Store

PRICE_TOL = 1e-6  # official tolerance: prices must match exactly (float noise only)
SPREAD_ABNORMAL_MULT = 5.0
HIST_TICKS = "mt5_hist_ticks"
HIST_BARS = "mt5_hist_bars"
LIVE_TICKS = "mt5_py_poll"


def _tick_arrays(store: Store, **flt):
    t = store.read_table("ticks", **flt)
    if t.num_rows == 0:
        return None
    o = np.argsort(np.asarray(t["time_msc"]), kind="stable")
    return {k: np.asarray(t[k])[o] for k in ("time_msc", "bid", "ask", "flags")}


def covered_minutes(store: Store, server: str, symbol: str):
    """Minutes (server epoch s) inside an hourly history chunk that was fetched for this exact server/symbol.
    This is *fetch coverage* only: whether a covered minute really has ticks is decided by comparing against MT5 bars."""
    cov = set()
    for f in store.files("ticks", source_id=HIST_TICKS, server=server, symbol=symbol, chunk_prefix="h"):
        h = int(f["chunk"][1:])
        cov.update(range(h, h + 3600, 60))
    return cov


def certified_parity(store: Store, symbol: str = "XAUUSD", server: str | None = None) -> dict:
    if server is None:  # single-server stores only; refuse to guess when several servers are present
        servers = {f["server"] for f in store.files("bars_m1", source_id=HIST_BARS, symbol=symbol)}
        if len(servers) != 1:
            return {"status": "INSUFFICIENT_DATA", "reason": f"server must be given explicitly (found {sorted(servers)})"}
        server = servers.pop()
    flt = {"server": server, "symbol": symbol}
    tk = _tick_arrays(store, source_id=HIST_TICKS, **flt)
    bars = store.read_table("bars_m1", source_id=HIST_BARS, **flt)
    if tk is None or bars.num_rows == 0:
        return {"status": "INSUFFICIENT_DATA", "server": server, "symbol": symbol}
    eng = CandleEngine(("M1",), price="bid", max_closed=10**7)
    for i in range(len(tk["time_msc"])):
        eng.on_tick(int(tk["time_msc"][i]), float(tk["bid"][i]), float(tk["ask"][i]), int(tk["flags"][i]))
    mine = {c.t: c for c in eng.closed["M1"]}
    open_minute = eng.open["M1"].t if "M1" in eng.open else None  # still-forming at the end of the data
    cov = covered_minutes(store, server, symbol)
    rows = {k: np.asarray(bars[k]) for k in ("time", "open", "high", "low", "close", "tick_volume")}
    res = {"server": server, "symbol": symbol, "compared": 0, "exact": 0, "excluded": [], "mismatches": []}
    quarantined = store.quarantined("bar_m1_parity", server, symbol)
    for i in range(len(rows["time"])):
        t = int(rows["time"][i])
        if t in quarantined:
            res["excluded"].append({"time": t, "reason": quarantined[t]})
            continue
        if t not in cov:
            res["excluded"].append({"time": t, "reason": "NO_TICK_COVERAGE_FOR_MINUTE"})
            continue
        if open_minute is not None and t == open_minute:
            res["excluded"].append({"time": t, "reason": "LOCAL_BAR_STILL_OPEN"})
            continue
        res["compared"] += 1
        c = mine.get(t)
        if c is None:  # MT5 has a bar for a minute whose hour we fetched completely, yet we hold no ticks: a real gap
            res["mismatches"].append({"time": t, "kind": "NO_LOCAL_TICKS_FOR_EXISTING_MT5_BAR",
                                      "mt5_tick_volume": int(rows["tick_volume"][i]), "local_tick_volume": 0})
            continue
        dpx = max(abs(c.o - rows["open"][i]), abs(c.h - rows["high"][i]), abs(c.l - rows["low"][i]), abs(c.c - rows["close"][i]))
        dtv = int(rows["tick_volume"][i]) - c.tick_volume
        if dpx <= PRICE_TOL and dtv == 0:
            res["exact"] += 1
        else:
            res["mismatches"].append({"time": t, "kind": "VALUE_MISMATCH", "price_delta": float(dpx),
                                      "tick_volume_delta": dtv, "mt5_tick_volume": int(rows["tick_volume"][i]),
                                      "local_tick_volume": c.tick_volume})
    q_n = sum(1 for x in res["excluded"] if x["reason"].startswith("QUARANTINED"))
    total_bars = len(rows["time"])
    res["coverage"] = {"mt5_bars": total_bars, "compared": res["compared"], "excluded": len(res["excluded"]),
                       "compared_fraction_of_all_bars": res["compared"] / total_bars if total_bars else 0.0}
    res["status"] = ("NOT_CERTIFIED" if res["mismatches"] or res["compared"] == 0
                     else "CERTIFIED_WITH_QUARANTINE" if q_n else "CERTIFIED")
    res["tolerance"] = {"price": PRICE_TOL, "tick_volume": 0}
    return res


def quality_report(store: Store, symbol: str = "XAUUSD", server: str | None = None) -> dict:
    if server is None:
        servers = {f["server"] for f in store.files("ticks", symbol=symbol)}
        if len(servers) != 1:
            return {"status": "INSUFFICIENT_DATA", "reason": f"server must be given explicitly (found {sorted(servers)})"}
        server = servers.pop()
    flt = {"server": server, "symbol": symbol}
    out: dict = {"server": server, "symbol": symbol}
    tk = _tick_arrays(store, source_id=HIST_TICKS, **flt)
    if tk is None:
        return {**out, "status": "INSUFFICIENT_DATA"}
    msc, bid, ask = tk["time_msc"], tk["bid"], tk["ask"]
    out["ticks"] = int(len(msc))
    out["invalid_quotes"] = int(((bid <= 0) | (ask <= 0) | (bid > ask)).sum())
    out["zero_spread_ticks"] = int((ask == bid).sum())
    key = np.rec.fromarrays([msc, bid, ask, tk["flags"]])
    _, cnt = np.unique(key, return_counts=True)
    out["duplicate_looking_ticks"] = int((cnt - 1).sum())  # reported only; cannot prove they are true duplicates
    gaps = np.diff(msc)
    out["tick_gap_max_s"] = float(gaps.max() / 1000) if len(gaps) else 0.0
    gi = np.where(gaps > 60_000)[0]
    out["tick_gaps_over_60s"] = [{"from_msc": int(msc[i]), "to_msc": int(msc[i + 1]), "seconds": float(gaps[i] / 1000)}
                                 for i in gi][:50]
    sp = ask - bid
    med = float(np.median(sp[sp > 0])) if (sp > 0).any() else 0.0
    out["spread_median"] = med
    out["abnormal_spread_ticks"] = int((sp > SPREAD_ABNORMAL_MULT * med).sum()) if med else 0
    d = np.abs(np.diff(bid))
    thr = 8 * (np.median(d[d > 0]) if (d > 0).any() else 0)
    m = len(d) - 2
    out["spike_candidates"] = int(((d[:m] > thr) & (np.abs(bid[3:] - bid[:m]) < 0.3 * d[:m])).sum()) if thr and m > 0 else 0
    bars = store.read_table("bars_m1", source_id=HIST_BARS, **flt)
    if bars.num_rows:
        t = np.asarray(bars["time"])
        tv = np.asarray(bars["tick_volume"]).astype(float)
        spr = np.asarray(bars["spread"])
        sb = session_boundary_bars(t, min_gap_s=1800, edge_minutes=5)   # bars next to every real session break in THIS data
        in_roll = np.zeros(len(t), dtype=bool)
        in_roll[sb["before_break"]] = True
        in_roll[sb["after_break"]] = True
        mtv = np.median(tv)
        mad = np.median(np.abs(tv - mtv)) or 1.0
        z = (tv - mtv) / (1.4826 * mad)
        out["bars"] = int(len(t))
        out["bar_gaps_minutes"] = int((np.diff(np.sort(t)) // 60 - 1).clip(min=0).sum())
        out["zero_spread_bars"] = int((spr == 0).sum())
        out["tick_volume_outliers_z>6"] = int((z > 6).sum())
        out["session_breaks_detected"] = sb["n_breaks"]
        out["rollover_window_bars"] = int(in_roll.sum())
        # candidate = at least one feature; research exclusion needs >= 2 independent features (zero spread AND volume outlier)
        sus = [{"time": int(t[i]), "zero_spread": bool(spr[i] == 0), "tv_z": float(z[i])}
               for i in np.where(in_roll & ((spr == 0) | (z > 6)))[0]]
        out["rollover_suspects"] = sus[:50]
        out["rollover_suspects_two_features"] = sum(1 for x in sus if x["zero_spread"] and x["tv_z"] > 6)
        ts = store.get_meta(f"symbol:{symbol}:tick_size")
        if ts:
            tick = float(ts)
            px = np.concatenate([np.asarray(bars[c]) for c in ("open", "high", "low", "close")])
            out["tick_size"] = tick
            out["tick_size_check_ok"] = bool(np.allclose(np.round(px / tick) * tick, px, atol=1e-6))
        else:
            out["tick_size_check_ok"] = "UNKNOWN_NO_SYMBOL_METADATA"
    out["policy"] = ("Findings are reported/quarantined, never deleted. A single feature never marks a bar as fake; "
                     "rollover suspects need >=2 independent features before research exclusion.")
    return out


def htf_parity(store: Store, tf: str, symbol: str = "XAUUSD", server: str | None = None) -> dict:
    """Compare native MT5 <tf> bars with <tf> bars aggregated from stored M1 bars (same server/symbol).
    Only buckets whose whole span lies inside the stored M1 range are compared; the rest are excluded with a reason."""
    from .multitf import TF_SECONDS, aggregate_m1
    if server is None:
        servers = {f["server"] for f in store.files("bars_m1", source_id=HIST_BARS, symbol=symbol)}
        if len(servers) != 1:
            return {"status": "INSUFFICIENT_DATA", "reason": f"server must be given explicitly (found {sorted(servers)})"}
        server = servers.pop()
    flt = {"server": server, "symbol": symbol, "source_id": HIST_BARS}
    m1 = store.read_table("bars_m1", **flt)
    nat = store.read_table(f"bars_{tf.lower()}", **flt)
    if m1.num_rows == 0 or nat.num_rows == 0:
        return {"status": "INSUFFICIENT_DATA", "tf": tf}
    o = np.argsort(np.asarray(m1["time"]), kind="stable")
    a = {k: np.asarray(m1[k])[o] for k in ("time", "open", "high", "low", "close", "tick_volume")}
    agg = aggregate_m1(a["time"], a["open"], a["high"], a["low"], a["close"], a["tick_volume"], tf)
    mine = {int(t): i for i, t in enumerate(agg["time"])}
    sec = TF_SECONDS[tf]
    m1_lo, m1_hi = int(a["time"][0]), int(a["time"][-1])
    res = {"tf": tf, "server": server, "symbol": symbol, "compared": 0, "exact": 0, "excluded": {}, "mismatches": []}
    nt = {k: np.asarray(nat[k]) for k in ("time", "open", "high", "low", "close", "tick_volume")}
    for i in range(len(nt["time"])):
        t = int(nt["time"][i])
        if t < m1_lo - (m1_lo % sec) + (sec if m1_lo % sec else 0):
            res["excluded"]["BEFORE_M1_RANGE"] = res["excluded"].get("BEFORE_M1_RANGE", 0) + 1
            continue
        if t + sec > m1_hi:
            res["excluded"]["AFTER_OR_AT_M1_END"] = res["excluded"].get("AFTER_OR_AT_M1_END", 0) + 1
            continue
        res["compared"] += 1
        j = mine.get(t)
        if j is None:
            res["mismatches"].append({"time": t, "kind": "NO_M1_FOR_NATIVE_BAR", "native_tick_volume": int(nt["tick_volume"][i])})
            continue
        d = max(abs(agg["open"][j] - nt["open"][i]), abs(agg["high"][j] - nt["high"][i]),
                abs(agg["low"][j] - nt["low"][i]), abs(agg["close"][j] - nt["close"][i]))
        dv = int(nt["tick_volume"][i]) - int(agg["tick_volume"][j])
        if d <= PRICE_TOL and dv == 0:
            res["exact"] += 1
        else:
            res["mismatches"].append({"time": t, "kind": "VALUE_MISMATCH", "price_delta": float(d), "tick_volume_delta": dv})
    res["status"] = "PASS" if res["compared"] and not res["mismatches"] else "FAIL" if res["compared"] else "INSUFFICIENT_DATA"
    return res
