"""Evidence-based detection of holes in the stored M1 history.

A hole is an interval between two consecutive M1 bars during which the NATIVE M5 series (an independent MT5 series of the same feed)
still has bars. Regular session breaks (daily break, weekends) are not holes because no native bar exists inside them. Nothing is
filled: holes are reported, stored in the quarantine table, and the higher-timeframe buckets overlapping them are excluded from the
aggregation parity with an explicit reason.
"""
from __future__ import annotations

import numpy as np


def m1_holes(m1_times, native_m5_times) -> list[dict]:
    m1 = np.sort(np.asarray(m1_times, dtype=np.int64))
    m5 = np.sort(np.asarray(native_m5_times, dtype=np.int64))
    out = []
    if len(m1) < 2 or len(m5) == 0:
        return out
    gaps = np.where(np.diff(m1) > 60)[0]
    for i in gaps:
        a, b = int(m1[i]) + 60, int(m1[i + 1])                     # missing minutes are [a, b)
        lo, hi = np.searchsorted(m5, a, side="left"), np.searchsorted(m5, b, side="left")
        if hi > lo:                                                 # native bars exist inside the gap
            out.append({"from": a, "to": b, "missing_minutes": (b - a) // 60, "native_m5_bars_inside": int(hi - lo)})
    return out


def overlaps(bucket_start: int, bucket_sec: int, holes: list[dict]) -> bool:
    end = bucket_start + bucket_sec
    return any(h["from"] < end and bucket_start < h["to"] for h in holes)
