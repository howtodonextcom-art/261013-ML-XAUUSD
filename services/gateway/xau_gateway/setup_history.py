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


def compact(e: dict, provenance: str, seq: int = 0) -> dict:
    out = {k: e.get(k) for k in KEYS}
    out["seq"] = int(seq)                                                    # emission order of the state machine: several transitions of one setup can share one second
    out["reasons"] = list(e.get("reasons") or [])
    out["event_id"] = f"{e['setup_id']}|{e['state']}|{int(e['known_at'])}"
    out["provenance"] = provenance
    return out


def replay_events(bars: dict) -> dict:
    """Worker-process function: bars = {M15,H1,H4: {time,open,high,low,close}} closed bars. Returns every setup event of the replay (compact)."""
    from xau_intel.backtest.engine import setup_run
    sr = setup_run(bars)
    ev = [compact(e, "REPLAY", i) for i, e in enumerate(sr["res"]["events"])]
    return {"events": ev, "coverage_end": (int(sr["t"][-1]) + 900) if len(sr["t"]) else None, "bars_m15": int(len(sr["t"])), "first_bar": int(sr["t"][0]) if len(sr["t"]) else None, "last_bar": int(sr["t"][-1]) if len(sr["t"]) else None,
            "setup_version": sr["res"].get("policy_version")}


def load_store_bars(store, server: str, symbol: str, hist_source: str = "mt5_hist_bars", tfs: tuple = ("M15", "H1", "H4")) -> dict:
    """Closed stored bars for M15/H1/H4 of THIS server/symbol, sorted; quarantined bars are excluded (never repaired), like the backtest loader."""
    bars = {}
    for tf in tfs:
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
    """Union by event_id; the FIRST group wins on a duplicate (pass the live engine events first). Sorted by (known_at, emission order)."""
    seen: dict[str, dict] = {}
    for g in groups:
        for e in g:
            seen.setdefault(e["event_id"], e)
    return sorted(seen.values(), key=lambda e: (e["known_at"], e.get("seq", 0), e["setup_id"]))      # never alphabetical by state: the lifecycle keeps its emission order


def compose(live: list[dict], replay: list[dict], coverage_end: int | None = None) -> tuple[list[dict], dict]:
    """ONE canonical timeline. The REPLAY (state machine started at the first stored bar, fed with every closed bar up to the newest one) is the history: it is deterministic and
    causal, and an event of the past never changes when time passes (the start is fixed). The LIVE engine analyses only a sliding 2000-bar window, so its setups differ from the
    replay's by 10 to 25% even deep inside the window (zig-zag swings depend on where the state machine started): mixing both would double count and make the past change as the window slides.
    LIVE events are therefore added only where the replay does not reach (known_at after `coverage_end`) and are never used to overwrite a replay event.
    The newest 12 live events travel in the realtime payload anyway (what the decision engine saw)."""
    cov = coverage_end if coverage_end is not None else (max((e["known_at"] for e in replay), default=None))
    extra = [e for e in live if cov is None or e["known_at"] > cov]
    rep = {"replay_events_total": len(replay), "live_events": len(live), "live_events_added_beyond_replay": len(extra), "live_events_not_used": len(live) - len(extra), "replay_coverage_end": cov}
    return merge(replay, extra), rep


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
