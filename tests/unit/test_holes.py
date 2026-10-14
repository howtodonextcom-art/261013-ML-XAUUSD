import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "gateway"))
sys.path.insert(0, str(Path(__file__).parent))
from xau_gateway.holes import m1_holes, overlaps  # noqa: E402
from xau_gateway.quality import htf_parity  # noqa: E402
from xau_gateway.storage import BAR_SCHEMA, Store  # noqa: E402

T0 = 1_700_006_400 // 3600 * 3600


def test_holes_need_native_bars_inside_the_gap_regular_breaks_are_not_holes():
    m1 = np.concatenate([T0 + np.arange(0, 3600, 60), T0 + 7200 + np.arange(0, 1800, 60)])   # one hour, a 1 h gap, 30 min
    m5_with = T0 + np.arange(0, 9000, 300)                                                     # native bars cover the gap: a HOLE
    m5_without = np.concatenate([T0 + np.arange(0, 3600, 300), T0 + 7200 + np.arange(0, 1800, 300)])   # no native bars in the gap: a normal break
    h = m1_holes(m1, m5_with)
    assert len(h) == 1 and h[0]["from"] == T0 + 3600 and h[0]["to"] == T0 + 7200 and h[0]["missing_minutes"] == 60 and h[0]["native_m5_bars_inside"] == 12
    assert m1_holes(m1, m5_without) == []
    assert overlaps(T0 + 3000, 900, h) and overlaps(T0 + 3600, 900, h) and not overlaps(T0, 900, h) and not overlaps(T0 + 7200, 900, h)


def mk(store, kind, tf, times, o=1.0, tv=1):
    n = len(times)
    cols = {"source_id": ["mt5_hist_bars"] * n, "server": ["S"] * n, "symbol": ["X"] * n, "tf": [tf] * n, "time": [int(t) for t in times],
            "open": [o] * n, "high": [o + 1] * n, "low": [o - 1] * n, "close": [o] * n, "tick_volume": [tv] * n, "spread": [1] * n, "real_volume": [0] * n,
            "dataset_version": ["t"] * n}
    store.write_chunk(kind, BAR_SCHEMA, cols, source_id="mt5_hist_bars", server="S", symbol="X", chunk=f"{tf}-g0", key_col="time", partition="date=x")


def test_htf_parity_excludes_buckets_over_an_m1_hole_with_a_reason_and_reports_the_hole():
    with tempfile.TemporaryDirectory() as d:
        s = Store(Path(d))
        m1 = np.concatenate([T0 + np.arange(0, 3600, 60), T0 + 7200 + np.arange(0, 3600, 60)])    # M1 missing the second hour
        mk(s, "bars_m1", "M1", m1)
        mk(s, "bars_m5", "M5", T0 + np.arange(0, 10800, 300), tv=5)
        mk(s, "bars_m15", "M15", T0 + np.arange(0, 10800, 900), tv=15)
        r = htf_parity(s, "M15", "X", "S")
        assert r["m1_holes"] and r["excluded"].get("M1_HISTORY_HOLE", 0) >= 4
        assert r["mismatches"] == [] and r["status"] == "PASS" and r["compared"] == 7   # 4 before the hole + 3 after it (the last bucket ends after the last M1 bar)
        r5 = htf_parity(s, "M5", "X", "S")
        assert r5["excluded"].get("M1_HISTORY_HOLE", 0) == 12 and r5["mismatches"] == []


def test_a_real_value_mismatch_outside_any_hole_still_fails():
    with tempfile.TemporaryDirectory() as d:
        s = Store(Path(d))
        mk(s, "bars_m1", "M1", T0 + np.arange(0, 7200, 60), o=1.0)
        mk(s, "bars_m5", "M5", T0 + np.arange(0, 7200, 300), o=1.0, tv=5)
        mk(s, "bars_m15", "M15", T0 + np.arange(0, 7200, 900), o=5.0, tv=15)             # native values differ from the aggregated M1
        r = htf_parity(s, "M15", "X", "S")
        assert r["status"] == "FAIL" and r["mismatches"] and not r["m1_holes"]
