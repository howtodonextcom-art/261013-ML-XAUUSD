"""Indicator parity against MetaTrader 5's own iMA/iRSI/iATR/iMACD.

Needs the CSV + .meta written by mt5/scripts/DumpIndicators.mq5 (drag the read-only script onto an XAUUSD chart once).
Exit codes: 0 PASS, 1 FAIL, 3 NOT TESTED (files missing), 4 REJECTED (dump is not from the pinned, fresh MetaQuotes-Demo feed).
A CSV is never trusted by name: server, account_ref, terminal path, symbol, timeframe, freshness and an OHLC cross-check with the
locally stored MT5 bars must all pass before any comparison is made."""
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/gateway", "services/intelligence"):
    sys.path.insert(0, str(ROOT / p))
from xau_gateway.identity import load_source_config
from xau_gateway.storage import Store
from xau_intel.mt5_parity import compare, read_csv
from xau_intel.provenance import read_meta, verify_provenance

common = Path(os.environ.get("APPDATA", "")) / "MetaQuotes" / "Terminal" / "Common" / "Files"
sym = sys.argv[1] if len(sys.argv) > 1 else "XAUUSD"
cfg = load_source_config()
expected, terminal = cfg.get("expected") or {}, cfg.get("terminal_path", "")
store = Store(ROOT / "data" / "store")
out, missing, rejected = {}, [], {}
for tf in ("M15", "H1", "H4"):
    p = common / f"xau_ind_{sym}_{tf}.csv"
    mp = common / f"xau_ind_{sym}_{tf}.meta"
    if not p.exists() or not mp.exists():
        missing.append(str(p if not p.exists() else mp))
        continue
    d = read_csv(p)
    t = store.read_table(f"bars_{tf.lower()}", source_id="mt5_hist_bars", server=expected.get("server", ""), symbol=sym)
    sb = {k: np.asarray(t[k]) for k in ("time", "open", "high", "low", "close")} if t.num_rows else None
    ok, why = verify_provenance(read_meta(mp), d, expected=expected, terminal_path=terminal, symbol=sym, tf=tf, now_utc=time.time(), store_bars=sb)
    if not ok:
        rejected[tf] = why
        continue
    out[tf] = compare(d)
if rejected:
    print("REJECTED (not from the pinned fresh MetaQuotes-Demo feed; comparison NOT run):")
    print(json.dumps(rejected, indent=1))
    sys.exit(4)
if missing:
    print("NOT TESTED: MT5 dump files not found:\n  " + "\n  ".join(missing))
    print("ACTION NEEDED: in MetaTrader 5 open an XAUUSD chart, Navigator > Scripts > xau_tmp_compile > DumpIndicators "
          "(double-click or drag onto the chart), wait for the alert, then rerun this script.")
    sys.exit(3)
print(json.dumps(out, indent=1))
sys.exit(0 if all(v["status"] == "PASS" for v in out.values()) else 1)
