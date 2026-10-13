"""Compares ticks the gateway captured live (source=mt5_py_poll, persisted) with MT5's own tick history for the same span.
Reports per-fingerprint multiset differences, i.e. ticks missing from the live capture and ticks only in history.
Read-only. Usage: live_vs_history.py [store_root] [settle_s=600]"""
import sys
import time
from collections import Counter
from pathlib import Path

import MetaTrader5 as mt5
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "gateway"))
from xau_gateway.storage import Store  # noqa: E402

root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / "data" / "store"
settle = int(sys.argv[2]) if len(sys.argv) > 2 else 600
st = Store(root)
files = [f for f in st.files("ticks") if f["chunk"].startswith("live-")]
import pyarrow.parquet as pq
tab = __import__("pyarrow").concat_tables([pq.read_table(root / f["path"]) for f in files])
live = {k: np.asarray(tab[k]) for k in ("time_msc", "bid", "ask", "flags", "quality_flags")}
# use only the most recent contiguous capture session: ticks from the last 'span' where msc >= start of last run
lo, hi = int(live["time_msc"].min()), int(live["time_msc"].max())
print(f"live ticks={len(live['time_msc'])} span_s={(hi-lo)/1000:.0f}  late_flagged={int(sum('LATE_INSERT' in q for q in live['quality_flags']))}")
assert mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
# compare only the interior of the span (skip first/last 5 s: capture start/stop edges)
a, b = lo + 5000, hi - 5000
h = mt5.copy_ticks_range("XAUUSD", a // 1000, b // 1000 + 2, mt5.COPY_TICKS_ALL)
h = h[(h["time_msc"] >= a) & (h["time_msc"] < b)]
fp = lambda m, bi, ak, fl: (int(m), float(bi), float(ak), int(fl))  # noqa: E731
H = Counter(fp(*x) for x in zip(h["time_msc"], h["bid"], h["ask"], h["flags"]))
sel = (live["time_msc"] >= a) & (live["time_msc"] < b)
L = Counter(fp(*x) for x in zip(live["time_msc"][sel], live["bid"][sel], live["ask"][sel], live["flags"][sel]))
miss_live = H - L   # in history, not captured live
extra_live = L - H  # captured live, absent from history
print(f"compared window {(b-a)/1000:.0f}s: history={sum(H.values())} live={sum(L.values())} "
      f"missing_in_live={sum(miss_live.values())} only_in_live={sum(extra_live.values())}")
for k, v in list(miss_live.items())[:8]:
    print("  missing_in_live", k, "x", v)
for k, v in list(extra_live.items())[:8]:
    print("  only_in_live", k, "x", v)
mt5.shutdown()
