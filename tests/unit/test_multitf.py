import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "gateway"))
from xau_gateway.multitf import aggregate_m1, warmup_status  # noqa: E402

DAY = 1_700_006_400 // 14400 * 14400  # H4-aligned


def test_aggregate_ohlc_volume_and_buckets():
    t = [DAY, DAY + 60, DAY + 300, DAY + 360]
    r = aggregate_m1(t, [1, 2, 3, 4], [5, 6, 7, 8], [0, 1, 2, 3], [2, 3, 4, 9], [10, 20, 30, 40], "M5")
    assert r["time"].tolist() == [DAY, DAY + 300]
    assert (r["open"].tolist(), r["high"].tolist(), r["low"].tolist(), r["close"].tolist()) == ([1, 3], [6, 8], [0, 2], [3, 9])
    assert r["tick_volume"].tolist() == [30, 70] and r["n_m1"].tolist() == [2, 2]


def test_no_synthetic_bucket_for_missing_minutes():
    t = [DAY, DAY + 3600 * 3]  # 3 hours with no M1 bars
    r = aggregate_m1(t, [1, 2], [1, 2], [1, 2], [1, 2], [1, 1], "H1")
    assert r["time"].tolist() == [DAY, DAY + 3 * 3600]  # buckets in between are NOT created


def test_h4_bucket_alignment_is_server_hours_0_4_8():
    t = [DAY + 3 * 3600 + 59 * 60, DAY + 4 * 3600]
    r = aggregate_m1(t, [1, 2], [1, 2], [1, 2], [1, 2], [1, 1], "H4")
    assert r["time"].tolist() == [DAY, DAY + 14400]
    assert (DAY // 3600) % 4 == 0


def test_partial_bucket_aggregates_existing_bars_only():
    t = [DAY + 20 * 3600 + 59 * 60]  # lone M1 bar at the end of a session
    r = aggregate_m1(t, [5], [6], [4], [5.5], [7], "H1")
    assert r["n_m1"].tolist() == [1] and r["tick_volume"].tolist() == [7]


def test_empty_input():
    r = aggregate_m1([], [], [], [], [], [], "M5")
    assert len(r["time"]) == 0


def test_warmup_not_assumed_from_one_week_of_m1():
    one_week_m1 = 7 * 1320
    h4_from_week = one_week_m1 // 240
    w = warmup_status({"H4": h4_from_week, "M1": one_week_m1})
    assert w["H4"]["indicators"]["EMA200"] == "INSUFFICIENT_HISTORY"
    assert w["M1"]["indicators"]["EMA200"] == "CONVERGED"
    assert warmup_status({"H4": 250})["H4"]["indicators"]["EMA200"] == "MINIMUM_ONLY"
    assert warmup_status({"H4": 3000})["H4"]["indicators"]["EMA200"] == "CONVERGED"
