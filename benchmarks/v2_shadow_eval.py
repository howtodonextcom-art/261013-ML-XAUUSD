"""Forward evaluation of the V2 shadow log (frozen protocol: docs/research/M1_ENTRY_V2_PREREGISTRATION.md).

  python benchmarks/v2_shadow_eval.py

Reads data/shadow/v2_events.jsonl (events logged live after the registration commit afd688e). Until at least 100 triggers AND 30 days exist it prints
INSUFFICIENT_EVIDENCE and reads NO bar. Afterwards it simulates the registered entries on the stored M1 bars and writes results/v2/forward_eval.json.
It never touches the sealed P6/P7 holdout period for any V2 claim: only events logged after registration are used.
"""
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/gateway", "services/intelligence"):
    sys.path.insert(0, str(ROOT / p))
from xau_intel.m1.evaluate_v2 import REGISTRATION_UTC, evaluate, events_to_utc, gate, read_log  # noqa: E402

LOG = ROOT / "data" / "shadow" / "v2_events.jsonl"


def main() -> int:
    """Evaluation runs entirely on the UTC timeline (amendment A12): events and bars are converted with MEASURED offsets only; what cannot be proven is excluded and counted."""
    events, bad = read_log(LOG.read_text(encoding="utf-8", errors="replace")) if LOG.exists() else ([], 0)
    now_utc = int(time.time())
    g = gate(events, now_utc, REGISTRATION_UTC)               # pure UTC difference; reads no price
    if g is not None:
        g["unreadable_log_lines"] = bad
        print(json.dumps(g, indent=1))
        return 3
    import json as _j
    from xau_gateway import utcstore
    from xau_gateway.identity import load_source_config
    from xau_gateway.storage import Store
    cfg = load_source_config()
    server, symbol = cfg["expected"]["server"], cfg.get("symbol_hint", "XAUUSD")
    st = Store(Path(os.environ.get("XAU_DATA_DIR") or ROOT / "data" / "store"))     # NOTE: writes the derived UTC dataset and a manifest backup here (never the legacy chunks)
    mig = utcstore.migrate(st, server, symbol)               # idempotent, backs up the manifest first
    runs = utcstore.runs_of(utcstore.load_evidence(st, server))
    ev_utc, ev_cnt = events_to_utc(events, lambda ts: utcstore.resolve_offset(ts, runs)[0])
    b = utcstore.read_utc_bars(st, server, symbol)
    point = float(st.get_meta("symbol:XAUUSD:tick_size") or 0.01)
    keep = b["time"] >= REGISTRATION_UTC                       # only bars from the registration instant on
    m1 = {k: v[keep] for k, v in b.items()}
    m1["spread"] = m1["spread"] * point
    sigs = _j.loads(st.get_meta(f"utc_closure_signatures:{server}:{symbol}") or "[]")
    closures = utcstore.closure_windows(m1, sigs)
    res = evaluate(ev_utc, m1, now_utc, REGISTRATION_UTC, now_utc, REGISTRATION_UTC, closures)
    # sensitivity required by amendment A11: without the events written before log_schema 2 (the legacy zone rule, A5)
    res["sensitivity_without_legacy_events"] = evaluate([e for e in ev_utc if e.get("log_schema") == 2], m1, now_utc, REGISTRATION_UTC, now_utc, REGISTRATION_UTC, closures)
    res["utc"] = {"migration": {k: mig[k] for k in ("legacy_rows", "written_rows", "excluded")}, "event_exclusions": ev_cnt, "closure_windows": len(closures), "closure_signatures": len(sigs), "unreadable_log_lines": bad}
    (ROOT / "results" / "v2").mkdir(parents=True, exist_ok=True)
    (ROOT / "results" / "v2" / "forward_eval.json").write_text(json.dumps(res, indent=1, sort_keys=True, default=lambda x: x.item() if hasattr(x, "item") else str(x)), encoding="utf-8")
    print(json.dumps({k: res[k] for k in ("status", "verdict", "trades", "base", "utc") if k in res}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
