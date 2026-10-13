from collections import deque

import numpy as np


class LatencyStats:
    def __init__(self, maxlen=20000):
        self.v = deque(maxlen=maxlen)

    def add(self, ms: float):
        self.v.append(ms)

    def snapshot(self):
        if not self.v:
            return {"n": 0}
        a = np.fromiter(self.v, float)
        return {"n": len(a), "p50": float(np.percentile(a, 50)), "p95": float(np.percentile(a, 95)),
                "p99": float(np.percentile(a, 99)), "max": float(a.max())}
