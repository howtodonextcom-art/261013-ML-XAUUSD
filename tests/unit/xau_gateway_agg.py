"""Test helper: aggregate arrays to a higher timeframe by floor bucket (same rule as xau_gateway.multitf)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "gateway"))
from xau_gateway.multitf import aggregate_m1


def agg(t, o, h, l, c, sec):
    import numpy as np
    tf = {3600: "H1", 14400: "H4", 900: "M15", 300: "M5"}[sec]
    r = aggregate_m1(t, o, h, l, c, np.ones(len(t)), tf) if False else None
    t = np.asarray(t, dtype=np.int64); b = t // sec * sec
    st = np.r_[0, np.where(np.diff(b) != 0)[0] + 1]; en = np.r_[st[1:], len(t)]
    # keep only buckets whose source bars cover the whole bucket (15-min source into H1 needs 4 bars)
    full = (en - st) == (sec // (t[1] - t[0]))
    st, en = st[full], en[full]
    o, h, l, c = (np.asarray(v, float) for v in (o, h, l, c))
    return dict(time=b[st], open=o[st], high=np.maximum.reduceat(h, np.r_[st])[:len(st)] if False else np.array([h[a:z].max() for a, z in zip(st, en)]),
                low=np.array([l[a:z].min() for a, z in zip(st, en)]), close=c[en - 1])
