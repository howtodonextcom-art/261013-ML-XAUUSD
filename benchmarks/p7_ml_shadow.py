"""P7 ML shadow runner (protocol: docs/research/ML_SHADOW_PREREGISTRATION.md, frozen before the first run).

  python benchmarks/p7_ml_shadow.py          fit on development, score on validation, expanding walk-forward inside development

The P6 holdout is never loaded into the computation: bars are cut at the frozen `val_end` (results/p6/boundaries.json) before any feature is built.
Output: results/p7/ml_devval.json and one line in results/p7/ml_runs.jsonl per run (no silent re-runs).
"""
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "benchmarks"))
for p in ("services/gateway", "services/intelligence"):
    sys.path.insert(0, str(ROOT / p))
import p6_backtest as P6  # noqa: E402
from xau_intel.backtest.engine import digest  # noqa: E402
from xau_intel.ml.evaluate import evaluate, usable  # noqa: E402
from xau_intel.ml.features import ML_VERSION, build_features, build_labels  # noqa: E402

OUT = ROOT / "results" / "p7"


def clean(o):
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


def main():
    bnd = json.loads((ROOT / "results" / "p6" / "boundaries.json").read_text(encoding="utf-8"))
    full, _ = P6.load_bars()
    bars = P6.cut_bars(full, bnd["val_end"])
    del full
    feats = build_features(bars)
    t, c = feats["t"], feats["close"]
    y = build_labels(t, c)
    ok = usable(feats["X"], y)
    res = evaluate(feats["X"], y, t, ok, bnd["dev_end"], bnd["val_end"], int(t[0]))
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    dirty = bool(subprocess.run(["git", "status", "--porcelain", "--", "services/intelligence", "benchmarks"], cwd=ROOT, capture_output=True, text=True).stdout.strip())
    res["meta"] = {"ml_version": ML_VERSION, "code_sha": sha, "dirty": dirty, "boundaries": bnd, "bars_M15": int(len(t)), "samples_usable": int(ok.sum()),
                   "dataset_hash": P6.full_fingerprint(bars), "result_fingerprint": digest(clean(res)), "holdout_loaded": False,
                   "note": "shadow model: output never feeds the rule engine and never authorizes execution"}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "ml_devval.json").write_text(json.dumps(clean(res), indent=1, sort_keys=True), encoding="utf-8")
    with open(OUT / "ml_runs.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"at": int(time.time()), "sha": sha, "dirty": dirty, "fingerprint": res["meta"]["result_fingerprint"], "verdict": res["verdict"]}) + chr(10))
    v = res["validation"]
    print(json.dumps(clean({"verdict": res["verdict"], "n_train": res["n_train"], "n_val": res["n_val"], "rule": res["rule"],
                            "M1": {k: v["M1"][k] for k in ("auc", "auc_day_bootstrap", "brier_skill", "calib_slope", "accuracy")},
                            "B1_auc": v["B1"]["auc"], "B2_auc": v["B2"]["auc"], "up_rate": v["M1"]["up_rate"],
                            "walk_forward": [{k: b.get(k) for k in ("block", "auc_M1", "auc_B1", "auc_B2")} for b in res["walk_forward"]]}), indent=1))


if __name__ == "__main__":
    main()
