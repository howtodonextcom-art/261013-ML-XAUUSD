"""V1 BUY / SELL signal funnel (Level 6.2): where do opportunities stop? Development + validation data ONLY: the store is read, then every bar closed after `val_end` is cut away BEFORE any computation (the sealed holdout contributes nothing).

  .\\.venv\\Scripts\\python.exe benchmarks\\v1_signal_funnel.py        -> results/v1/signal_funnel.json

Per direction, unique setup ids that reached each stage of the PRODUCTION path (setup-1 state machine + the real decide() with risk-1 / gate-1 on the reference account):
context -> impulse -> pullback -> zone -> confirmation -> entry eligible -> risk PASS. Also: top reasons at the terminal states, share of bars with a usable context,
and the length of the stretches in which no setup was active (the WAIT that a human sees). Nothing is tuned; thresholds are the frozen ones.
"""
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/gateway", "services/intelligence", "benchmarks"):
    sys.path.insert(0, str(ROOT / p))
from p6_backtest import cut_bars, load_bars  # noqa: E402
from xau_intel.backtest.engine import eligible_decisions, setup_run  # noqa: E402

STAGES = (("impulse", {"SETUP_FORMING"}), ("pullback", {"PULLBACK_IN_PROGRESS"}), ("zone", {"AT_RELEVANT_ZONE"}), ("confirmation", {"CONFIRMED"}),
          ("entry_window", {"ENTRY_WINDOW"}), ("entry_eligible", {"ENTRY_ELIGIBLE"}))
TERMINAL = ("MISSED", "INVALIDATED", "EXPIRED")


def funnel(bars: dict, dataset_version: str) -> dict:
    sr = setup_run(bars)
    ev = sr["res"]["events"]
    by_id: dict[str, list[dict]] = {}
    for e in ev:
        by_id.setdefault(e["setup_id"], []).append(e)
    out = {"bars_m15": int(len(sr["t"])), "from": int(sr["t"][0]), "to": int(sr["t"][-1]), "dataset_version": dataset_version, "directions": {}}
    ctx = np.asarray(sr["ctx"])
    conflict = np.asarray(sr["conflict"])
    out["context_share"] = {"UP": float(np.mean(ctx == "UP")), "DOWN": float(np.mean(ctx == "DOWN")), "NONE_OR_UNKNOWN": float(np.mean(~np.isin(ctx, ["UP", "DOWN"]))),
                            "H4_conflict": float(np.mean(conflict))}
    decisions = eligible_decisions(sr, bars["M5"], dataset_version=dataset_version)
    dec_by_id = {d["setup_id"]: d["decision"] for d in decisions}
    for dname, ctx_name in (("BUY", "UP"), ("SELL", "DOWN")):
        ids = [sid for sid, es in by_id.items() if es[0]["direction"] == dname]
        row = {"context_bars": int(np.sum((ctx == ctx_name) & ~conflict)), "setups_unique": len(ids)}
        for name, states in STAGES:
            row[name] = sum(1 for sid in ids if any(e["state"] in states for e in by_id[sid]))
        term = Counter()
        why = Counter()
        for sid in ids:
            last = by_id[sid][-1]
            if last["state"] in TERMINAL:
                term[last["state"]] += 1
                why[last["state"] + ":" + ",".join(last.get("reasons") or [])] += 1
        row["terminal"] = dict(term)
        row["terminal_reasons_top"] = why.most_common(6)
        ds = [dec_by_id[sid] for sid in ids if sid in dec_by_id]
        row["risk_pass_at_first_eligible_bar"] = sum(1 for d in ds if d["action"] == dname)       # PROXY: one decision per setup at its first ENTRY_ELIGIBLE bar close (bar close as bid, M5 spread at that close); live, the decision is re-evaluated every 2 s over the entry window
        row["risk_blocked_at_first_eligible_bar"] = sum(1 for d in ds if d["action"] == "BLOCKED")
        row["blocked_reasons_top"] = Counter(str(d["primary_reason"]).split(":")[0] + ":" + str(d["primary_reason"]).split(":")[1].split("(")[0].strip() if ":" in str(d["primary_reason"]) else str(d["primary_reason"])
                                             for d in ds if d["action"] == "BLOCKED").most_common(6)
        out["directions"][dname] = row
    # WAIT stretches: bars with no active setup (any direction) between a context and the next setup
    active = np.zeros(len(sr["t"]), dtype=bool)
    for sid, es in by_id.items():
        j0, j1 = es[0]["bar_idx"], es[-1]["bar_idx"]
        if es[-1]["state"] in TERMINAL or True:
            active[j0:j1 + 1] = True
    runs, n = [], 0
    for a in active:
        if not a:
            n += 1
        elif n:
            runs.append(n)
            n = 0
    if n:
        runs.append(n)
    out["no_active_setup"] = {"bars_share": float(np.mean(~active)), "stretches": len(runs), "median_bars": float(np.median(runs)) if runs else 0.0, "max_bars": int(max(runs)) if runs else 0,
                              "note": "an M15 bar is 15 minutes"}
    return out


def main() -> int:
    bars, _ = load_bars()
    b = json.loads((ROOT / "results" / "p6" / "boundaries.json").read_text())
    bars = cut_bars(bars, int(b["val_end"]))                      # development + validation only: the sealed holdout starts after val_end and is never loaded here
    res = funnel(bars, "ds-0.2:dev+val")
    res["kind"] = "DEVELOPMENT_AND_VALIDATION (historical replay, not forward, not live)"
    res["strategy_version"] = "cand-1[setup-1+risk-1+gate-1]"
    res["holdout_bars_used_in_computation"] = False
    res["decision_basis"] = "first ENTRY_ELIGIBLE bar per setup (backtest decision builder), a proxy for live publication"
    (ROOT / "results" / "v1").mkdir(parents=True, exist_ok=True)
    (ROOT / "results" / "v1" / "signal_funnel.json").write_text(json.dumps(res, indent=1, sort_keys=True, default=str), encoding="utf-8")
    print(json.dumps(res, indent=1, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
