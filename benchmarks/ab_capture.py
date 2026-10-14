"""A/B capture benchmark: Mode A (Python polling copy_ticks_from, the product's MT5TickSource) vs Mode B (read-only EA writing a file).

  python benchmarks/ab_capture.py --minutes 30

Prerequisite (manual, once): attach the compiled EA `XauTickLoggerModeB` (Navigator > Expert Advisors > xau_tmp_compile) to ONE XAUUSD chart of the
MetaQuotes-Demo terminal and allow algorithmic trading for it. The EA contains no trading call (tests/unit/test_modeb_reader.py enforces that for
every .mq5 in the repository). Without the EA's file this script exits with status 3 (NOT TESTED); it never fabricates numbers.

Metrics (both modes see the same terminal, so they are compared on the SAME ticks):
  completeness : ticks seen by A only / B only / both, keyed by (time_msc, bid, ask, flags) with occurrence counting
  latency      : reader wall clock minus (tick time_msc - server_utc_offset). Wall clock and the server stamp are different clocks, so ABSOLUTE values carry
                 the clock skew; the DIFFERENCE between A and B on the same ticks is the meaningful number. Gateway-internal latency is not included here.
Exit codes: 0 report written, 2 refused (no pinned terminal path), 3 NOT TESTED (EA file missing or one side empty), 4 FAILED (identity mismatch or untrusted header:
the two streams are not provably the same server/account/symbol, so NO comparison and no result file is produced).
"""
import argparse
import json
import queue
import sys
import threading
import time
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/gateway",):
    sys.path.insert(0, str(ROOT / p))
from xau_gateway.identity import load_source_config  # noqa: E402
from xau_gateway.modeb_reader import ModeBReader, identity_mismatch  # noqa: E402

COMMON = Path.home() / "AppData" / "Roaming" / "MetaQuotes" / "Terminal" / "Common" / "Files"


def key(msc, bid, ask, flags):
    return (int(msc), round(float(bid), 5), round(float(ask), 5), int(flags))


def occurrence_keys(rows):
    """Occurrence-counted keys so two identical ticks in the same millisecond stay two ticks."""
    c = Counter()
    out = []
    for k in rows:
        c[k] += 1
        out.append((k, c[k]))
    return out


def pct(a, q):
    return None if len(a) == 0 else float(np.percentile(a, q))


def summarize(lat_ms):
    a = np.asarray(lat_ms, dtype=float)
    return {"n": int(len(a)), "p50": pct(a, 50), "p95": pct(a, 95), "p99": pct(a, 99), "max": None if not len(a) else float(a.max())}


def identity_gate(header: dict, expected: dict | None, symbol: str, mode_a_status: dict | None = None) -> str | None:
    """None only when BOTH modes are provably the same pinned server/account/symbol. A missing EA header, a mismatch in server / account_ref / symbol, an
    unpinned expectation, or a Mode A source that did not verify its identity all fail (the benchmark never produces a PASS in those cases)."""
    exp = expected or {}
    if not exp.get("server") or not exp.get("account_ref"):
        return "the expected server/account_ref are not pinned in configs/source.json"
    why = identity_mismatch(header, exp, symbol)
    if why:
        return "Mode B: " + why
    if str(header.get("symbol", "")) != symbol and not str(header.get("symbol", "")).startswith(symbol):
        return f"Mode B symbol {header.get('symbol')} != {symbol}"
    if mode_a_status is not None:
        if not mode_a_status.get("identity_verified"):
            return "Mode A did not verify the terminal identity (state " + str(mode_a_status.get("state")) + ")"
        a_sym = str(mode_a_status.get("symbol") or "")
        if a_sym and a_sym != str(header.get("symbol")):
            return f"Mode A symbol {a_sym} != Mode B symbol {header.get('symbol')}"
    return None


def run(minutes: float, symbol: str, out: Path) -> int:
    cfg = load_source_config()
    if not cfg.get("terminal_path"):
        print("configs/source.json has no terminal_path: refusing (several MT5 terminals exist)")
        return 2
    ref = (cfg.get("expected") or {}).get("account_ref")
    if not ref:
        print("REFUSED: configs/source.json has no expected.account_ref: the identity of the capture cannot be verified")
        return 2
    f = COMMON / f"xau_modeb_{symbol}_{ref}.csv"          # the account_ref in the name keeps terminals that share the COMMON folder apart
    if not f.exists():
        print(f"NOT TESTED: {f} does not exist. Attach the EA XauTickLoggerModeB (v1.1) to an XAUUSD chart first (see the docstring).")
        return 3
    from xau_gateway.mt5_source import MT5TickSource
    src = MT5TickSource(cfg["terminal_path"], symbol, cfg.get("expected"))
    src.start()
    rd = ModeBReader(f, offset=f.stat().st_size)                 # only ticks written from now on: the EA's backlog would be unfair to Mode A
    a_rows, b_rows = [], []
    stop = time.time() + minutes * 60
    t_a = threading.Event()

    def pump_a():
        while time.time() < stop and not t_a.is_set():
            try:
                tk = src.q.get(timeout=0.2)
            except queue.Empty:
                continue
            a_rows.append((time.time_ns(), tk.time_msc, tk.bid, tk.ask, tk.flags))
    th = threading.Thread(target=pump_a, daemon=True)
    th.start()
    while time.time() < stop:
        for t in rd.poll():
            b_rows.append((t.wall_ns, t.time_msc, t.bid, t.ask, t.flags))
        time.sleep(0.002)
    t_a.set()
    th.join(2)
    src.stop_ev.set()
    off = src.status.get("server_utc_offset_s")
    bad = identity_gate(rd.header, cfg.get("expected"), symbol, src.status)
    if bad:
        print(f"FAILED (identity): {bad}. No comparison is made and no result file is written.")
        return 4
    if off is None or not a_rows or not b_rows:
        print(f"NOT TESTED: offset={off} A ticks={len(a_rows)} B ticks={len(b_rows)} (no data from one side)")
        return 3
    mism = None
    ka, kb = occurrence_keys([key(*r[1:]) for r in a_rows]), occurrence_keys([key(*r[1:]) for r in b_rows])
    sa, sb = set(ka), set(kb)
    both = sa & sb
    lat = lambda rows: [(r[0] / 1e6) - (r[1] - off * 1000) for r in rows]
    ma = {k: r for k, r in zip(ka, a_rows)}
    mb = {k: r for k, r in zip(kb, b_rows)}
    d = [(mb[k][0] - ma[k][0]) / 1e6 for k in both]                  # B receipt minus A receipt for the same tick (same wall clock: skew cancels)
    res = {"minutes": minutes, "symbol": symbol, "server_utc_offset_s": off, "identity_mismatch_modeb": mism,
           "ticks": {"A": len(a_rows), "B": len(b_rows), "both": len(both), "only_A": len(sa - sb), "only_B": len(sb - sa)},
           "latency_ms_vs_server_stamp": {"A": summarize(lat(a_rows)), "B": summarize(lat(b_rows))},
           "B_minus_A_receipt_ms_same_tick": summarize(d), "modeb_reader": {"bad_lines": rd.bad_lines, "resets": rd.resets, "sessions": rd.sessions},
           "caveats": ["server stamp and wall clock are different clocks: absolute latency includes skew; compare A to B", "gateway-internal pipeline latency not included",
                       "both modes read the same terminal: terminal-side delays are shared"]}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=30)
    ap.add_argument("--symbol", default="XAUUSD")
    ap.add_argument("--out", default=str(ROOT / "results" / "p2" / "ab_capture.json"))
    a = ap.parse_args()
    sys.exit(run(a.minutes, a.symbol, Path(a.out)))
