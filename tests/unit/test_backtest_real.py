"""P6 on the REAL local store, restricted to bars BEFORE the holdout start (the holdout never enters these tests)."""
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in ("services/gateway", "services/intelligence", "benchmarks"):
    sys.path.insert(0, str(ROOT / p))

pytestmark = pytest.mark.skipif(not (ROOT / "data" / "store" / "manifest.sqlite").exists() or not (ROOT / "configs" / "source.json").exists(),
                                reason="local store / source config not present")


@pytest.fixture(scope="module")
def real():
    import p6_backtest as P
    full, _ = P.load_bars()
    bnd = P.boundaries(full["M5"]["time"])
    return P, P.cut_bars(full, bnd["val_end"]), bnd


def test_holdout_bars_are_not_in_memory(real):
    P, bars, bnd = real
    assert int(bars["M5"]["time"][-1]) + 300 <= bnd["val_end"] and int(bars["M15"]["time"][-1]) + 900 <= bnd["val_end"]
    assert int(bars["H4"]["time"][-1]) + 14400 <= bnd["val_end"]


def test_real_data_prefix_invariance(real):
    from xau_intel.backtest.engine import canon, setup_run
    P, bars, _ = real
    full = setup_run(bars)["res"]["events"]
    assert len(full) > 100
    n15 = bars["M15"]["time"]
    for frac in (0.35, 0.6, 0.85):
        cut = int(n15[int(len(n15) * frac)])
        pre = setup_run(P.cut_bars(bars, cut))["res"]["events"]
        assert canon(pre) == canon([e for e in full if e["known_at"] <= cut]), f"look-ahead at {time.strftime('%Y-%m-%d %H:%M', time.gmtime(cut))}"


def test_real_data_replay_is_deterministic(real):
    from xau_intel.backtest import candidates as C
    from xau_intel.backtest.engine import digest
    P, bars, _ = real
    a, _ = C.c4(bars, bars["M5"], "t")
    b, _ = C.c4(bars, bars["M5"], "t")
    assert digest(a) == digest(b)
    assert digest(C.c3(C.c4(bars, bars["M5"], "t")[1], bars["M5"])) == digest(C.c3(C.c4(bars, bars["M5"], "t")[1], bars["M5"]))


def test_spread_units_are_price_units(real):
    P, bars, _ = real
    sp = bars["M5"]["spread"]
    assert 0.02 < float(sp[sp > 0].mean()) < 3.0, "spread must be in USD per ounce (points x 0.01), not raw points"
