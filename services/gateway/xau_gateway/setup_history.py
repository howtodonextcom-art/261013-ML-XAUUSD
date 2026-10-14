"""Historical setup events (Level 6.3). The realtime payload carries only the newest 12 setup events; the full history is served by /api/setup_events in pages.

Two provenances, never mixed up:
* LIVE_ENGINE: the events of the production analysis that is running now (`compute_heavy` result cache: same bars, same code, same moment as the realtime decision).
* REPLAY: a deterministic causal replay of the setup-1 state machine over the STORED closed bars (M15 events, H1/H4 context): the same functions as production, no live decision is reconstructed.
Both are SETUP observations (F/C/X/I/M), not BUY/SELL decisions. Display only: no outcome, expectancy or performance is computed here, so the sealed research holdout is not used for any claim.
An event id is stable: `setup_id|state|known_at`.
"""
from __future__ import annotations

import numpy as np

KEYS = ("setup_id", "direction", "setup_timeframe", "state", "prev_state", "event_time", "known_at", "reasons", "entry_level", "invalidation_level", "policy_version", "expires_at")
DEFAULT_LIMIT, MAX_LIMIT = 500, 2000


def compact(e: dict, provenance: str) -> dict:
    out = {k: e.get(k) for k in KEYS}
    out["reasons"] = list(e.get("reasons") or [])
    out["event_id"] = f"{e['setup_id']}|{e['state']}|{int(e['known_at'])}"
    out["provenance"] = provenance
    return out


def replay_events(bars: dict) -> dict:
    """Worker-process function: bars = {M15,H1,H4: {time,open,high,low,close}} closed bars. Returns every setup event of the replay (compact)."""
    from xau_intel.backtest.engine import setup_run
    sr = setup_run(bars)
    ev = [compact(e, "REPLAY") for e in sr["res"]["events"]]
    return {"events": ev, "bars_m15": int(len(sr["t"])), "first_bar": int(sr["t"][0]) if len(sr["t"]) else None, "last_bar": int(sr["t"][-1]) if len(sr["t"]) else None,
            "setup_version": sr["res"].get("policy_version")}


def load_store_bars(store, server: str, symbol: str, hist_source: str = "mt5_hist_bars") -> dict:
    """Closed stored bars for M15/H1/H4 of THIS server/symbol, sorted; quarantined bars are excluded (never repaired), like the backtest loader."""
    bars = {}
    for tf in ("M15", "H1", "H4"):
        t = store.read_table(f"bars_{tf.lower()}", source_id=hist_source, server=server, symbol=symbol)
        if t.num_rows == 0:
            bars[tf] = {k: np.array([]) for k in ("time", "open", "high", "low", "close")}
            continue
        q = store.quarantined(f"bars_{tf.lower()}", server, symbol)
        times = np.asarray(t["time"])
        keep = np.array([int(x) not in q for x in times], dtype=bool)
        o = np.nonzero(keep)[0][np.argsort(times[keep], kind="stable")]
        g = lambda k: np.asarray(t[k])[o].astype(float)  # noqa: E731
        bars[tf] = {"time": g("time").astype(np.int64), "open": g("open"), "high": g("high"), "low": g("low"), "close": g("close")}
    return bars


def merge(*groups: list[dict]) -> list[dict]:
    """Union by event_id; the FIRST group wins on a duplicate (pass the live engine events first). Sorted by (known_at, setup_id, state)."""
    seen: dict[str, dict] = {}
    for g in groups:
        for e in g:
            seen.setdefault(e["event_id"], e)
    return sorted(seen.values(), key=lambda e: (e["known_at"], e["setup_id"], e["state"]))


def compose(live: list[dict], replay: list[dict]) -> tuple[list[dict], dict]:
    """ONE consistent timeline: the LIVE engine events are authoritative from the start of its window on (they are what production produced from the bars it had); the REPLAY
    (a state machine started at the first stored bar) only fills the time BEFORE that window. Mixing both inside the live window would double count setups, because a state
    machine started at a different bar can build different setups (zig-zag path dependence). Returns (events, report)."""
    start = min((e["known_at"] for e in live), default=None)
    kept = [e for e in replay if start is None or e["known_at"] < start]
    rep = {"live_window_start": start, "live_events": len(live), "replay_events_total": len(replay), "replay_events_used": len(kept), "replay_events_superseded_by_live": len(replay) - len(kept)}
    return merge(live, kept), rep


def page(events: list[dict], t_from: int | None, t_to: int | None, limit: int = DEFAULT_LIMIT, cursor: int | None = None) -> dict:
    """Events with known_at in [t_from, t_to] (server-time epoch seconds, inclusive), oldest first, at most `limit` (cap MAX_LIMIT), after `cursor` (the last known_at/event id of the previous page)."""
    limit = max(1, min(int(limit), MAX_LIMIT))
    sel = [e for e in events if (t_from is None or e["known_at"] >= t_from) and (t_to is None or e["known_at"] <= t_to)]
    total_in_range = len(sel)
    if cursor is not None:
        sel = [e for e in sel if e["known_at"] > cursor]
    out = sel[:limit]
    # a page never splits events that share one known_at: extend to the end of that second so a cursor on known_at loses nothing
    if len(sel) > limit:
        last = out[-1]["known_at"]
        out += [e for e in sel[limit:] if e["known_at"] == last]
    truncated = len(sel) > len(out)
    return {"events": out, "total_in_range": total_in_range, "returned": len(out), "truncated": truncated, "next_cursor": out[-1]["known_at"] if truncated else None}
