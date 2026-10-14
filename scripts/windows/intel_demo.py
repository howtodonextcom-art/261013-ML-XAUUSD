"""Offline: point-in-time multi-timeframe analysis on the local store (no MT5 connection, no gateway). Usage: intel_demo.py [--at EPOCH]"""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
for p in ("services/gateway", "services/intelligence"):
    sys.path.insert(0, str(ROOT / p))
from xau_gateway.identity import load_source_config
from xau_gateway.storage import Store
from xau_intel.regime_snapshot import analyse_snapshot, build_snapshot

ap = argparse.ArgumentParser()
ap.add_argument("--at", type=int, default=None, help="evaluation time (server epoch s); default = just after the last stored M1 bar closed")
a = ap.parse_args()
cfg = load_source_config()
server, sym = cfg["expected"]["server"], cfg.get("symbol_hint", "XAUUSD")
st = Store(ROOT / "data" / "store")
point = float(st.get_meta(f"symbol:{sym}:tick_size") or 0.01)
bars = {}
for tf in ("M1", "M5", "M15", "H1", "H4"):
    t = st.read_table(f"bars_{tf.lower()}", source_id="mt5_hist_bars", server=server, symbol=sym)
    o = np.argsort(np.asarray(t["time"]), kind="stable")
    g = lambda k: np.asarray(t[k])[o]
    bars[tf] = {"time": g("time"), "open": g("open"), "high": g("high"), "low": g("low"), "close": g("close"), "spread_price": g("spread").astype(float) * point}
t_now = a.at or int(bars["M1"]["time"][-1]) + 60
t0 = time.perf_counter()
snap = build_snapshot(bars, t_now)
res = analyse_snapshot(snap)
dt = time.perf_counter() - t0
print(f"evaluated_at={t_now} (server time {time.strftime('%Y-%m-%d %H:%M', time.gmtime(t_now))}), compute {dt:.2f}s on {sum(len(b.close) for b in snap.tfs.values())} closed bars")
for tf in ("H4", "H1", "M15", "M5", "M1"):
    r = res["timeframes"][tf]
    f = lambda v, d=2: "n/a" if v is None else round(v, d)
    print(f"{tf:3s} bars={r['bars']:6d} regime={r['regime']:20s} struct={r['structure_trend']:7s} align={r['ema_alignment']:5s} rsi={f(r['rsi'],1)} ({r['rsi_regime']}) "
          f"atr={f(r['atr'])} atr_ratio={f(r['atr_ratio50'])} atr_pct={f(r['atr_pct200'])} spread/atr={f(r['spread_atr'],3)} "
          f"labels={','.join(r['structure_labels_last'])} events={[e['event'] for e in r['events_recent']]}")
    print("      why:", "; ".join(r["reasons"]))
