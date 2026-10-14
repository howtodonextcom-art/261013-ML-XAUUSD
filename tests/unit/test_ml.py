"""P7 ML shadow: metrics, model determinism, point-in-time features (mutation-checked), label/split isolation. Synthetic data only."""
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in ("services/intelligence", "tests/unit"):
    sys.path.insert(0, str(ROOT / p))
from xau_intel.ml import features as F  # noqa: E402
from xau_intel.ml.evaluate import HORIZON_S, evaluate, split_indices, usable, wf_blocks  # noqa: E402
from xau_intel.ml.features import FEATURE_NAMES, build_features, build_labels  # noqa: E402
from xau_intel.ml.model import Logistic, auc, brier, brier_skill, calibration, day_bootstrap_auc, reliability, sigmoid  # noqa: E402
from test_backtest import synth, truncate  # noqa: E402


def test_auc_known_values():
    assert auc([0, 0, 1, 1], [0.1, 0.2, 0.8, 0.9]) == 1.0
    assert auc([0, 0, 1, 1], [0.9, 0.8, 0.2, 0.1]) == 0.0
    assert auc([0, 1, 0, 1], [0.5, 0.5, 0.5, 0.5]) == 0.5                      # all tied
    assert auc([0, 0, 1, 1], [0.1, 0.4, 0.35, 0.8]) == pytest.approx(0.75)     # the textbook example
    assert np.isnan(auc([1, 1], [0.2, 0.3]))
    rng = np.random.default_rng(0)
    y, p = rng.integers(0, 2, 20000), rng.random(20000)
    assert abs(auc(y, p) - 0.5) < 0.02


def test_brier_and_skill():
    y = np.array([1, 0, 1, 0.0])
    assert brier(y, np.array([1, 0, 1, 0.0])) == 0.0
    assert brier(y, np.full(4, 0.5)) == pytest.approx(0.25)
    assert brier_skill(y, np.full(4, 0.5), 0.5) == pytest.approx(0.0)
    assert brier_skill(y, np.array([0.9, 0.1, 0.9, 0.1]), 0.5) > 0.9


def test_logistic_recovers_a_planted_signal_deterministically_and_standardises_on_train_only():
    rng = np.random.default_rng(1)
    X = rng.normal(size=(6000, 3))
    y = (rng.random(6000) < sigmoid(1.5 * X[:, 0])).astype(float)
    a = Logistic(1.0).fit(X[:4000], y[:4000])
    b = Logistic(1.0).fit(X[:4000], y[:4000])
    assert np.array_equal(a.w, b.w)                                             # no randomness in the fit
    assert a.w[1] > 1.0 and abs(a.w[2]) < 0.25 and abs(a.w[3]) < 0.25
    p = a.predict(X[4000:])
    assert auc(y[4000:], p) > 0.75
    mu_before = a.mu.copy()
    a.predict(X[4000:] * 100 + 50)                                              # scoring data never changes the stored standardisation
    assert np.array_equal(mu_before, a.mu)


def test_calibration_slope_detects_overconfidence():
    rng = np.random.default_rng(2)
    p_true = rng.uniform(0.2, 0.8, 30000)
    y = (rng.random(30000) < p_true).astype(float)
    good = calibration(y, p_true)
    assert abs(good["slope"] - 1.0) < 0.08 and abs(good["intercept"]) < 0.06
    over = calibration(y, sigmoid(3.0 * np.log(p_true / (1 - p_true))))        # the same ranking, far too confident
    assert over["slope"] < 0.5
    rel = reliability(y, p_true)
    assert len(rel) == 10 and all(abs(r["mean_p"] - r["freq"]) < 0.06 for r in rel)


def test_day_bootstrap_ci_is_wider_than_naive_for_autocorrelated_samples_and_deterministic():
    rng = np.random.default_rng(3)
    t = np.repeat(np.arange(40) * 86400, 50) + np.tile(np.arange(50) * 900, 40)
    day_effect = np.repeat(rng.normal(size=40), 50)
    y = (rng.random(2000) < sigmoid(day_effect)).astype(float)
    p = sigmoid(day_effect + rng.normal(0, 1.0, 2000))
    a, b = day_bootstrap_auc(y, p, t, n_boot=300), day_bootstrap_auc(y, p, t, n_boot=300)
    assert a == b and a["ci95"][0] < a["auc"] < a["ci95"][1] and a["days"] == 40


# ------------------------------------------------------------------ point in time
@pytest.fixture(scope="module")
def sy():
    bars = synth(n5=48 * 300)
    return bars, build_features(bars)


def prefix_equal(bars, full, fracs=(0.4, 0.7, 0.9)):
    n = len(bars["M15"]["time"])
    for fr in fracs:
        cut = int(bars["M15"]["time"][int(n * fr)])
        pre = build_features(truncate(bars, cut))
        m = len(pre["t"])
        if not np.array_equal(pre["X"], full["X"][:m], equal_nan=True):
            return False
    return True


def test_features_are_point_in_time_prefix_invariant(sy):
    bars, full = sy
    assert full["X"].shape[1] == len(FEATURE_NAMES) and np.isfinite(full["X"]).all(axis=1).sum() > 500
    assert prefix_equal(bars, full)


def test_future_corruption_does_not_change_past_features(sy):
    bars, full = sy
    cut = int(bars["M15"]["time"][int(len(bars["M15"]["time"]) * 0.6)])
    bad = {tf: {k: v.copy() for k, v in b.items()} for tf, b in bars.items()}
    for tf, b in bad.items():
        after = b["time"] >= cut
        for k in ("open", "high", "low", "close"):
            b[k][after] = b[k][after] * 2.0 + 300
    fb = build_features(bad)
    m = int(np.searchsorted(fb["t"], cut))
    assert np.array_equal(fb["X"][:m], full["X"][:m], equal_nan=True)


def test_the_lookahead_detector_detects_a_peeking_feature(sy, monkeypatch):
    bars, _ = sy
    real = F.atr_fn

    def peeking(h, l, c, n=14):
        a = real(h, l, c, n)
        return np.concatenate([a[10:], np.full(10, np.nan)])                   # ATR of 10 bars in the future
    monkeypatch.setattr(F, "atr_fn", peeking)
    peek_full = build_features(bars)
    assert not prefix_equal(bars, peek_full), "the prefix test is blind to a feature that peeks into the future"


def test_labels_use_only_the_future_and_drop_ties_gaps_and_the_end():
    t = np.arange(10) * 900
    c = np.array([1, 2, 3, 4, 5, 4, 3, 3, 3, 3.0])
    y = build_labels(t, c, horizon=4)
    exp = np.array([1, 1, np.nan, 0, 0, 0, np.nan, np.nan, np.nan, np.nan])      # sample 2 is a tie (3 vs 3): dropped; the last 4 have no complete future
    assert np.array_equal(y, exp, equal_nan=True)
    t2 = t.copy()
    t2[3:] += 900                                                              # a missing bar inside the horizon of samples 0..2
    y2 = build_labels(t2, c, horizon=4)
    assert np.isnan(y2[0]) and np.isnan(y2[1]) and np.isnan(y2[2])
    tie = build_labels(np.arange(6) * 900, np.array([1, 1, 1, 1, 1, 1.0]), horizon=4)
    assert np.isnan(tie).all()


def test_splits_never_cross_a_boundary_and_never_touch_the_holdout():
    t = np.arange(0, 400 * 900, 900)
    ok = np.ones(len(t), dtype=bool)
    dev_end, val_end = 150 * 900, 300 * 900
    sp = split_indices(t, ok, dev_end, val_end)
    assert sp["train"].size and sp["val"].size
    assert (t[sp["train"]] + 900 + HORIZON_S <= dev_end).all()                 # the future of a training sample ends before the boundary
    assert (t[sp["val"]] >= dev_end + 86400).all() and (t[sp["val"]] + 900 + HORIZON_S <= val_end).all()
    assert t[sp["val"]].max() + 900 + HORIZON_S <= val_end and (t[sp["train"]] < dev_end).all()
    assert not np.intersect1d(sp["train"], sp["val"]).size
    blocks = wf_blocks(0, 600_000)
    assert len(blocks) == 6 and blocks[0][0] == 0 and blocks[-1][1] == 600_000 and all(a[1] == b[0] for a, b in zip(blocks, blocks[1:]))


def test_evaluate_runs_end_to_end_is_deterministic_and_reports_no_skill_on_noise():
    rng = np.random.default_rng(5)
    n = 9000
    t = (np.arange(n) * 900).astype(np.int64)
    X = rng.normal(size=(n, len(FEATURE_NAMES)))
    y = (rng.random(n) < 0.5).astype(float)                                    # pure noise: there is nothing to learn
    ok = np.ones(n, dtype=bool)
    dev_end, val_end = int(t[int(n * 0.6)]), int(t[int(n * 0.8)])
    a = evaluate(X, y, t, ok, dev_end, val_end, int(t[0]))
    b = evaluate(X, y, t, ok, dev_end, val_end, int(t[0]))
    import json
    assert json.dumps(a, sort_keys=True, default=float) == json.dumps(b, sort_keys=True, default=float)      # NaN-safe equality (constant predictors have no calibration slope)
    assert a["verdict"] == "NO_EVIDENCE_OF_PREDICTIVE_SKILL" and a["n_val"] > 500
    assert abs(a["validation"]["M1"]["auc"] - 0.5) < 0.05


def test_evaluate_finds_a_planted_signal():
    rng = np.random.default_rng(6)
    n = 12000
    t = (np.arange(n) * 900).astype(np.int64)
    X = rng.normal(size=(n, len(FEATURE_NAMES)))
    y = (rng.random(n) < sigmoid(1.2 * X[:, 3])).astype(float)                 # macd_hist_atr truly drives the label
    dev_end, val_end = int(t[int(n * 0.6)]), int(t[int(n * 0.8)])
    r = evaluate(X, y, t, np.ones(n, dtype=bool), dev_end, val_end, int(t[0]))
    assert r["validation"]["M1"]["auc"] > 0.65 and r["rule"]["beats_B1_and_B2"] and r["rule"]["wf_blocks_scored"] == 5
