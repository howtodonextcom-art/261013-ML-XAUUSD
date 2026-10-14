"""Server-time helpers. MT5 tick/bar times are broker-server wall-clock expressed as an epoch (offset from UTC changes with the
broker's DST: observed +3 h on 2026-10-13). The offset is only an *estimate* from the last tick vs the local UTC clock, so it carries
a confidence; nothing safety- or integrity-critical may depend on it (catch-up and gap logic use server time only)."""
from __future__ import annotations

import numpy as np

GRID_S = 900          # real server offsets are multiples of 15 minutes
HIGH_RESIDUAL_S = 120  # |tick_age + clock skew| must be below this for the estimate to be trusted


def estimate_server_offset(tick_time_s: float, utc_now_s: float) -> tuple[int, str, float]:
    """Single-sample estimate -> (offset_s, 'PROVISIONAL', residual_s). One sample can never be trusted: a tick whose age is an
    exact multiple of 15 min is indistinguishable from a fresh tick with a different offset (e.g. connecting during the daily break)."""
    raw = tick_time_s - utc_now_s
    off = int(round(raw / GRID_S) * GRID_S)
    return off, "PROVISIONAL", float(raw - off)


class OffsetEstimator:
    """Multi-sample estimator fed ONLY with ticks that first appeared in a steady polling loop (age <= poll latency, a few seconds).
    HIGH needs >= min_samples whose median residual from the 15-minute grid is within tolerance_s; otherwise PROVISIONAL/UNKNOWN."""

    def __init__(self, min_samples: int = 5, tolerance_s: float = 5.0, maxlen: int = 50, max_spread_s: float = 120.0):
        from collections import deque
        self.v = deque(maxlen=maxlen)
        self.min_samples, self.tolerance_s, self.max_spread_s = min_samples, tolerance_s, max_spread_s
        self.provisional: tuple[int, float] | None = None

    def set_provisional(self, tick_time_s: float, utc_now_s: float):
        off, _, res = estimate_server_offset(tick_time_s, utc_now_s)
        self.provisional = (off, res)

    def add_fresh(self, tick_time_s: float, utc_now_s: float):
        self.v.append(tick_time_s - utc_now_s)

    def recent_consistent(self, off: int, n: int = 5, tol_s: float = 30.0) -> bool:
        """True only if the NEWEST n fresh samples all agree with `off` (server - utc, within tol_s). The 50-sample median can stay HIGH for several samples after a broker switch
        (stale window): this is the guard that keeps a stale offset out of the evidence and out of event stamps."""
        if len(self.v) < n:
            return False
        recent = list(self.v)[-n:]
        return all(abs(x - off) <= tol_s for x in recent)

    def snapshot(self) -> tuple[int | None, str, float | None, int]:
        if len(self.v) >= self.min_samples:
            a = np.fromiter(self.v, float)
            med = float(np.median(a))
            off = int(round(med / GRID_S) * GRID_S)
            res = med - off
            conf = "HIGH" if abs(res) <= self.tolerance_s else "LOW"
            if conf == "HIGH" and float(np.percentile(a, 90) - np.percentile(a, 10)) > self.max_spread_s:
                conf = "LOW"            # a MIXED window (broker DST switch inside it): the median of two offsets (+3 h and +2 h) is a valid-looking 2.5 h on the 15-minute grid
            return off, conf, res, len(self.v)
        if self.provisional:
            return self.provisional[0], "PROVISIONAL", self.provisional[1], len(self.v)
        return None, "UNKNOWN", None, 0


def session_boundary_bars(times, min_gap_s: int = 1800, edge_minutes: int = 5) -> dict:
    """Indices of M1 bars adjacent to a real session break (a gap >= min_gap_s between consecutive bars): the last `edge_minutes`
    bars before it and the first `edge_minutes` after it. Derived from the data, not from a hard-coded clock window."""
    t = np.asarray(times, dtype=np.int64)
    order = np.argsort(t, kind="stable")
    ts = t[order]
    gaps = np.where(np.diff(ts) >= min_gap_s)[0]
    before, after = [], []
    for g in gaps:
        before.extend(range(max(0, g - edge_minutes + 1), g + 1))
        after.extend(range(g + 1, min(len(ts), g + 1 + edge_minutes)))
    return {"before_break": order[np.array(before, dtype=int)] if before else np.array([], dtype=int),
            "after_break": order[np.array(after, dtype=int)] if after else np.array([], dtype=int),
            "n_breaks": int(len(gaps))}
