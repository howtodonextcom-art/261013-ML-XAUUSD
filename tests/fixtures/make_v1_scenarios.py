"""Builds tests/fixtures/xau_v1_scenarios.npz + v1_scenarios.json from the stored DEVELOPMENT + VALIDATION history (bars closed at val_end: the sealed holdout is never read).

Run once (it needs the local store; the tests do NOT):  .\\.venv\\Scripts\\python.exe tests\\fixtures\\make_v1_scenarios.py

The npz holds historical XAUUSD M15/H1/H4 bars (market prices only, integer cents; no account data). The json lists moments ("now" = a closed-bar time) chosen by the BACKTEST path
(`eligible_decisions`, setup-1 events) at which the production path must give a specific answer; tests/unit/test_v1_production_path.py re-derives every answer through the
PRODUCTION path (compute_heavy -> make_decision -> v1_event_from_decision), which is a different code path.
"""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
for p in ("services/gateway", "services/intelligence", "benchmarks"):
    sys.path.insert(0, str(ROOT / p))
from p6_backtest import cut_bars, load_bars  # noqa: E402
from xau_intel.backtest.engine import eligible_decisions, setup_run, spread_at  # noqa: E402
from xau_intel.setups.machine import current_status  # noqa: E402

OUT = Path(__file__).parent


def main() -> int:
    bars, point = load_bars()
    b = json.loads((ROOT / "results" / "p6" / "boundaries.json").read_text())
    bars = cut_bars(bars, int(b["val_end"]))
    sr = setup_run(bars)
    ev = sr["res"]["events"]
    decs = eligible_decisions(sr, bars["M5"], dataset_version="fixture")
    sc: dict[str, dict] = {}

    def add(name, now, **meta):
        if name not in sc:
            sc[name] = {"now": int(now), **meta}

    for d in decs:
        act = d["decision"]["action"]
        direction = "BUY" if d["decision"]["setup"]["direction"] == "BUY" else "SELL"
        if act in ("BUY", "SELL"):
            add(f"{act}_PUBLISHED", d["decision_time"], expect_action=act)
        elif act == "BLOCKED":
            add(f"{direction}_BLOCKED", d["decision_time"], expect_action="BLOCKED", expect_reason=str(d["decision"]["primary_reason"]).split(":")[0])
    firsts = {}
    for e in ev:
        firsts.setdefault(e["state"], e)
    for state, name in (("SETUP_FORMING", "IMPULSE_NO_PULLBACK"), ("MISSED", "MISSED"), ("INVALIDATED", "INVALIDATED"), ("EXPIRED", "EXPIRED")):
        if state in firsts:
            add(name, firsts[state]["known_at"], expect_event_state=state, setup_id=firsts[state]["setup_id"])
    active_bars = np.zeros(len(sr["t"]), dtype=bool)
    by_id = {}
    for e in ev:
        by_id.setdefault(e["setup_id"], []).append(e)
    for es in by_id.values():
        active_bars[es[0]["bar_idx"]:es[-1]["bar_idx"] + 1] = True
    for j in range(2000, len(sr["t"])):                                              # no active setup, a direction exists, no conflict: NO_VALID_IMPULSE (both sides)
        c = str(sr["ctx"][j])
        if not active_bars[j] and not bool(sr["conflict"][j]):
            if c == "DOWN":
                add("NO_VALID_IMPULSE_DOWN", int(sr["t"][j]) + 900, expect_action="WAIT", expect_reason="NO_VALID_IMPULSE")
            if c == "UP":
                add("NO_VALID_IMPULSE_UP", int(sr["t"][j]) + 900, expect_action="WAIT", expect_reason="NO_VALID_IMPULSE")
        if bool(sr["conflict"][j]) and c in ("UP", "DOWN"):
            add("CONFLICT", int(sr["t"][j]) + 900, expect_action="WAIT")
        if c == "NONE" and not active_bars[j]:
            add("NO_DIRECTION", int(sr["t"][j]) + 900, expect_action="WAIT", expect_reason="NO_DIRECTION")
    for v in sc.values():                                                            # the M5 spread known at that moment (the backtest uses the same lookup)
        sp = spread_at(bars["M5"], v["now"])
        v["spread"] = 0.30 if sp is None else round(float(sp), 4)
    keep_tf = {tf: bars[tf] for tf in ("M15", "H1", "H4")}
    arrays = {}
    for tf, v in keep_tf.items():
        arrays[f"{tf}_time"] = v["time"].astype(np.int64)
        for k in ("open", "high", "low", "close"):
            arrays[f"{tf}_{k}"] = np.rint(np.asarray(v[k]) * 100).astype(np.int32)
    np.savez_compressed(OUT / "xau_v1_scenarios.npz", **arrays)
    (OUT / "v1_scenarios.json").write_text(json.dumps({"kind": "development+validation replay fixtures (historical, not live)", "spread": 0.30, "scenarios": sc}, indent=1, sort_keys=True), encoding="utf-8")
    print({k: v["now"] for k, v in sc.items()})
    return 0


if __name__ == "__main__":
    sys.exit(main())
