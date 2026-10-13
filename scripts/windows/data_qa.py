"""Runs quality report + certified parity on the persisted store and prints JSON. Usage: data_qa.py [store_root]"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "gateway"))
from xau_gateway.storage import Store
from xau_gateway.quality import certified_parity, quality_report
root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[2] / "data" / "store"
s = Store(root)
par = certified_parity(s)
print(json.dumps({"verify": s.verify(), "quality": quality_report(s),
                  "parity": {k: (v if k not in ("excluded",) else {"count": len(v), "by_reason": {r: sum(1 for x in v if x["reason"] == r) for r in {x["reason"] for x in v}}}) for k, v in par.items()}}, indent=1, default=str))
