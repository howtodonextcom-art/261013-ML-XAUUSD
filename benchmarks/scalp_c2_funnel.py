"""C2 counts-only funnel on the stored M1 history (Level 6.5, P5): how often does the scalping candidate fire, on which side, with which H1 label, and how much of it
do V1 and V2 already cover?  COUNTS ONLY: no price outcome, no P/L, no R, no expectancy.  The stored M1 history lies inside the sealed holdout period, so this is
a frequency/coverage description of the code, never evidence of performance.

  python benchmarks/scalp_c2_funnel.py   -> results/v1/scalp_c2_funnel.json
"""
import json
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/gateway", "services/intelligence", "benchmarks"):
    sys.path.insert(0, str(ROOT / p))
from xau_gateway.identity import load_source_config  # noqa: E402
from xau_gateway.setup_history import load_store_bars  # noqa: E402
from xau_gateway.storage import Store  # noqa: E402
from xau_intel.backtest.engine import setup_run  # noqa: E402
from xau_intel.m1.entry_v2 import run_v2  # noqa: E402
from xau_intel.scalp.c2 import run_c2  # noqa: E402
from scalping_audit import active_arrays  # noqa: E402


def main() -> int:
    cfg = load_source_config()
    b = load_store_bars(Store(ROOT / "data" / "store"), cfg["expected"]["server"], cfg.get("symbol_hint", "XAUUSD"), tfs=("M1", "M5", "M15", "H1", "H4"))
    now = int(b["M1"]["time"][-1]) + 60
    t0 = time.perf_counter()
    c2 = run_c2(b, now, window=10 ** 9)
    c2_s = time.perf_counter() - t0
    v2 = run_v2(b, now, window=10 ** 9)
    trig = [e for e in c2["events"] if e["stage"] == "M1_TRIGGERED" and e["kind"] != "WINDOW_STATE"]
    v2t = [e for e in v2["events"] if e["stage"] == "M1_TRIGGERED" and e["kind"] != "WINDOW_STATE"]
    sr = setup_run({k: b[k] for k in ("M15", "H1", "H4")})
    t15 = np.asarray(sr["t"], dtype=np.int64)
    act = active_arrays(sr, len(t15))
    cov = Counter()
    v2_by_dir = {d: np.array(sorted(e["known_at"] for e in v2t if e["direction"] == d)) for d in ("BUY", "SELL")}
    for e in trig:
        j = int(np.searchsorted(t15 + 900, e["known_at"], side="right")) - 1
        cov["v1_active_same_side" if j >= 0 and act[e["direction"]][j] else "v1_no_setup_same_side"] += 1
        a = v2_by_dir[e["direction"]]
        cov["v2_trigger_within_5min" if len(a) and np.any(np.abs(a - e["known_at"]) <= 300) else "v2_no_trigger_within_5min"] += 1
    days = max(1, (int(b["M1"]["time"][-1]) - int(b["M1"]["time"][0])) / 86400)
    res = {"kind": "COUNTS ONLY (no outcome, no P/L, no R); stored M1 history is inside the sealed holdout period: a description of frequency, not evidence",
           "m1_bars": int(len(b["M1"]["time"])), "days": round(days, 1), "c2_compute_seconds_whole_history": round(c2_s, 2),
           "c2_triggers": len(trig), "v2_triggers": len(v2t), "c2_per_day": round(len(trig) / days, 2), "v2_per_day": round(len(v2t) / days, 2),
           "by_direction": dict(Counter(e["direction"] for e in trig)), "by_kind": dict(Counter(e["kind"] for e in trig)), "by_alignment": dict(Counter(e["alignment"] for e in trig)),
           "terminal_states": dict(Counter(e["stage"] for e in c2["events"] if e["stage"] in ("MISSED", "INVALIDATED", "EXPIRED"))), "coverage": dict(cov),
           "h4_conflict_triggers": sum(1 for e in trig if e.get("h4_conflict"))}
    (ROOT / "results" / "v1").mkdir(parents=True, exist_ok=True)
    (ROOT / "results" / "v1" / "scalp_c2_funnel.json").write_text(json.dumps(res, indent=1, sort_keys=True), encoding="utf-8")
    print(json.dumps(res, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
