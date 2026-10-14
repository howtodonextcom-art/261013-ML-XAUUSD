"""Pre-registered swing-detector comparison (docs/research/SWING_DETECTION_DECISION.md). Offline: reads the local store only."""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/gateway", "services/intelligence"):
    sys.path.insert(0, str(ROOT / p))
from xau_gateway.identity import load_source_config
from xau_gateway.storage import Store
from xau_intel.structure import fractal_swings, swings_known_by, zigzag_swings

cfg = load_source_config()
server, sym = cfg["expected"]["server"], cfg.get("symbol_hint", "XAUUSD")
st = Store(ROOT / "data" / "store")
out = {}
for tf, days in (("M15", 120), ("H1", 365)):
    t = st.read_table(f"bars_{tf.lower()}", source_id="mt5_hist_bars", server=server, symbol=sym)
    o = np.argsort(np.asarray(t["time"]), kind="stable")
    a = {k: np.asarray(t[k])[o].astype(float) for k in ("time", "open", "high", "low", "close")}
    sec = 900 if tf == "M15" else 3600
    keep = a["time"] >= a["time"][-1] - days * 86400
    T, H, L, C = (a[k][keep] for k in ("time", "high", "low", "close"))
    n = len(T)
    res = {"bars": n}
    for name, fn, kw in (("fractal", fractal_swings, {"n": 3}), ("zigzag", None, {"k": 2.0})):
        sw = fractal_swings(H, L, T.astype(np.int64), tf, **kw) if name == "fractal" else zigzag_swings(H, L, C, T, tf, **kw)
        delays = [s.known_idx - s.idx for s in sw]
        # G1/G2 on real bars at sampled cut points
        key = lambda s: (s.kind, s.idx, s.known_idx, s.price)
        cuts = list(range(250, n, max(1, n // 60)))
        prev, g1, g2 = set(), True, True
        for c in cuts:
            known = swings_known_by(H, L, C, T, tf, c, method=name, **kw)
            exp = [s for s in sw if s.known_idx <= c]
            if [key(s) for s in known] != [key(s) for s in exp]:
                g1 = False
            now = {key(s) for s in known}
            if not prev <= now:
                g2 = False
            prev = now
        g3 = all(s.known_at > s.formed_at and s.source_timeframe == tf for s in sw)
        res[name] = {"swings": len(sw), "per_100_bars": round(100 * len(sw) / n, 2), "median_delay_bars": float(np.median(delays)) if delays else None,
                     "G1_no_lookahead": g1, "G2_no_repaint": g2, "G3_fields": g3, "cut_points_checked": len(cuts)}
    out[tf] = res
print(json.dumps(out, indent=1))
