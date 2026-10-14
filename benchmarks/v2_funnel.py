"""V2 signal-FREQUENCY funnel on the stored history: COUNTS ONLY (docs/research/M1_ENTRY_V2_PREREGISTRATION.md).

All stored M1 history lies inside the sealed P6/P7 holdout period, so this script computes no price outcome, no P/L, no R and no hit-rate of any kind: it only
counts how often each stage is reached, to check that the machinery fires at a sane rate. It makes NO performance claim about V2 (forward shadow data only).

  python benchmarks/v2_funnel.py          -> results/v2/funnel_history.json
"""
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "benchmarks"))
for p in ("services/gateway", "services/intelligence"):
    sys.path.insert(0, str(ROOT / p))
import p6_backtest as P6  # noqa: E402
from xau_gateway.identity import load_source_config  # noqa: E402
from xau_gateway.storage import Store  # noqa: E402
from xau_intel.m1.entry_v2 import run_v2  # noqa: E402


def load_all():
    cfg = load_source_config()
    server, sym = cfg["expected"]["server"], cfg.get("symbol_hint", "XAUUSD")
    st = Store(ROOT / "data" / "store")
    out = {}
    for tf in ("M1", "M5", "M15", "H1", "H4"):
        t = st.read_table(f"bars_{tf.lower()}", source_id="mt5_hist_bars", server=server, symbol=sym)
        o = np.argsort(np.asarray(t["time"]), kind="stable")
        g = lambda k: np.asarray(t[k])[o]
        out[tf] = {"time": g("time").astype(np.int64), "open": g("open"), "high": g("high"), "low": g("low"), "close": g("close")}
    return out


def main():
    bars = load_all()
    now = int(bars["M1"]["time"][-1]) + 60
    r = run_v2(bars, now, window=10**9)
    stages = {}
    for e in r["events"]:
        stages[e["stage"]] = stages.get(e["stage"], 0) + 1
    by_dir = {}
    for e in r["events"]:
        by_dir.setdefault(e["direction"], {}).setdefault(e["stage"], 0)
        by_dir[e["direction"]][e["stage"]] += 1
    trig_kinds = {}
    for e in r["events"]:
        if e["stage"] == "M1_TRIGGERED" and e["kind"] != "WINDOW_STATE":          # WINDOW_STATE = a state change of an existing trigger, not a new trigger
            trig_kinds[e["kind"]] = trig_kinds.get(e["kind"], 0) + 1
    days = (bars["M1"]["time"][-1] - bars["M1"]["time"][0]) / 86400
    out = {"purpose": "signal frequency only: NO price outcome, NO P/L, NO performance claim; all stored M1 history is inside the sealed holdout period",
           "m1_bars": int(len(bars["M1"]["time"])), "span_days": round(float(days), 1), "from": time.strftime("%Y-%m-%d", time.gmtime(int(bars["M1"]["time"][0]))),
           "to": time.strftime("%Y-%m-%d", time.gmtime(int(bars["M1"]["time"][-1]))), "events_by_stage": stages, "events_by_direction_and_stage": by_dir, "trigger_kinds": trig_kinds,
           "triggers": sum(trig_kinds.values()), "triggered_per_week": round(sum(trig_kinds.values()) / max(1e-9, days / 7), 2), "final_state": r["directions"], "context": r["context"],
           "note": "weeks until the pre-registered 100 triggered events at this rate: " + (str(round(100 / max(1e-9, sum(trig_kinds.values()) / max(1e-9, days / 7)), 1)) if sum(trig_kinds.values()) else "unbounded (no triggers)")}
    (ROOT / "results" / "v2").mkdir(parents=True, exist_ok=True)
    (ROOT / "results" / "v2" / "funnel_history.json").write_text(json.dumps(out, indent=1, sort_keys=True, default=lambda o: o.item() if hasattr(o, "item") else str(o)), encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("m1_bars", "span_days", "events_by_stage", "trigger_kinds", "triggered_per_week", "note")}, indent=1))


if __name__ == "__main__":
    main()
