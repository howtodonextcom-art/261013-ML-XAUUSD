"""Forward evaluation of the V2 shadow log (frozen protocol: docs/research/M1_ENTRY_V2_PREREGISTRATION.md).

  python benchmarks/v2_shadow_eval.py

Reads data/shadow/v2_events.jsonl (events logged live after the registration commit afd688e). Until at least 100 triggers AND 30 days exist it prints
INSUFFICIENT_EVIDENCE and reads NO bar. Afterwards it simulates the registered entries on the stored M1 bars and writes results/v2/forward_eval.json.
It never touches the sealed P6/P7 holdout period for any V2 claim: only events logged after registration are used.
"""
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/gateway", "services/intelligence"):
    sys.path.insert(0, str(ROOT / p))
from xau_intel.m1.evaluate_v2 import evaluate, gate  # noqa: E402

REGISTRATION_UTC = 1791960048        # commit afd688e
LOG = ROOT / "data" / "shadow" / "v2_events.jsonl"


def main() -> int:
    events = [json.loads(x) for x in LOG.read_text(encoding="utf-8").splitlines() if x.strip()] if LOG.exists() else []
    offset = 10800                    # server UTC offset measured live (HIGH); only used to compare server-time event stamps with the registration instant
    reg = REGISTRATION_UTC + offset
    now = int(time.time()) + offset
    g = gate(events, now, reg)
    if g is not None:
        print(json.dumps(g, indent=1))
        return 3
    from xau_gateway.identity import load_source_config
    from xau_gateway.storage import Store
    cfg = load_source_config()
    st = Store(ROOT / "data" / "store")
    t = st.read_table("bars_m1", source_id="mt5_hist_bars", server=cfg["expected"]["server"], symbol=cfg.get("symbol_hint", "XAUUSD"))
    o = np.argsort(np.asarray(t["time"]), kind="stable")
    point = float(st.get_meta("symbol:XAUUSD:tick_size") or 0.01)
    g_ = lambda k: np.asarray(t[k])[o]
    m1 = {"time": g_("time").astype(np.int64), "open": g_("open"), "high": g_("high"), "low": g_("low"), "close": g_("close"), "spread": g_("spread").astype(float) * point}
    m1 = {k: v[m1["time"] >= reg] for k, v in m1.items()}          # only bars from the registration instant on
    res = evaluate(events, m1, now, reg)
    (ROOT / "results" / "v2").mkdir(parents=True, exist_ok=True)
    (ROOT / "results" / "v2" / "forward_eval.json").write_text(json.dumps(res, indent=1, sort_keys=True, default=lambda x: x.item() if hasattr(x, "item") else str(x)), encoding="utf-8")
    print(json.dumps({k: res[k] for k in ("status", "verdict", "trades", "base") if k in res}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
