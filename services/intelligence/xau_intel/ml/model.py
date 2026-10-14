"""P7 model and metrics: numpy only, deterministic (no random state in the fit)."""
from __future__ import annotations

import numpy as np

DAY = 86400


def sigmoid(z):
    z = np.clip(z, -35, 35)
    return 1.0 / (1.0 + np.exp(-z))


class Logistic:
    """L2-regularised logistic regression on standardised features, Newton/IRLS, intercept not penalised. Standardisation uses the TRAINING data only."""

    def __init__(self, lam: float = 1.0, iters: int = 50):
        self.lam, self.iters = lam, iters
        self.mu = self.sd = self.w = None

    def fit(self, X, y):
        X, y = np.asarray(X, float), np.asarray(y, float)
        self.mu, self.sd = X.mean(0), X.std(0)
        self.sd = np.where(self.sd > 1e-12, self.sd, 1.0)
        Z = np.hstack([np.ones((len(X), 1)), (X - self.mu) / self.sd])
        w = np.zeros(Z.shape[1])
        pen = np.eye(Z.shape[1]) * self.lam
        pen[0, 0] = 0.0
        for _ in range(self.iters):
            p = sigmoid(Z @ w)
            g = Z.T @ (p - y) + pen @ w
            H = (Z * (p * (1 - p))[:, None]).T @ Z + pen + 1e-9 * np.eye(Z.shape[1])
            step = np.linalg.solve(H, g)
            w = w - step
            if np.max(np.abs(step)) < 1e-9:
                break
        self.w = w
        return self

    def predict(self, X):
        Z = np.hstack([np.ones((len(X), 1)), (np.asarray(X, float) - self.mu) / self.sd])
        return sigmoid(Z @ self.w)


def auc(y, p) -> float:
    """Rank AUC with average ranks for ties (Mann-Whitney)."""
    y, p = np.asarray(y), np.asarray(p, float)
    pos, neg = int((y == 1).sum()), int((y == 0).sum())
    if pos == 0 or neg == 0:
        return float("nan")
    order = np.argsort(p, kind="mergesort")
    ranks = np.empty(len(p))
    sp = p[order]
    i = 0
    while i < len(sp):
        j = i
        while j + 1 < len(sp) and sp[j + 1] == sp[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return float((ranks[y == 1].sum() - pos * (pos + 1) / 2.0) / (pos * neg))


def brier(y, p) -> float:
    return float(np.mean((np.asarray(p, float) - np.asarray(y, float)) ** 2))


def brier_skill(y, p, base_rate: float) -> float:
    b0 = brier(y, np.full(len(y), base_rate))
    return float(1.0 - brier(y, p) / b0) if b0 > 0 else float("nan")


def calibration(y, p, iters: int = 50) -> dict:
    """Logistic recalibration y ~ sigmoid(a + b * logit(p)): b = 1, a = 0 is perfect. Slope b < 1 means over-confident."""
    y, p = np.asarray(y, float), np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6)
    z = np.log(p / (1 - p))
    if np.std(z) < 1e-9:
        return {"slope": float("nan"), "intercept": float("nan")}
    A = np.column_stack([np.ones(len(z)), z])
    w = np.array([0.0, 1.0])
    for _ in range(iters):
        q = sigmoid(A @ w)
        g = A.T @ (q - y)
        H = (A * (q * (1 - q))[:, None]).T @ A + 1e-9 * np.eye(2)
        step = np.linalg.solve(H, g)
        w = w - step
        if np.max(np.abs(step)) < 1e-9:
            break
    return {"slope": float(w[1]), "intercept": float(w[0])}


def reliability(y, p, bins: int = 10) -> list:
    y, p = np.asarray(y, float), np.asarray(p, float)
    qs = np.quantile(p, np.linspace(0, 1, bins + 1))
    out = []
    for i in range(bins):
        m = (p >= qs[i]) & ((p <= qs[i + 1]) if i == bins - 1 else (p < qs[i + 1]))
        if m.sum():
            out.append({"n": int(m.sum()), "mean_p": float(p[m].mean()), "freq": float(y[m].mean())})
    return out


def day_bootstrap_auc(y, p, times, n_boot: int = 2000, seed: int = 20261014) -> dict:
    """AUC with a 95% interval from resampling whole calendar days (the samples overlap in time, so i.i.d. resampling would be far too optimistic)."""
    y, p, times = np.asarray(y), np.asarray(p, float), np.asarray(times)
    day = times // DAY
    ud = np.unique(day)
    idx_by_day = [np.nonzero(day == d)[0] for d in ud]
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(n_boot):
        pick = rng.integers(0, len(ud), len(ud))
        ii = np.concatenate([idx_by_day[k] for k in pick])
        v = auc(y[ii], p[ii])
        if v == v:
            vals.append(v)
    lo, hi = np.percentile(vals, [2.5, 97.5])
    return {"auc": auc(y, p), "ci95": [float(lo), float(hi)], "n_boot": n_boot, "days": int(len(ud)), "seed": seed}
