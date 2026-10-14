"""Swing-detector evaluation on the local store (offline).
Default: the original comparison fractal(n=3) vs zig-zag(k=2.0) (docs/research/SWING_DETECTION_DECISION.md).
--k-grid 2.5 3.0 4.0 : the pre-registered k experiment (docs/research/SWING_K_PREREGISTRATION.md), zig-zag only."""
import argparse
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

ap = argparse.ArgumentParser()
ap.add_argument("--k-grid", type=float, nargs="*", default=None)
args = ap.parse_args()
cfg = load_source_config()
server, sym = cfg["expected"]["server"], cfg.get("symbol_hint", "XAUUSD")
st = Store(ROOT / "data" / "store")
cands = [("zigzag", {"k": k}) for k in args.k_grid] if args.k_grid else [("fractal", {"n": 3}), ("zigzag", {"k": 2.0})]
out = {}
for tf, days in (("M15", 120), ("H1", 365)):
    t = st.read_table(f"bars_{tf.lower()}", source_id="mt5_hist_bars", server=server, symbol=sym)
    o = np.argsort(np.asarray(t["time"]), kind="stable")
    a = {k: np.asarray(t[k])[o].astype(float) for k in ("time", "open", "high", "low", "close")}
    keep = a["time"] >= a["time"][-1] - days * 86400
    T, H, L, C = (a[k][keep] for k in ("time", "high", "low", "close"))
    n = len(T)
    res = {"bars": n}
    for name, kw in cands:
        label = f"{name}({','.join(f'{k}={v}' for k, v in kw.items())})"
        sw = fractal_swings(H, L, T.astype(np.int64), tf, **kw) if name == "fractal" else zigzag_swings(H, L, C, T, tf, **kw)
        real = [s for s in sw if not s.window_start_artifact]
        delays = [s.known_idx - s.idx for s in real]
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
        d = round(100 * len(real) / n, 2)
        res[label] = {"swings": len(real), "per_100_bars": d, "S1_in_band_4_10": 4 <= d <= 10, "median_delay_bars": float(np.median(delays)) if delays else None,
                      "G1_no_lookahead": g1, "G2_no_repaint": g2, "G3_fields": g3, "cut_points_checked": len(cuts)}
    out[tf] = res
print(json.dumps(out, indent=1))
