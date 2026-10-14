"""Runs the full data QA on the persisted store and prints/saves JSON: manifest verification, quality report, certified M1
parity (eligible AND overall coverage), HTF aggregation parity, warm-up status, hourly coverage/seam inventory.
Server/symbol come from configs/source.json (never guessed). Usage: data_qa.py [store_root] [--out file.json]"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "gateway"))
from xau_gateway.coverage import coverage_report
from xau_gateway.identity import load_source_config
from xau_gateway.multitf import warmup_status
from xau_gateway.quality import certified_parity, htf_parity, quality_report
from xau_gateway.storage import Store

import argparse
ap = argparse.ArgumentParser()
ap.add_argument("root", nargs="?", default=str(Path(__file__).resolve().parents[2] / "data" / "store"))
ap.add_argument("--out", default=None)
_a = ap.parse_args()
root, out_path = Path(_a.root), _a.out
cfg = load_source_config()
server, symbol = (cfg.get("expected") or {}).get("server"), cfg.get("symbol_hint", "XAUUSD")
if not server:
    sys.exit("configs/source.json must pin expected.server")
s = Store(root)
par = certified_parity(s, symbol, server)
slim = {k: v for k, v in par.items() if k not in ("excluded", "mismatches")}
slim["excluded_by_reason"] = {r: sum(1 for x in par.get("excluded", []) if x["reason"] == r) for r in {x["reason"] for x in par.get("excluded", [])}}
slim["mismatches"] = par.get("mismatches", [])
bars_n = {}
for tf in ("M1", "M5", "M15", "H1", "H4"):
    bars_n[tf] = s.read_table(f"bars_{tf.lower()}", source_id="mt5_hist_bars", server=server, symbol=symbol).num_rows
cov = coverage_report(s, server, symbol)
from xau_gateway.integrity import duplicate_times
dups = {tf: duplicate_times(s, f"bars_{tf.lower()}", source_id="mt5_hist_bars", server=server, symbol=symbol) for tf in ("M1", "M5", "M15", "H1", "H4")}
res = {"server": server, "symbol": symbol, "verify_problems": s.verify(), "duplicate_bar_times": dups,
       "duplicates_total": sum(v["duplicates"] for v in dups.values()), "quality": quality_report(s, symbol, server),
       "m1_parity": slim,
       "htf_parity": {tf: {k: v for k, v in htf_parity(s, tf, symbol, server).items() if k != "mismatches"} | {"mismatch_count": len(htf_parity(s, tf, symbol, server)["mismatches"])} for tf in ("M5", "M15", "H1", "H4")},
       "bars_by_tf": bars_n, "warmup": warmup_status(bars_n),
       "coverage": {k: v for k, v in cov.items() if k != "rows"}}
text = json.dumps(res, indent=1, default=str)
print(text)
if out_path:
    Path(out_path).write_text(text, encoding="utf-8")
