"""Per-stage CPU / latency of the analysis pipeline (Level 6.4). Offline, deterministic inputs (tests/fixtures bars, the newest 2000 bars per timeframe = the gateway window).

  .\\.venv\\Scripts\\python.exe benchmarks\\stage_latency.py   -> results/p3/stage_latency.json

Stages: heavy analysis (`compute_heavy`, runs in a worker process in production), decision re-evaluation (`make_decision`, every 2 s in the intel loop), V1 event builder, the ML shadow
(feature build for the window + logistic scoring of one row; the shadow feeds no decision), setup history replay (worker, cached). Wall time is `perf_counter`; CPU time is
`process_time` (this process only). Network, WebSocket and render are measured separately in real Chrome (benchmarks/e2e_latency.mjs). No LLM is called here: its latency is NOT MEASURED.
"""
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/gateway", "services/intelligence"):
    sys.path.insert(0, str(ROOT / p))
from xau_gateway.intel_logic import compute_heavy, make_decision, v1_event_from_decision  # noqa: E402
from xau_gateway.setup_history import replay_events  # noqa: E402
from xau_intel.backtest.engine import GATE, RISK, XAU_SPEC  # noqa: E402

FIX = ROOT / "tests" / "fixtures"
W = 2000


def pct(a, q):
    s = sorted(a)
    return round(s[min(len(s) - 1, int(q / 100 * len(s)))], 3)


def stat(a):
    return {"n": len(a), "p50": pct(a, 50), "p95": pct(a, 95), "p99": pct(a, 99), "max": round(max(a), 3)}


def timed(fn, n):
    wall, cpu = [], []
    for _ in range(n):
        c0, t0 = time.process_time(), time.perf_counter()
        fn()
        wall.append((time.perf_counter() - t0) * 1000)
        cpu.append((time.process_time() - c0) * 1000)
    return {"wall_ms": stat(wall), "cpu_ms": stat(cpu)}


def main() -> int:
    z = np.load(FIX / "xau_v1_scenarios.npz")
    full = {tf: {"time": z[f"{tf}_time"], **{k: z[f"{tf}_{k}"].astype(float) / 100.0 for k in ("open", "high", "low", "close")}} for tf in ("M15", "H1", "H4")}
    bars = {tf: {k: v[-W:] for k, v in b.items()} for tf, b in full.items()}
    now = int(bars["M15"]["time"][-1]) + 900
    out = {"input": {"m15_bars": len(bars["M15"]["time"]), "h1_bars": len(bars["H1"]["time"]), "h4_bars": len(bars["H4"]["time"]), "note": "development+validation fixture bars (historical), same window size as the gateway"}}
    out["heavy_analysis"] = timed(lambda: compute_heavy(bars, now), 25)
    heavy = compute_heavy(bars, now)
    kw = dict(spread=0.2, bid=float(bars["M15"]["close"][-1]), data_age_s=1.0, spec=XAU_SPEC, equity=1e4, free_margin=1e4, risk_policy=RISK, gate_policy=GATE, dataset_version="x", now_server_s=now)
    out["decision_reevaluation"] = timed(lambda: make_decision(heavy, **kw), 400)
    dec = make_decision(heavy, **kw)
    out["v1_event_builder"] = timed(lambda: v1_event_from_decision(dec, bid=1.0, published_at=now, published_wall_ms=1, evaluated_at=now), 2000)
    from xau_intel.ml.features import build_features
    out["ml_shadow_feature_build_window"] = timed(lambda: build_features(bars), 10)
    w = np.random.default_rng(1).normal(size=14)
    x = np.random.default_rng(2).normal(size=(1, 14))
    out["ml_shadow_logistic_score_one_row"] = timed(lambda: 1 / (1 + np.exp(-(x @ w))), 5000)
    out["setup_history_replay_all_stored_bars_fixture"] = timed(lambda: replay_events(full), 3)
    out["not_measured"] = ["LLM explanation (no API call was made: network and provider dependent)", "WebSocket and render (see results/p3/e2e_latency.json, real Chrome)"]
    (ROOT / "results" / "p3").mkdir(parents=True, exist_ok=True)
    (ROOT / "results" / "p3" / "stage_latency.json").write_text(json.dumps(out, indent=1, sort_keys=True), encoding="utf-8")
    print(json.dumps(out, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
