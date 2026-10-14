"""Offline, descriptive: run the setup lifecycle machine on stored MT5 bars (setup timeframe M15, direction from H1, conflict from H4).
No MT5 connection, no outcomes, no profitability claim: it only shows what the state machine does on real data."""
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
for p in ("services/gateway", "services/intelligence"):
    sys.path.insert(0, str(ROOT / p))
from xau_gateway.identity import load_source_config
from xau_gateway.storage import Store
from xau_intel.setups.machine import current_status, run_setups
from xau_intel.setups.trend_series import align_to, direction_series
from xau_intel.structure import zigzag_swings

cfg = load_source_config()
server, sym = cfg["expected"]["server"], cfg.get("symbol_hint", "XAUUSD")
st = Store(ROOT / "data" / "store")


def load(tf):
    t = st.read_table(f"bars_{tf.lower()}", source_id="mt5_hist_bars", server=server, symbol=sym)
    o = np.argsort(np.asarray(t["time"]), kind="stable")
    return {k: np.asarray(t[k])[o].astype(float) for k in ("time", "open", "high", "low", "close")}


m15, h1, h4 = load("M15"), load("H1"), load("H4")
d_h1 = direction_series(h1["open"], h1["high"], h1["low"], h1["close"], h1["time"], "H1")
d_h4 = direction_series(h4["open"], h4["high"], h4["low"], h4["close"], h4["time"], "H4")
ctx = align_to(m15["time"], "M15", h1["time"], "H1", d_h1)
ctx4 = align_to(m15["time"], "M15", h4["time"], "H4", d_h4)
conflict = ((ctx == "UP") & (ctx4 == "DOWN")) | ((ctx == "DOWN") & (ctx4 == "UP"))
t0 = time.perf_counter()
sw = zigzag_swings(m15["high"], m15["low"], m15["close"], m15["time"], "M15", k=2.5)
res = run_setups(m15["open"], m15["high"], m15["low"], m15["close"], m15["time"], "M15", sw, ctx, ctx_conflict=conflict)
dt = time.perf_counter() - t0
ev = res["events"]
by_state = Counter(e["state"] for e in ev)
terms = Counter((e["state"], e["reasons"][0]) for e in ev if e["state"] in ("INVALIDATED", "MISSED", "EXPIRED"))
setups = {e["setup_id"] for e in ev}
print(f"M15 bars={len(m15['close'])} swings={len(sw)} setups={len(setups)} events={len(ev)} compute={dt:.2f}s")
print("H1 direction at M15 bars:", dict(Counter(ctx)), "| H4 conflicts:", int(conflict.sum()))
print("events by state:", dict(by_state))
print("terminal reasons:", dict(terms))
reached = Counter()
for sid in setups:
    s = {e["state"] for e in ev if e["setup_id"] == sid}
    for k in ("PULLBACK_IN_PROGRESS", "AT_RELEVANT_ZONE", "CONFIRMED", "ENTRY_ELIGIBLE"):
        reached[k] += k in s
print("setups reaching:", {k: f"{v}/{len(setups)}" for k, v in reached.items()})
last = current_status(res, len(m15["close"]), ctx_last=str(ctx[-1]), conflict_last=bool(conflict[-1]))
print("status at the last stored M15 bar:", last["decision_context"], last["wait_reason"], "| H1 direction:", ctx[-1], "| H4 direction:", ctx4[-1])
