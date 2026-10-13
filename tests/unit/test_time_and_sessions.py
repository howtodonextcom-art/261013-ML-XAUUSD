import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "gateway"))
from xau_gateway.multitf import aggregate_m1  # noqa: E402
from xau_gateway.timeutil import OffsetEstimator, estimate_server_offset, session_boundary_bars  # noqa: E402

NOW = 1_800_000_000


def test_single_sample_is_never_more_than_provisional():
    for age, off in ((2, 10800), (5, 7200), (9900, 10800)):     # last one: stale tick during the daily break, looks like offset 900
        o, conf, _ = estimate_server_offset(NOW + off - age, NOW)
        assert conf == "PROVISIONAL"
    assert estimate_server_offset(NOW + 10800 - 9900, NOW)[0] == 900   # the wrong value a naive estimator would trust


def test_fresh_arrival_samples_give_high_confidence_and_override_a_bad_provisional():
    e = OffsetEstimator()
    e.set_provisional(NOW + 10800 - 9900, NOW)                  # connected during the break: provisional says 900
    assert e.snapshot()[1] == "PROVISIONAL" and e.snapshot()[0] == 900
    for i in range(6):
        e.add_fresh(NOW + i + 10800 - 0.4, NOW + i)             # ticks first seen live, ~0.4 s old
    off, conf, res, n = e.snapshot()
    assert (off, conf, n) == (10800, "HIGH", 6) and abs(res) < 1


def test_inconsistent_samples_are_LOW_not_HIGH():
    e = OffsetEstimator()
    for k, age in enumerate([0.3, 40, 0.5, 90, 20, 70]):
        e.add_fresh(NOW + 7200 - age, NOW)
    assert e.snapshot()[1] == "LOW"


def test_no_samples_is_unknown():
    assert OffsetEstimator().snapshot() == (None, "UNKNOWN", None, 0)


def test_dst_transition_changes_offset_estimate_but_not_wall_clock_bucketing():
    # server wall-clock epoch has no discontinuity at DST: H4 buckets stay aligned on both sides of the switch
    t = [14400 * 100000 + k * 60 for k in range(0, 600, 7)]
    r = aggregate_m1(t, *[np.ones(len(t))] * 4, np.ones(len(t)), "H4")
    assert all(x % 14400 == 0 for x in r["time"].tolist())
    e1, e2 = OffsetEstimator(), OffsetEstimator()
    for i in range(6):
        e1.add_fresh(NOW + 7200 - 0.3, NOW); e2.add_fresh(NOW + 10800 - 0.3, NOW)
    assert e1.snapshot()[0] == 7200 and e2.snapshot()[0] == 10800


def test_session_boundaries_are_derived_from_real_gaps_not_a_fixed_clock_window():
    day = 1_700_006_400 // 86400 * 86400
    # active 01:00-22:59, break, active 01:00 next day (server hours), like this broker
    t1 = np.arange(day + 3600, day + 23 * 3600, 60)
    t2 = np.arange(day + 86400 + 3600, day + 86400 + 4 * 3600, 60)
    t = np.concatenate([t1, t2])
    b = session_boundary_bars(t, min_gap_s=1800, edge_minutes=5)
    before = set(t[b["before_break"]].tolist()); after = set(t[b["after_break"]].tolist())
    assert max(before) == day + 22 * 3600 + 59 * 60 and len(before) == 5
    assert min(after) == day + 86400 + 3600 and len(after) == 5


def test_no_gaps_means_no_boundary_bars():
    t = np.arange(0, 3600 * 5, 60)
    b = session_boundary_bars(t, min_gap_s=1800, edge_minutes=5)
    assert len(b["before_break"]) == 0 and len(b["after_break"]) == 0
