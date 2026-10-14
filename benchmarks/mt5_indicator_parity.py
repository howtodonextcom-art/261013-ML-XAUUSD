"""Indicator parity against MetaTrader 5's own iMA/iRSI/iATR/iMACD. Needs the CSV written by mt5/scripts/DumpIndicators.mq5
(drag the script onto an XAUUSD chart once; it is read-only). Without the CSV the result is NOT TESTED, never a pass."""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "intelligence"))
from xau_intel.mt5_parity import compare_csv

common = Path(os.environ.get("APPDATA", "")) / "MetaQuotes" / "Terminal" / "Common" / "Files"
sym = sys.argv[1] if len(sys.argv) > 1 else "XAUUSD"
out, missing = {}, []
for tf in ("M15", "H1", "H4"):
    p = common / f"xau_ind_{sym}_{tf}.csv"
    if not p.exists():
        missing.append(str(p))
        continue
    out[tf] = compare_csv(p)
if missing:
    print("NOT TESTED: MT5 dump files not found:\n  " + "\n  ".join(missing))
    print("ACTION NEEDED: in MetaTrader 5 open an XAUUSD chart, Navigator > Scripts > xau_tmp_compile > DumpIndicators (double-click or drag onto the chart), wait for the alert, then rerun this script.")
    sys.exit(3)
print(json.dumps(out, indent=1))
sys.exit(0 if all(v["status"] == "PASS" for v in out.values()) else 1)
