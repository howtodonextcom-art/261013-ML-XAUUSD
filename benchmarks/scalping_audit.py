"""Scalping opportunity audit (Level 6.5, P0): what do V1 and V2 skip, by design, and is the treatment of BUY and SELL symmetric?

  .\\.venv\\Scripts\\python.exe benchmarks\\scalping_audit.py        -> results/v1/scalping_audit.json

COUNTS AND CLASSIFICATIONS ONLY. No price outcome, no P/L, no R, no expectancy is computed anywhere in this file. Historical sections use bars closed at `val_end`
(development + validation, the sealed holdout is cut away before any computation). The forward section uses the V2 forward log (events known after the registration instant,
which is after the sealed period) and the stored bars up to now only to classify V1's state at each trigger time.
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
from xau_intel.backtest.engine import setup_run  # noqa: E402
from xau_intel.setups.patterns import candle_patterns  # noqa: E402
from xau_intel.setups.trend_series import align_to, direction_series, structure_trend_series  # noqa: E402
from xau_intel.indicators import atr as atr_fn  # noqa: E402

TERMINAL = ("MISSED", "INVALIDATED", "EXPIRED")


def mirrored(bars: dict) -> dict:
    out = {}
    for tf, b in bars.items():
        out[tf] = {**b, "open": -b["open"], "high": -b["low"], "low": -b["high"], "close": -b["close"]}
    return out


def state_counts(sr: dict) -> dict:
    by = {}
    for e in sr["res"]["events"]:
        by.setdefault((e["direction"], e["state"]), set()).add(e["setup_id"])
    return {f"{d}|{s}": len(v) for (d, s), v in sorted(by.items())}


def symmetry(bars: dict) -> dict:
    """V1 on the real prices and on the price-mirrored series: BUY on one must equal SELL on the other, state by state."""
    a = state_counts(setup_run({k: bars[k] for k in ("M15", "H1", "H4")}))
    b = state_counts(setup_run({k: mirrored(bars)[k] for k in ("M15", "H1", "H4")}))
    swap = {"BUY": "SELL", "SELL": "BUY"}
    rows, equal = [], True
    for key, v in a.items():
        d, s = key.split("|")
        mk = f"{swap[d]}|{s}"
        rows.append({"state": s, "real": key, "real_count": v, "mirrored": mk, "mirrored_count": b.get(mk, 0)})
        equal &= v == b.get(mk, 0)
    return {"states_compared": len(rows), "all_equal": bool(equal), "rows": rows}


def active_arrays(sr: dict, n: int) -> dict:
    act = {"BUY": np.zeros(n, dtype=bool), "SELL": np.zeros(n, dtype=bool)}
    by = {}
    for e in sr["res"]["events"]:
        by.setdefault(e["setup_id"], []).append(e)
    for es in by.values():
        j0 = es[0]["bar_idx"]
        j1 = es[-1]["bar_idx"] if es[-1]["state"] in TERMINAL else n - 1
        act[es[0]["direction"]][j0:j1 + 1] = True
    return act


def m5_relations(bars: dict) -> dict:
    """Classify every closed M5 bar by (M5 structure) x (H1 direction) x (H4 conflict) and by whether V1 had an active setup of the SAME direction; plus the M5 pa-1 pattern bars."""
    sr = setup_run({k: bars[k] for k in ("M15", "H1", "H4")})
    t15 = np.asarray(sr["t"], dtype=np.int64)
    act = active_arrays(sr, len(t15))
    m5 = bars["M5"]
    t5 = np.asarray(m5["time"], dtype=np.int64)
    o, h, l, c = (np.asarray(m5[k], dtype=float) for k in ("open", "high", "low", "close"))
    trend5 = structure_trend_series(h, l, c, t5.astype(float), "M5")
    h1 = bars["H1"]
    d1 = direction_series(h1["open"], h1["high"], h1["low"], h1["close"], h1["time"], "H1")
    h4 = bars["H4"]
    d4 = direction_series(h4["open"], h4["high"], h4["low"], h4["close"], h4["time"], "H4")
    ctx1 = align_to(t5.astype(float), "M5", np.asarray(h1["time"], dtype=float), "H1", d1)
    ctx4 = align_to(t5.astype(float), "M5", np.asarray(h4["time"], dtype=float), "H4", d4)
    conflict = ((ctx1 == "UP") & (ctx4 == "DOWN")) | ((ctx1 == "DOWN") & (ctx4 == "UP"))
    j15 = np.searchsorted(t15 + 900, t5 + 300, side="right") - 1          # last M15 bar closed at the close of the M5 bar
    atr5 = atr_fn(h, l, c, 14)
    pat = candle_patterns(o, h, l, c, atr5)
    table, pattern_table = Counter(), Counter()
    for j in range(len(t5)):
        tr = str(trend5[j])
        if tr not in ("UP", "DOWN"):
            table[("M5_" + tr, "-", "-")] += 1
            continue
        want = "UP" if tr == "UP" else "DOWN"
        side = "BUY" if tr == "UP" else "SELL"
        rel = "ALIGNED" if ctx1[j] == want else "COUNTERTREND" if ctx1[j] in ("UP", "DOWN") else ("H1_NONE" if ctx1[j] == "NONE" else "H1_UNKNOWN")
        if conflict[j]:
            rel += "+H4_CONFLICT"
        v1 = "V1_ACTIVE_SAME_SIDE" if (j15[j] >= 0 and act[side][j15[j]]) else "V1_NO_SETUP_SAME_SIDE"
        table[("M5_" + tr, rel, v1)] += 1
        hit = bool(pat["any_bull"][j]) if side == "BUY" else bool(pat["any_bear"][j])
        if hit:
            pattern_table[("M5_" + tr, rel, v1)] += 1
    fmt = lambda c_: {" | ".join(k): v for k, v in sorted(c_.items())}  # noqa: E731
    total = sum(table.values())
    return {"m5_bars": int(total), "bars_by_m5_structure_h1_relation_v1_coverage": fmt(table), "m5_pattern_bars_in_m5_structure_direction": fmt(pattern_table),
            "pattern_bars_total": int(sum(pattern_table.values()))}


def forward_v2_vs_v1() -> dict:
    """The V2 forward triggers (live, after the registration, outside the sealed period) against V1's state at the same moment (setup events from the stored bars)."""
    log = ROOT / "data" / "shadow" / "v2_events.jsonl"
    if not log.exists():
        return {"status": "NO_FORWARD_LOG"}
    from xau_gateway.identity import load_source_config
    from xau_gateway.setup_history import load_store_bars
    from xau_gateway.storage import Store
    from xau_intel.m1.evaluate_v2 import read_log, triggers_of
    evs, bad = read_log(log.read_text(encoding="utf-8", errors="replace"))
    trig = triggers_of(evs)
    cfg = load_source_config()
    st = Store(ROOT / "data" / "store")
    b = load_store_bars(st, cfg["expected"]["server"], cfg.get("symbol_hint", "XAUUSD"))
    sr = setup_run(b)
    t15 = np.asarray(sr["t"], dtype=np.int64)
    act = active_arrays(sr, len(t15))
    out = Counter()
    for e in trig:
        j = int(np.searchsorted(t15 + 900, e["known_at"], side="right")) - 1
        side = e["direction"]
        if j < 0:
            out["NO_BAR"] += 1
            continue
        same, other = bool(act[side][j]), bool(act["SELL" if side == "BUY" else "BUY"][j])
        ctx = str(sr["ctx"][j])
        out[f"{'V1_ACTIVE_SAME_SIDE' if same else 'V1_NO_SETUP_SAME_SIDE'}|H1_{ctx}|{'H4_CONFLICT' if bool(sr['conflict'][j]) else 'no_H4_conflict'}"] += 1
    return {"v2_forward_triggers": len(trig), "unreadable_lines": bad, "v1_state_at_trigger": dict(out),
            "note": "V2 itself requires H1 direction and no H4 conflict (ctx_ok), so every V2 trigger has an H1 direction; the rows show whether V1 had a setup in the same direction at that moment"}


def main() -> int:
    bars, _ = load_bars()
    b = json.loads((ROOT / "results" / "p6" / "boundaries.json").read_text())
    bars = cut_bars(bars, int(b["val_end"]))                        # development + validation only
    res = {"kind": "COUNTS AND CLASSIFICATIONS ONLY (no outcome, no P/L, no R); development + validation bars closed at val_end", "holdout_bars_used_in_computation": False,
           "bars": {tf: int(len(v["time"])) for tf, v in bars.items()}}
    res["v1_buy_sell_symmetry_on_mirrored_prices"] = symmetry(bars)
    res["m5_relations"] = m5_relations(bars)
    res["forward_v2_vs_v1"] = forward_v2_vs_v1()
    (ROOT / "results" / "v1").mkdir(parents=True, exist_ok=True)
    (ROOT / "results" / "v1" / "scalping_audit.json").write_text(json.dumps(res, indent=1, sort_keys=True, default=str), encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k != "v1_buy_sell_symmetry_on_mirrored_prices"}, indent=1, sort_keys=True, default=str))
    print("SYMMETRY all_equal:", res["v1_buy_sell_symmetry_on_mirrored_prices"]["all_equal"], "states", res["v1_buy_sell_symmetry_on_mirrored_prices"]["states_compared"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
