"""Per-hour coverage inventory and historical/live seam reconciliation (read-only over the store).

For every server-time hour in [start, end) it states which provenance has ticks and, where two provenances overlap, whether
they are IDENTICAL as multisets of (time_msc, bid, ask, flags). Gaps are classified, never filled:
  MARKET_BREAK        no ticks anywhere AND MT5 has no M1 bars for the hour (consistent with a closed market)
  UNRESOLVED_GAP      no ticks anywhere but MT5 has M1 bars for the hour -> real hole, stays open
  HIST_ONLY / LIVE_ONLY / BOTH_MATCH / BOTH_DIFFER
A coverage fraction is reported; nothing is labelled 'continuous' unless every hour with M1 bars is HIST_ONLY/LIVE_ONLY/BOTH_MATCH.
"""
from __future__ import annotations

from collections import Counter

import numpy as np
import pyarrow.parquet as pq

from .quality import HIST_BARS, HIST_TICKS, LIVE_TICKS
from .storage import Store

HOUR = 3600


def _per_hour_multisets(store: Store, source_id: str, server: str, symbol: str, lo_h: int, hi_h: int, chunk_prefix=None):
    """hour -> Counter[(msc,bid,ask,flags)]. Chunks of ONE capture session are summed (they are disjoint pieces of one stream);
    different sessions that observed the same stream are merged with Counter union (= max count per tick), never summed:
    two overlapping sessions saw the same tick once, not twice. Sessions are the unit of duplicate-safe merging."""
    per_session: dict[str, dict[int, Counter]] = {}
    legacy_run, last_end = 0, 0
    for f in store.files("ticks", source_id=source_id, server=server, symbol=symbol, chunk_prefix=chunk_prefix):
        if not f["session"] and f["chunk"].startswith("live-"):
            # legacy chunks (before capture_session_id): a bridge_seq that restarts at 1 / goes backwards marks a new gateway run
            a, b = (int(x) for x in f["chunk"].split("-")[1:3])
            if a <= last_end or a == 1:
                legacy_run += 1
            last_end = b
            f = {**f, "session": f"legacy-run-{legacy_run}"}
        if f["max_key"] < lo_h * 1000 or f["min_key"] >= hi_h * 1000:
            continue
        t = pq.read_table(store.root / f["path"], columns=["time_msc", "bid", "ask", "flags"])
        msc, bid, ask, fl = (np.asarray(t[c]) for c in ("time_msc", "bid", "ask", "flags"))
        sess = per_session.setdefault(f["session"], {})
        for m, b, a, g in zip(msc.tolist(), bid.tolist(), ask.tolist(), fl.tolist()):
            h = m // 1000 // HOUR * HOUR
            if lo_h <= h < hi_h:
                sess.setdefault(h, Counter())[(m, b, a, g)] += 1
    out: dict[int, Counter] = {}
    for sess in per_session.values():
        for h, c in sess.items():
            out[h] = (out[h] | c) if h in out else c
    return out


def coverage_report(store: Store, server: str, symbol: str, start_h: int | None = None, end_h: int | None = None) -> dict:
    bars = store.read_table("bars_m1", source_id=HIST_BARS, server=server, symbol=symbol)
    bar_times = np.asarray(bars["time"]).tolist() if bars.num_rows else []
    bar_hours = {x // HOUR * HOUR for x in bar_times}
    bar_minutes_by_hour: dict[int, set] = {}
    for x in bar_times:
        bar_minutes_by_hour.setdefault(x // HOUR * HOUR, set()).add(x // 60)
    tick_files = store.files("ticks", server=server, symbol=symbol)
    if not tick_files and not bar_hours:
        return {"status": "INSUFFICIENT_DATA"}
    lo = start_h if start_h is not None else min([f["min_key"] // 1000 // HOUR * HOUR for f in tick_files] or [min(bar_hours)])
    hi = end_h if end_h is not None else max([f["max_key"] // 1000 // HOUR * HOUR + HOUR for f in tick_files] or [max(bar_hours) + HOUR])
    hist = _per_hour_multisets(store, HIST_TICKS, server, symbol, lo, hi)
    live = _per_hour_multisets(store, LIVE_TICKS, server, symbol, lo, hi)
    rows, summary = [], Counter()
    def tick_minutes(*cs):
        out = set()
        for c in cs:
            if c:
                out.update(k[0] // 60000 for k in c)
        return out

    for h in range(lo, hi, HOUR):
        hc, lc = hist.get(h), live.get(h)
        missing_min = len(bar_minutes_by_hour.get(h, set()) - tick_minutes(hc, lc))   # MT5 has a bar, we hold no tick for that minute
        if hc and lc:
            # live capture covers only part of the hour (start/stop edges): compare inside the live span only
            lmin = min(k[0] for k in lc)
            lmax = max(k[0] for k in lc)
            hsub = Counter({k: v for k, v in hc.items() if lmin <= k[0] <= lmax})
            same = hsub == lc
            miss, extra = sum((hsub - lc).values()), sum((lc - hsub).values())
            st = "BOTH_MATCH" if same else "BOTH_DIFFER"
            rows.append({"hour": h, "status": st, "hist_ticks": sum(hc.values()), "live_ticks": sum(lc.values()),
                         "missing_in_live": miss, "only_in_live": extra})
        elif hc:
            st = "HIST_ONLY"
            rows.append({"hour": h, "status": st, "hist_ticks": sum(hc.values())})
        elif lc:
            st = "LIVE_ONLY"
            rows.append({"hour": h, "status": st, "live_ticks": sum(lc.values())})
        else:
            st = "UNRESOLVED_GAP" if h in bar_hours else "MARKET_BREAK"
            rows.append({"hour": h, "status": st})
        if st in ("HIST_ONLY", "LIVE_ONLY", "BOTH_MATCH") and missing_min:
            st = {"HIST_ONLY": "HIST_PARTIAL", "LIVE_ONLY": "LIVE_PARTIAL", "BOTH_MATCH": "BOTH_MATCH_PARTIAL"}[st]
            rows[-1]["status"] = st
        rows[-1]["minutes_without_ticks"] = missing_min
        summary[st] += 1
    with_bars = [r for r in rows if r["hour"] in bar_hours]
    ok = [r for r in with_bars if r["status"] in ("HIST_ONLY", "LIVE_ONLY", "BOTH_MATCH")]
    return {"server": server, "symbol": symbol, "from_hour": lo, "to_hour": hi, "hours": len(rows),
            "summary": dict(summary), "hours_with_m1_bars": len(with_bars),
            "tick_coverage_of_active_hours": (len(ok) / len(with_bars)) if with_bars else None,
            "continuous": bool(with_bars) and len(ok) == len(with_bars),
            "unresolved": [r["hour"] for r in rows if r["status"] == "UNRESOLVED_GAP"],
            "differ": [r for r in rows if r["status"] == "BOTH_DIFFER"], "rows": rows}
