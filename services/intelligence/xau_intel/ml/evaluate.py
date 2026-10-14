"""P7 splits and evaluation (protocol: docs/research/ML_SHADOW_PREREGISTRATION.md, frozen before the first run)."""
from __future__ import annotations

import numpy as np

from .features import FEATURE_NAMES, HORIZON, M15
from .model import Logistic, auc, brier, brier_skill, calibration, day_bootstrap_auc, reliability

LAMBDA = 1.0
HORIZON_S = HORIZON * M15
EMBARGO_S = 86400
IDX = {n: i for i, n in enumerate(FEATURE_NAMES)}


def usable(X: np.ndarray, y: np.ndarray) -> np.ndarray:
    return np.isfinite(X).all(axis=1) & np.isfinite(y)


def split_indices(t: np.ndarray, ok: np.ndarray, dev_end: int, val_end: int, horizon_s: int = HORIZON_S, embargo_s: int = EMBARGO_S) -> dict:
    """train: the label horizon ends at or before dev_end (no sample's future crosses a boundary). val: starts after the 24 h embargo and its horizon ends
    at or before val_end. Nothing at or after val_end is ever selected (the holdout)."""
    train = np.nonzero(ok & (t + M15 + horizon_s <= dev_end))[0]
    val = np.nonzero(ok & (t >= dev_end + embargo_s) & (t + M15 + horizon_s <= val_end))[0]
    return {"train": train, "val": val}


def wf_blocks(t0: int, dev_end: int, n_blocks: int = 6) -> list[tuple[int, int]]:
    span = (dev_end - t0) / n_blocks
    return [(int(t0 + k * span), int(t0 + (k + 1) * span)) for k in range(n_blocks)]


def _b2_fit(h1_train, y_train):
    base = float(y_train.mean())
    tab = {}
    for v in (-1.0, 0.0, 1.0):
        m = h1_train == v
        tab[v] = float(y_train[m].mean()) if m.sum() >= 30 else base
    return lambda h1: np.array([tab.get(float(v), base) for v in h1])


def fit_predict(X, y, tr, te, lam: float = LAMBDA) -> dict:
    """Returns predicted probabilities on `te` for M1, B0, B1, B2, all fitted on `tr` only."""
    base = float(y[tr].mean())
    m1 = Logistic(lam).fit(X[tr], y[tr])
    b1 = Logistic(lam).fit(X[tr][:, [IDX["ret4_atr"]]], y[tr])
    b2 = _b2_fit(X[tr, IDX["h1_dir"]], y[tr])
    return {"M1": m1.predict(X[te]), "B0": np.full(len(te), base), "B1": b1.predict(X[te][:, [IDX["ret4_atr"]]]), "B2": b2(X[te, IDX["h1_dir"]]), "base_rate": base}


def metrics(y, p, base_rate, times, boot: bool = True) -> dict:
    out = {"n": int(len(y)), "up_rate": float(np.mean(y)), "auc": auc(y, p), "brier": brier(y, p), "brier_skill": brier_skill(y, p, base_rate), "accuracy": float(np.mean((p > 0.5) == (y == 1)))}
    out.update({f"calib_{k}": v for k, v in calibration(y, p).items()})
    if boot:
        out["auc_day_bootstrap"] = day_bootstrap_auc(y, p, times)
        out["effective_days"] = out["auc_day_bootstrap"]["days"]
    return out


def evaluate(X, y, t, ok, dev_end: int, val_end: int, t0: int) -> dict:
    sp = split_indices(t, ok, dev_end, val_end)
    tr, va = sp["train"], sp["val"]
    res = {"n_train": int(len(tr)), "n_val": int(len(va)), "features": list(FEATURE_NAMES), "lambda": LAMBDA}
    pred = fit_predict(X, y, tr, va)
    res["validation"] = {k: metrics(y[va], pred[k], pred["base_rate"], t[va], boot=(k in ("M1", "B1", "B2"))) for k in ("M1", "B0", "B1", "B2")}
    res["validation"]["M1"]["reliability"] = reliability(y[va], pred["M1"])
    # expanding walk-forward inside development: fit on all earlier blocks (horizon ending before the block), score the next
    blocks = wf_blocks(t0, dev_end)
    wf = []
    for k in range(1, len(blocks)):
        lo, hi = blocks[k]
        trk = np.nonzero(ok & (t + M15 + HORIZON_S <= lo))[0]
        tek = np.nonzero(ok & (t >= lo) & (t + M15 + HORIZON_S <= min(hi, dev_end)))[0]
        if len(trk) < 200 or len(tek) < 50:
            wf.append({"block": k, "skipped": True, "n_train": int(len(trk)), "n_test": int(len(tek))})
            continue
        pk = fit_predict(X, y, trk, tek)
        wf.append({"block": k, "n_train": int(len(trk)), "n_test": int(len(tek)), "auc_M1": auc(y[tek], pk["M1"]), "auc_B1": auc(y[tek], pk["B1"]),
                   "auc_B2": auc(y[tek], pk["B2"]), "brier_skill_M1": brier_skill(y[tek], pk["M1"], pk["base_rate"])})
    res["walk_forward"] = wf
    v = res["validation"]
    m1 = v["M1"]
    n_pos = sum(1 for b in wf if not b.get("skipped") and b["auc_M1"] > 0.5)
    res["rule"] = {"auc_ci_lower_gt_0.5": m1["auc_day_bootstrap"]["ci95"][0] > 0.5, "brier_skill_gt_0": m1["brier_skill"] > 0,
                   "calibration_slope_in_0.7_1.3": bool(0.7 <= m1["calib_slope"] <= 1.3) if m1["calib_slope"] == m1["calib_slope"] else False,
                   "beats_B1_and_B2": m1["auc"] > v["B1"]["auc"] and m1["auc"] > v["B2"]["auc"], "wf_blocks_auc_gt_0.5": n_pos, "wf_blocks_scored": sum(1 for b in wf if not b.get("skipped"))}
    ok_all = (res["rule"]["auc_ci_lower_gt_0.5"] and res["rule"]["brier_skill_gt_0"] and res["rule"]["calibration_slope_in_0.7_1.3"] and res["rule"]["beats_B1_and_B2"]
              and n_pos >= 4)
    res["verdict"] = "SHOWS_PREDICTIVE_EVIDENCE_ON_VALIDATION" if ok_all else "NO_EVIDENCE_OF_PREDICTIVE_SKILL"
    return res
