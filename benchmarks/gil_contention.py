"""GIL contention benchmark: does the heavy intelligence recompute delay the tick hot path? (Level 5.1 P3)

A "hot path" thread repeats what the gateway does per tick (candle engine update + JSON serialisation of the message) at a fixed rate; its SCHEDULING
DELAY (actual wake-up minus planned wake-up) and PROCESSING time are recorded. Meanwhile (a) nothing, (b) `compute_heavy` on the real stored bars, in a
loop, runs in another thread of the same process, (c) the same with a 1 ms interpreter switch interval, (d) `compute_heavy` in a separate PROCESS.
Only the pre-holdout bars are used. Output: results/p3/gil_contention.json. Numbers are for THIS machine, load and Python build; nothing is extrapolated.

  python benchmarks/gil_contention.py --seconds 20 --hz 50
"""
import argparse
import json
import multiprocessing as mp
import statistics
import sys
import threading
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "benchmarks"))
for p in ("services/gateway", "services/intelligence"):
    sys.path.insert(0, str(ROOT / p))


def pct(a, q):
    return float(np.percentile(a, q)) if len(a) else None


def load():
    import p6_backtest as P
    bnd = json.loads((ROOT / "results" / "p6" / "boundaries.json").read_text(encoding="utf-8"))
    full, _ = P.load_bars()
    return P.cut_bars(full, bnd["val_end"]), bnd["val_end"]


def heavy_loop(bars, now_s, stop):
    from xau_gateway.intel_logic import compute_heavy
    n = 0
    while not stop.is_set():
        compute_heavy({tf: bars[tf] for tf in ("M15", "H1", "H4")}, now_s)
        n += 1
    return n


def _proc_main(bars, now_s, stop_ev):
    from xau_gateway.intel_logic import compute_heavy
    while not stop_ev.is_set():
        compute_heavy({tf: bars[tf] for tf in ("M15", "H1", "H4")}, now_s)


def hot_path(seconds, hz):
    from xau_gateway.candles import CandleEngine
    eng = CandleEngine()
    period = 1.0 / hz
    delays, proc = [], []
    t0 = time.perf_counter()
    nxt = t0 + period
    price, msc = 4100.0, 1_791_925_000_000
    rng = np.random.default_rng(1)
    while time.perf_counter() - t0 < seconds:
        now = time.perf_counter()
        if now < nxt:
            time.sleep(max(0.0, nxt - now - 0.0005))
            while time.perf_counter() < nxt:
                pass
        t_wake = time.perf_counter()
        delays.append((t_wake - nxt) * 1000)
        price += float(rng.normal(0, 0.05))
        msc += int(1000 / hz)
        s = time.perf_counter()
        events = eng.on_tick(msc, price, price + 0.4, 6)
        msg = json.dumps({"type": "tick", "tick": {"time_msc": msc, "bid": price, "ask": price + 0.4, "spread": 0.4}, "candles": [{"event": e, **c.to_dict()} for e, c in events]}, allow_nan=False)
        proc.append((time.perf_counter() - s) * 1000)
        nxt += period
        if t_wake - nxt > period:                                   # fell behind by more than one period: do not burst to catch up
            nxt = t_wake + period
    return {"n": len(delays), "scheduling_delay_ms": {"p50": pct(delays, 50), "p95": pct(delays, 95), "p99": pct(delays, 99), "max": float(max(delays))},
            "processing_ms": {"p50": pct(proc, 50), "p95": pct(proc, 95), "p99": pct(proc, 99), "max": float(max(proc))}}


def scenario(name, bars, now_s, seconds, hz, mode):
    stop = threading.Event()
    th = None
    prev = sys.getswitchinterval()
    heavy_runs = {"n": 0}
    pr = None
    mpstop = None
    if mode in ("thread", "thread_si1ms"):
        if mode == "thread_si1ms":
            sys.setswitchinterval(0.001)
        th = threading.Thread(target=lambda: heavy_runs.update(n=heavy_loop(bars, now_s, stop)), daemon=True)
        th.start()
    elif mode == "process":
        ctx = mp.get_context("spawn")
        mpstop = ctx.Event()
        pr = ctx.Process(target=_proc_main, args=(bars, now_s, mpstop), daemon=True)
        pr.start()
    time.sleep(1.0)
    try:
        res = hot_path(seconds, hz)
    finally:
        stop.set()
        if mpstop:
            mpstop.set()
        if th:
            th.join(30)
        if pr:
            pr.join(10)
        sys.setswitchinterval(prev)
    res.update(name=name, mode=mode, heavy_runs=heavy_runs["n"] if th else None)
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=20)
    ap.add_argument("--hz", type=float, default=50)
    ap.add_argument("--out", default=str(ROOT / "results" / "p3" / "gil_contention.json"))
    a = ap.parse_args()
    bars, val_end = load()
    now_s = int(bars["M15"]["time"][-1]) + 900
    t = time.perf_counter()
    from xau_gateway.intel_logic import compute_heavy
    compute_heavy({tf: bars[tf] for tf in ("M15", "H1", "H4")}, now_s)
    one_heavy_s = time.perf_counter() - t
    out = {"seconds": a.seconds, "hz": a.hz, "one_compute_heavy_s": one_heavy_s, "python": sys.version.split()[0], "switch_interval_default_s": sys.getswitchinterval(), "scenarios": []}
    for name, mode in (("baseline: no heavy work", "none"), ("heavy recompute in a thread (production layout)", "thread"),
                       ("heavy recompute in a thread, switch interval 1 ms", "thread_si1ms"), ("heavy recompute in a separate process", "process")):
        r = scenario(name, bars, now_s, a.seconds, a.hz, mode)
        out["scenarios"].append(r)
        print(f"{name:55s} sched p50/p95/p99/max {r['scheduling_delay_ms']['p50']:.2f}/{r['scheduling_delay_ms']['p95']:.2f}/{r['scheduling_delay_ms']['p99']:.2f}/{r['scheduling_delay_ms']['max']:.2f} ms   "
              f"proc p99 {r['processing_ms']['p99']:.2f} ms  n={r['n']} heavy_runs={r['heavy_runs']}", flush=True)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(out, indent=1), encoding="utf-8")
