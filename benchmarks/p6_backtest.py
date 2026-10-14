"""P6 backtest runner (protocol: docs/research/BACKTEST_PREREGISTRATION.md + BACKTEST_IMPLEMENTATION_CLARIFICATIONS.md).

  python benchmarks/p6_backtest.py --phase devval      development + validation + walk-forward (holdout bars are NEVER loaded into the computation)
  python benchmarks/p6_backtest.py --phase seal        freeze: records code SHA, config hash and dataset hash (clean git tree required)
  python benchmarks/p6_backtest.py --phase holdout     opens the holdout exactly ONCE, only if sealed and the validation gate passed

Output: results/p6/*.json (+ trades_*.jsonl) and docs/research/BACKTEST_REPORT_*.md. Deterministic: same code + data => same fingerprints.
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/gateway", "services/intelligence"):
    sys.path.insert(0, str(ROOT / p))
from xau_gateway.identity import load_source_config  # noqa: E402
from xau_gateway.storage import Store  # noqa: E402
from xau_intel.backtest import candidates as C  # noqa: E402
from xau_intel.backtest.engine import COSTS, ENGINE_VERSION, TIMEOUT_M5, canon, digest, setup_run  # noqa: E402
from xau_intel.backtest.stats import breakdown, day_bootstrap, month_concentration, summarize  # noqa: E402
from xau_intel.structure import TF_SEC  # noqa: E402

OUT = ROOT / "results" / "p6"
EMBARGO = 86400
N_SEEDS = 500
MIN_VAL_TRADES = 20
MIN_HOLDOUT_TRADES = 100


def load_bars() -> tuple[dict, str]:
    cfg = load_source_config()
    server, sym = cfg["expected"]["server"], cfg.get("symbol_hint", "XAUUSD")
    st = Store(ROOT / "data" / "store")
    point = float(st.get_meta(f"symbol:{sym}:tick_size") or 0.01)
    bars = {}
    for tf in ("M5", "M15", "H1", "H4"):
        t = st.read_table(f"bars_{tf.lower()}", source_id="mt5_hist_bars", server=server, symbol=sym)
        q = st.quarantined(f"bars_{tf.lower()}", server, sym)                  # quarantined bars are excluded, never repaired
        keep = np.array([int(x) not in q for x in np.asarray(t["time"])], dtype=bool)
        o = np.nonzero(keep)[0][np.argsort(np.asarray(t["time"])[keep], kind="stable")]
        g = lambda k: np.asarray(t[k])[o]
        bars[tf] = {"time": g("time").astype(np.int64), "open": g("open"), "high": g("high"), "low": g("low"), "close": g("close"),
                    "spread": g("spread").astype(float) * point}
    return bars, point


def cut_bars(bars: dict, cut: int | None) -> dict:
    """Keep only bars fully CLOSED at `cut` (None = everything). This is what keeps the holdout out of memory in the dev/val phase."""
    if cut is None:
        return bars
    return {tf: {k: v[b["time"] + TF_SEC[tf] <= cut] for k, v in b.items()} for tf, b in bars.items()}


def dataset_fingerprint(bars: dict) -> str:
    return digest({tf: {k: digest([float(x) for x in np.asarray(v)[:: max(1, len(v) // 4000)]]) + str(len(v)) for k, v in b.items()} for tf, b in bars.items()})


def full_fingerprint(bars: dict) -> str:
    import hashlib
    h = hashlib.sha256()
    for tf in sorted(bars):
        for k in sorted(bars[tf]):
            h.update(np.ascontiguousarray(bars[tf][k]).tobytes())
    return h.hexdigest()


def git(*a) -> str:
    return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True).stdout.strip()


def code_state() -> dict:
    return {"sha": git("rev-parse", "HEAD"), "dirty": bool(git("status", "--porcelain", "--", "services/intelligence", "benchmarks/p6_backtest.py", "configs")),
            "engine_version": ENGINE_VERSION}


def config_hash() -> str:
    pol = (ROOT / "configs" / "risk" / "policy.json").read_bytes()
    from xau_intel.backtest import engine
    return digest({"policy": pol.decode(), "timeout_m5": TIMEOUT_M5, "costs": COSTS, "risk": repr(engine.RISK), "gate": repr(engine.GATE), "spec": repr(engine.XAU_SPEC),
                   "embargo": EMBARGO, "seeds": N_SEEDS})


def boundaries(m5t: np.ndarray, fixed: dict | None = None) -> dict:
    """Split points from the stored span (first/last M5 bar). With `fixed` (the sealed boundaries) NOTHING is recomputed: a store that kept growing after
    the seal cannot move the holdout window onto bars already seen in validation."""
    if fixed:
        return {k: int(fixed[k]) for k in ("t0", "t1", "dev_end", "val_end")}
    t0 = int(m5t[0])
    t1 = int(m5t[-1] + 300)
    s = t1 - t0
    return {"t0": t0, "t1": t1, "dev_end": t0 + int(0.6 * s), "val_end": t0 + int(0.8 * s)}


def sel(trades, lo, hi):
    return [t for t in trades if lo <= t["decision_time"] < hi]


def seg_block(trades, lo, hi, *, cut_exit=None):
    ts = sel(trades, lo, hi)
    dropped = 0
    if cut_exit is not None:
        keep = [t for t in ts if t["exit_time"] <= cut_exit]
        dropped = len(ts) - len(keep)
        ts = keep
    out = {"n": len(ts), "dropped_crossing_boundary": dropped}
    if not ts:
        return out
    out["base"] = summarize(ts)
    out["bootstrap_base"] = day_bootstrap(ts, "base")
    out["costs"] = {k: summarize(ts, k)["mean_r"] for k in COSTS}
    out["bootstrap_slip0.3"] = day_bootstrap(ts, "slip0.3")
    out["optimistic_ambiguous_mean_r"] = float(np.mean([t["r_optimistic"] for t in ts if t["r_optimistic"] is not None])) if any(t["r_optimistic"] is not None for t in ts) else None
    out["ambiguous_bars_total"] = int(sum(t["ambiguous_bars"] for t in ts))
    out["month_concentration"] = month_concentration(ts)
    out["by_direction"] = breakdown(ts, lambda t: t["direction"])
    out["by_h1_context"] = breakdown(ts, lambda t: t.get("regime"))
    out["by_server_session"] = breakdown(ts, lambda t: ("00-08" if (t["decision_time"] // 3600) % 24 < 8 else "08-16" if (t["decision_time"] // 3600) % 24 < 16 else "16-24"))
    out["by_month"] = breakdown(ts, lambda t: time.strftime("%Y-%m", time.gmtime(t["decision_time"])))
    out["by_outcome"] = {k: sum(1 for t in ts if t["outcome"] == k) for k in sorted({t["outcome"] for t in ts})}
    return out


def run_all(bars: dict, bnd: dict, segs: dict, cut_exit: dict, tag: str) -> dict:
    m5 = bars["M5"]
    ver = full_fingerprint(bars)
    sr = setup_run(bars)
    res = {"meta": {"tag": tag, "code": code_state(), "config_hash": config_hash(), "dataset_hash": ver, "boundaries": bnd,
                    "bars": {tf: int(len(b["time"])) for tf, b in bars.items()}, "segments": segs, "cost_levels": COSTS}, "candidates": {}}
    all_trades: dict = {}
    (t4, k4), _ = C.c4(bars, m5, ver, sr)
    (t5, k5), _ = C.c5(bars, m5, ver)
    t7, k7 = C.c7(bars, m5, ver, sr)
    t3, k3 = C.c3(sr, m5)
    (t6, k6), _ = C.c6(bars, m5, ver, sr)
    cand = {"C0": ([], {}), "C3": (t3, k3), "C4": (t4, k4), "C5": (t5, k5), "C6": (t6, k6), "C7": (t7, k7)}
    for name, (tr, cnt) in cand.items():
        all_trades[name] = tr
        r = {"counters": cnt, "trades_total": len(tr), "trades_fingerprint": digest(tr), "segments": {}}
        for sname, (lo, hi) in segs.items():
            r["segments"][sname] = seg_block(tr, lo, hi, cut_exit=cut_exit.get(sname))
        res["candidates"][name] = r
    res["candidates"]["C6"]["identical_to_C4"] = digest(t6) == digest(t4)
    # C2: buy and hold per segment (USD per ounce, no R)
    res["candidates"]["C2"] = {"segments": {s: C.c2(m5, lo, hi) for s, (lo, hi) in segs.items()}}
    # C1: random entries paired with the C4 geometry of the same segment
    c1 = {}
    for sname, (lo, hi) in segs.items():
        paired = sel(t4, lo, hi)
        runs = C.c1(paired, sr, m5, lo, hi, N_SEEDS) if paired else []
        means = [summarize(x["trades"])["mean_r"] for x in runs if x["trades"]]
        c4_mean = summarize(paired)["mean_r"] if paired else None
        c1[sname] = {"seeds": len(runs), "seeds_with_trades": len(means), "mean_r_percentiles": None if not means else {str(q): float(np.percentile(means, q)) for q in (5, 25, 50, 75, 95)},
                     "c4_mean_r": c4_mean, "c4_above_p95": None if not means or c4_mean is None else bool(c4_mean > np.percentile(means, 95)),
                     "share_of_seeds_at_or_above_c4": None if not means or c4_mean is None else float(np.mean([m >= c4_mean for m in means]))}
    res["candidates"]["C1"] = {"segments": c1}
    return res, all_trades


def write(res, trades, name):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}.json").write_text(json.dumps(res, indent=1, sort_keys=True, default=lambda o: o.item() if hasattr(o, "item") else str(o)), encoding="utf-8")
    for c, tr in trades.items():
        with open(OUT / f"{name}_trades_{c}.jsonl", "w", encoding="utf-8") as f:
            for t in tr:
                f.write(canon(t) + "\n")


def phase_devval():
    full, _ = load_bars()
    bf = OUT / "boundaries.json"                                  # frozen at the first run: later growth of the store never moves the split points
    fixed = json.loads(bf.read_text(encoding="utf-8")) if bf.exists() else None
    bnd = boundaries(full["M5"]["time"], fixed)
    if not bf.exists():
        OUT.mkdir(parents=True, exist_ok=True)
        bf.write_text(json.dumps(bnd, indent=1), encoding="utf-8")
    hold_start = bnd["val_end"]
    bars = cut_bars(full, hold_start)                    # the holdout bars are dropped HERE, before any computation
    assert int(bars["M5"]["time"][-1]) + 300 <= hold_start
    del full
    t0, de, ve = bnd["t0"], bnd["dev_end"], bnd["val_end"]
    segs = {"dev": (t0, de), "val": (de + EMBARGO, ve)}
    span = (ve - t0) / 4
    for i in range(4):
        segs[f"wf{i + 1}"] = (int(t0 + i * span), int(t0 + (i + 1) * span))
    res, trades = run_all(bars, bnd, segs, {"dev": de}, "devval")
    c4v = res["candidates"]["C4"]["segments"]["val"]
    n, mean = c4v.get("n", 0), c4v.get("base", {}).get("mean_r")
    gate = "INSUFFICIENT_EVIDENCE" if n < MIN_VAL_TRADES else ("VALIDATION_PASS" if mean is not None and mean > 0 else "NO_EVIDENCE_OF_EDGE")
    res["validation_gate"] = {"c4_val_trades": n, "c4_val_mean_r": mean, "min_trades": MIN_VAL_TRADES, "verdict": gate,
                              "holdout_may_open": gate == "VALIDATION_PASS"}
    write(res, trades, "devval")
    with open(OUT / "devval_runs.jsonl", "a", encoding="utf-8") as f:                        # every run is logged: no silent re-runs until a gate passes
        f.write(canon({"at": int(time.time()), "sha": res["meta"]["code"]["sha"], "dirty": res["meta"]["code"]["dirty"], "dataset_hash": res["meta"]["dataset_hash"],
                       "c4_fingerprint": res["candidates"]["C4"]["trades_fingerprint"], "verdict": gate}) + chr(10))
    print(json.dumps({"gate": res["validation_gate"], "bars": res["meta"]["bars"], "dataset_hash": res["meta"]["dataset_hash"][:16]}, indent=1))


def verify_seal(seal: dict, state: dict) -> str | None:
    """None when the current state matches the seal, else the reason it does not (pure: unit-tested)."""
    if state["dirty"] or state["sha"] != seal["code"]["sha"]:
        return "code differs from the sealed commit (or the tree is dirty)"
    if state["config_hash"] != seal["config_hash"]:
        return "configuration differs from the sealed configuration"
    if state["devval_dataset_hash"] != seal["devval_dataset_hash"]:
        return "the dev/validation dataset changed since the seal"
    return None


def phase_seal():
    if (OUT / "holdout_seal.json").exists():
        sys.exit("REFUSED: a seal already exists; it is never overwritten")
    st = code_state()
    if st["dirty"]:
        sys.exit("REFUSED: uncommitted changes in services/intelligence, benchmarks/p6_backtest.py or configs; commit first so the seal names a real SHA")
    dv = json.loads((OUT / "devval.json").read_text(encoding="utf-8"))
    if not dv["validation_gate"]["holdout_may_open"]:
        sys.exit(f"REFUSED: the validation gate says {dv['validation_gate']['verdict']}; the holdout stays sealed and unopened")
    full, _ = load_bars()
    bnd = {k: dv["meta"]["boundaries"][k] for k in ("t0", "t1", "dev_end", "val_end")}
    h = full_fingerprint(cut_bars(full, bnd["val_end"]))
    if h != dv["meta"]["dataset_hash"] or dv["meta"]["code"]["sha"] != st["sha"]:
        sys.exit("REFUSED: devval.json was not produced by this commit and this data; re-run --phase devval first")
    seal = {"code": st, "config_hash": config_hash(), "boundaries": bnd, "devval_dataset_hash": h, "devval_c4_fingerprint": dv["candidates"]["C4"]["trades_fingerprint"],
            "sealed_at": int(time.time())}
    (OUT / "holdout_seal.json").write_text(json.dumps(seal, indent=1), encoding="utf-8")
    print("sealed:", json.dumps(seal))


def phase_holdout(dry: bool = False):
    seal_p, opened_p = OUT / "holdout_seal.json", OUT / "holdout_opened.json"
    if not dry:
        if opened_p.exists():
            sys.exit("REFUSED: the holdout has already been opened once; it is not unseen any more")
        if not seal_p.exists():
            sys.exit("REFUSED: no seal (validation gate not passed or seal not created)")
    seal = json.loads(seal_p.read_text(encoding="utf-8")) if seal_p.exists() else None
    full, _ = load_bars()
    bnd = boundaries(full["M5"]["time"], seal["boundaries"] if seal else None)
    cur = {**code_state(), "config_hash": config_hash(), "devval_dataset_hash": full_fingerprint(cut_bars(full, bnd["val_end"]))}
    if seal and not dry:
        why = verify_seal(seal, cur)
        if why:
            sys.exit("REFUSED: " + why)
        # committed-marker discipline: the marker is written BEFORE any holdout number is computed, and a crash is recorded in it (a crashed run still counts as opened)
        opened_p.write_text(json.dumps({"opened_at": int(time.time()), "sha": cur["sha"], "status": "STARTED"}), encoding="utf-8")
    data = cut_bars(full, bnd["t1"]) if not dry else cut_bars(full, bnd["val_end"])          # bars that appeared after the seal are ignored
    segs = {"holdout": (bnd["val_end"] + EMBARGO, bnd["t1"])} if not dry else {"holdout": (bnd["dev_end"] + EMBARGO, bnd["val_end"])}
    try:
        res, trades = run_all(data, bnd, segs, {}, "holdout" if not dry else "holdout_dry_run_on_validation_window")
        write(res, trades, "holdout" if not dry else "holdout_dry")
    except Exception as e:  # noqa: BLE001
        if not dry:
            opened_p.write_text(json.dumps({"opened_at": int(time.time()), "sha": cur["sha"], "status": "CRASHED", "error": type(e).__name__}), encoding="utf-8")
        raise
    if not dry:
        opened_p.write_text(json.dumps({"opened_at": int(time.time()), "sha": cur["sha"], "status": "COMPLETED"}), encoding="utf-8")
    print(json.dumps(res["candidates"]["C4"]["segments"]["holdout"].get("base"), indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=("devval", "seal", "holdout"), required=True)
    ap.add_argument("--dry", action="store_true", help="holdout phase only: run the whole pipeline on the VALIDATION window (no holdout bar is used, nothing is marked opened)")
    a = ap.parse_args()
    phase_holdout(a.dry) if a.phase == "holdout" else {"devval": phase_devval, "seal": phase_seal}[a.phase]()
