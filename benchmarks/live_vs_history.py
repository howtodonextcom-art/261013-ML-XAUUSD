"""Compares ticks the gateway captured live (persisted) with MT5's own tick history for the same span. Read-only.

Isolation: only the selected live capture sessions (default: the most recent one; --sessions s1,s2 or --all-sessions for a
restart/crash check over the union) and only the configured server/symbol are compared. Terminal and expected identity come
from configs/source.json (same verify_identity as the live source), not from hardcoded paths.

Reports per-fingerprint multiset differences: ticks missing from the live capture / only in the live capture.
Usage: live_vs_history.py [--root data/store] [--sessions a,b | --all-sessions] [--trim-s 5] [--json out.json]
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import MetaTrader5 as mt5
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "gateway"))
from xau_gateway.identity import load_source_config, verify_identity  # noqa: E402
from xau_gateway.quality import LIVE_TICKS  # noqa: E402
from xau_gateway.storage import Store  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--root", default=str(Path(__file__).resolve().parents[1] / "data" / "store"))
ap.add_argument("--sessions", default=None)
ap.add_argument("--all-sessions", action="store_true")
ap.add_argument("--trim-s", type=float, default=5.0, help="ignore the first/last N seconds (capture start/stop edges)")
ap.add_argument("--json", default=None)
a = ap.parse_args()

cfg = load_source_config()
terminal, expected = cfg.get("terminal_path"), cfg.get("expected") or {}
symbol = cfg.get("symbol_hint", "XAUUSD")
server = expected.get("server")
if not terminal or not server:
    sys.exit("configs/source.json must pin terminal_path and expected.server")

st = Store(Path(a.root))
files = [f for f in st.files("ticks", source_id=LIVE_TICKS, server=server, symbol=symbol) if f["chunk"].startswith("live-")]
sessions = sorted({f["session"] for f in files if f["session"]}, key=lambda s: min(f["min_key"] for f in files if f["session"] == s))
if a.sessions:
    chosen = a.sessions.split(",")
elif a.all_sessions:
    chosen = sessions
else:
    chosen = sessions[-1:]
files = [f for f in files if f["session"] in chosen]
if not files:
    sys.exit(f"no live chunks for sessions {chosen}; available: {sessions}")
tab = pa.concat_tables([pq.read_table(Path(a.root) / f["path"]) for f in files], promote_options="default")
live = {k: np.asarray(tab[k]) for k in ("time_msc", "bid", "ask", "flags", "quality_flags")}
lo, hi = int(live["time_msc"].min()), int(live["time_msc"].max())
print(f"sessions={chosen} live ticks={len(live['time_msc'])} span_s={(hi - lo) / 1000:.0f} "
      f"late_flagged={int(sum('LATE_INSERT' in q for q in live['quality_flags']))}")

if not mt5.initialize(path=terminal):
    sys.exit(f"initialize failed {mt5.last_error()}")
bad = verify_identity(mt5.terminal_info(), mt5.account_info(), terminal, expected)
if bad:
    mt5.shutdown()
    sys.exit(f"SOURCE_MISMATCH: {bad}")
x0, x1 = lo + int(a.trim_s * 1000), hi - int(a.trim_s * 1000)
h = mt5.copy_ticks_range(symbol, x0 // 1000, x1 // 1000 + 2, mt5.COPY_TICKS_ALL)
h = h[(h["time_msc"] >= x0) & (h["time_msc"] < x1)]


def fp(m, b, k, f):
    return (int(m), float(b), float(k), int(f))


H = Counter(fp(*x) for x in zip(h["time_msc"], h["bid"], h["ask"], h["flags"]))
sel = (live["time_msc"] >= x0) & (live["time_msc"] < x1)
L = Counter(fp(*x) for x in zip(live["time_msc"][sel], live["bid"][sel], live["ask"][sel], live["flags"][sel]))
miss, extra = H - L, L - H
res = {"sessions": chosen, "window_s": (x1 - x0) / 1000, "history": sum(H.values()), "live": sum(L.values()),
       "missing_in_live": sum(miss.values()), "only_in_live": sum(extra.values()),
       "result": "EXACT" if not miss and not extra else "DIFFERENT"}
print(json.dumps(res))
for k, v in list(miss.items())[:8]:
    print("  missing_in_live", k, "x", v)
for k, v in list(extra.items())[:8]:
    print("  only_in_live", k, "x", v)
if a.json:
    Path(a.json).write_text(json.dumps(res, indent=1))
mt5.shutdown()
