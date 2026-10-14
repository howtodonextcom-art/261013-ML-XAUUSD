"""Setup event pipeline trace (Level 6.3): where does every F/C/X/I/M event go between the state machine and the candle?

  .\\.venv\\Scripts\\python.exe benchmarks\\setup_event_trace.py        -> results/v1/setup_event_trace.json

Stages measured with the SAME functions the gateway uses (bars seeded like `seed_from_store`: the newest 2000 closed bars per timeframe):
 1 backend events (state machine over the engine window) / 2 kept by the realtime cap (`recent_events`) / 3 the REPLAY total over every stored bar
 per chart timeframe (candle window = newest 2000 candles of that timeframe): 4 events inside the candle window, 5 mapped to a candle, 6 not mapped with a reason
 (BEFORE_FIRST_CANDLE / AFTER_LAST_CANDLE / MISSING_BAR), 7 groups (several events on one candle and side are ONE marker whose tooltip lists all).
The mapping mirrors apps/dashboard-static/intel_panels.js `mapEvent` (time = known_at - 1, bar-close convention). Display only: no outcome is computed.
"""
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/gateway", "services/intelligence"):
    sys.path.insert(0, str(ROOT / p))
from xau_gateway.identity import load_source_config  # noqa: E402
from xau_gateway.intel_logic import compute_heavy  # noqa: E402
from xau_gateway.setup_history import compose, load_store_bars, replay_events  # noqa: E402
from xau_gateway.storage import Store  # noqa: E402

SEC = {"M1": 60, "M5": 300, "M15": 900, "H1": 3600, "H4": 14400}
WINDOW = 2000


def map_event(known_at: int, candle_times: np.ndarray, tf: str):
    """(candle time | None, reason). Mirrors `mapEvent` in intel_panels.js."""
    if len(candle_times) == 0:
        return None, "NO_CANDLES"
    t = known_at - 1
    bar = (t // SEC[tf]) * SEC[tf]
    i = int(np.searchsorted(candle_times, bar, side="right")) - 1
    if i < 0:
        return None, "BEFORE_FIRST_CANDLE"
    if t >= candle_times[i] + SEC[tf]:
        return None, "AFTER_LAST_CANDLE" if i == len(candle_times) - 1 else "MISSING_BAR"
    return int(candle_times[i]), "OK"


def candle_times(store, server, symbol, tf):
    t = store.read_table(f"bars_{tf.lower()}", source_id="mt5_hist_bars", server=server, symbol=symbol)
    return np.sort(np.asarray(t["time"]).astype(np.int64))[-WINDOW:]


def main() -> int:
    cfg = load_source_config()
    server, symbol = cfg["expected"]["server"], cfg.get("symbol_hint", "XAUUSD")
    st = Store(ROOT / "data" / "store")
    bars = load_store_bars(st, server, symbol)
    now = int(bars["M15"]["time"][-1]) + 900
    engine_bars = {tf: {k: v[-WINDOW:] for k, v in b.items()} for tf, b in bars.items()}
    heavy = compute_heavy(engine_bars, now)
    engine = heavy["setup_events_all"]
    out = {"now_server_time": now, "engine_window_m15_bars": len(engine_bars["M15"]["time"]), "backend_events_engine_window": len(engine), "kept_by_realtime_cap": len(heavy["setup_events"]),
           "lost_to_cap": len(engine) - len(heavy["setup_events"]), "cap": len(heavy["setup_events"])}
    rep = replay_events(bars)
    out["replay_events_all_stored_bars"] = len(rep["events"])
    ev, comp = compose(engine, rep["events"], rep["coverage_end"])  # ONE canonical timeline: the replay is the history, live events only beyond it
    out["timeline"] = comp
    live_ids = {e["event_id"] for e in engine}
    start = min(e["known_at"] for e in engine)
    out["live_vs_replay_inside_the_live_window"] = {"live_events": len(engine), "live_events_also_in_replay": len(live_ids & {e["event_id"] for e in rep["events"]}),
                                                    "replay_only": len([e for e in rep["events"] if e["known_at"] >= start and e["event_id"] not in live_ids]),
                                                    "note": "a state machine started at a different bar builds different setups: the replay is the history and is never mixed with live events inside its reach"}
    out["events_in_timeline"] = len(ev)
    out["replay_bars_m15"] = rep["bars_m15"]
    out["state_counts_replay"] = dict(Counter(e["state"] for e in ev))
    out["per_timeframe"] = {}
    for tf in SEC:
        ct = candle_times(st, server, symbol, tf)
        row = Counter()
        groups = Counter()
        for e in ev:
            ct_, why = map_event(int(e["known_at"]), ct, tf)
            row[why] += 1
            if ct_ is not None:
                groups[(ct_, e["direction"])] += 1
        realtime = {e["event_id"] for e in heavy["setup_events"]}
        rt = Counter(map_event(int(e["known_at"]), ct, tf)[1] for e in ev if e["event_id"] in realtime)
        out["per_timeframe"][tf] = {"candles": int(len(ct)), "first_candle": int(ct[0]) if len(ct) else None, "last_candle": int(ct[-1]) if len(ct) else None,
                                    "events_by_mapping": dict(row), "drawn_before_fix_realtime_cap": int(rt.get("OK", 0)), "drawn_after_fix_all_loaded": int(row.get("OK", 0)),
                                    "marker_groups": len(groups), "events_sharing_a_candle_and_side": int(sum(v for v in groups.values() if v > 1)), "max_events_on_one_candle_side": max(groups.values()) if groups else 0}
    (ROOT / "results" / "v1").mkdir(parents=True, exist_ok=True)
    (ROOT / "results" / "v1" / "setup_event_trace.json").write_text(json.dumps(out, indent=1, sort_keys=True), encoding="utf-8")
    print(json.dumps(out, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
