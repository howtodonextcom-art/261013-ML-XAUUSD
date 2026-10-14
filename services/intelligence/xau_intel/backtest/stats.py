"""Trade statistics and day-block bootstrap (P6). Deterministic: every random generator is seeded by the caller."""
from __future__ import annotations

import numpy as np

DAY = 86400


def summarize(trades: list[dict], cost: str = "base") -> dict:
    r = np.array([t["r"][cost] for t in trades], dtype=float)
    n = len(r)
    if n == 0:
        return {"n": 0}
    order = np.argsort([t["exit_time"] for t in trades], kind="stable")
    eq = np.cumsum(r[order])
    peak = np.maximum.accumulate(np.concatenate([[0.0], eq]))[1:]
    gp, gl = r[r > 0].sum(), -r[r < 0].sum()
    streak = best = 0
    for v in r[order]:
        streak = streak + 1 if v < 0 else 0
        best = max(best, streak)
    return {"n": n, "mean_r": float(r.mean()), "median_r": float(np.median(r)), "win_rate": float((r > 0).mean()), "sum_r": float(r.sum()),
            "profit_factor": float(gp / gl) if gl > 0 else None, "max_drawdown_r": float((peak - eq).max()), "longest_losing_streak": int(best)}


def day_bootstrap(trades: list[dict], cost: str = "base", n_boot: int = 2000, seed: int = 20261014) -> dict:
    """Resample whole calendar days of decisions (block = day). Returns mean R and its 95% interval."""
    if not trades:
        return {"n": 0}
    days: dict[int, list[float]] = {}
    for t in trades:
        days.setdefault(int(t["decision_time"]) // DAY, []).append(t["r"][cost])
    keys = sorted(days)
    rng = np.random.default_rng(seed)
    sums = np.array([sum(days[k]) for k in keys])
    cnts = np.array([len(days[k]) for k in keys])
    m = len(keys)
    idx = rng.integers(0, m, size=(n_boot, m))
    means = sums[idx].sum(axis=1) / cnts[idx].sum(axis=1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    return {"n": int(cnts.sum()), "days": m, "mean_r": float(sums.sum() / cnts.sum()), "ci95": [float(lo), float(hi)], "n_boot": n_boot, "seed": seed}


def breakdown(trades: list[dict], key, cost: str = "base") -> dict:
    g: dict = {}
    for t in trades:
        g.setdefault(key(t), []).append(t)
    return {str(k): summarize(v, cost) for k, v in sorted(g.items(), key=lambda kv: str(kv[0]))}


def month_concentration(trades: list[dict], cost: str = "base") -> float | None:
    """Largest single-month share of the TOTAL positive-or-negative R (|month sum| / sum of |month sums|); None when no trades."""
    m: dict = {}
    for t in trades:
        m[int(t["decision_time"]) // (30 * DAY)] = m.get(int(t["decision_time"]) // (30 * DAY), 0.0) + t["r"][cost]
    tot = sum(abs(v) for v in m.values())
    return None if not m or tot == 0 else float(max(abs(v) for v in m.values()) / tot)
