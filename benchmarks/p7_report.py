"""Render docs/research/ML_SHADOW_REPORT_DEVVAL.md from results/p7/ml_devval.json (no number is typed by hand)."""
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
r = json.loads((ROOT / "results" / "p7" / "ml_devval.json").read_text(encoding="utf-8"))
m = r["meta"]
f = lambda v, d=3: "n/a" if v is None else f"{v:.{d}f}"
d = lambda s: time.strftime("%Y-%m-%d", time.gmtime(s))
v = r["validation"]
L = ["# P7 ML shadow report: development + validation (holdout NOT loaded)", "",
     f"Generated from `results/p7/ml_devval.json` (code {m['code_sha'][:8]}{' + uncommitted changes' if m['dirty'] else ''}, {m['ml_version']}, dataset hash {m['dataset_hash'][:16]}, result fingerprint {m['result_fingerprint'][:16]}).",
     f"Protocol: ML_SHADOW_PREREGISTRATION.md (frozen before the run). Task: sign of the 4-bar (1 h) forward close change at every M15 close. Development to {d(m['boundaries']['dev_end'])}, validation to {d(m['boundaries']['val_end'])}; the holdout shared with P6 was never loaded.", "",
     "## Verdict", "", f"**{r['verdict']}**", "",
     f"Samples: {r['n_train']} train, {r['n_val']} validation (usable rows overall {m['samples_usable']}); validation up-rate {f(v['M1']['up_rate'])}. Effective independent days in validation: {v['M1']['effective_days']} (the samples overlap in time).", "",
     "## Validation", "", "| Model | AUC | AUC 95% (day bootstrap) | Brier skill vs base rate | calibration slope | accuracy |", "|---|---|---|---|---|---|"]
for k in ("M1", "B0", "B1", "B2"):
    x = v[k]
    ci = x.get("auc_day_bootstrap", {}).get("ci95")
    L.append(f"| {k} | {f(x['auc'])} | {('[' + f(ci[0]) + ', ' + f(ci[1]) + ']') if ci else 'n/a'} | {f(x['brier_skill'], 4)} | {f(x.get('calib_slope'))} | {f(x['accuracy'])} |")
L += ["", "M1 = L2 logistic regression on 14 point-in-time features; B0 = base rate; B1 = 4-bar momentum; B2 = H1-direction lookup.", "", "## Walk-forward inside development (expanding window, 5 scored blocks)", "",
      "| Block | train n | test n | AUC M1 | AUC B1 | AUC B2 | Brier skill M1 |", "|---|---|---|---|---|---|---|"]
for b in r["walk_forward"]:
    L.append(f"| {b['block']} | {b['n_train']} | {b['n_test']} | " + (f"{f(b['auc_M1'])} | {f(b['auc_B1'])} | {f(b['auc_B2'])} | {f(b['brier_skill_M1'], 4)} |" if not b.get("skipped") else "skipped | | | |"))
ru = r["rule"]
L += ["", "## Pre-registered rule", "", *[f"- {k}: {val}" for k, val in ru.items()], "",
      "## Reading this honestly", "",
      "- A validation AUC at or below 0.5 with an interval around 0.5 means the model has no demonstrated skill on this data; this was the expected outcome and is a valid result.",
      "- Overlapping 4-bar labels on every bar make the samples strongly autocorrelated: the effective sample size is the number of independent days, not the number of rows.",
      "- Nothing here is a trading claim and the model feeds nothing: it would only ever be displayed as a shadow signal.",
      "- Limits: one instrument and broker feed, about eight months of development+validation, a strongly trending year; no hyper-parameter search was done (lambda fixed); spread is not a feature (the stored M5 spread is unreliable).", ""]
(ROOT / "docs" / "research" / "ML_SHADOW_REPORT_DEVVAL.md").write_text(chr(10).join(L), encoding="utf-8")
print(chr(10).join(L)[:1800])
