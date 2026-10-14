import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "intelligence"))
sys.path.insert(0, str(Path(__file__).parent))
from xau_intel.liquidity import liquidity_events  # noqa: E402
from test_intel import _bars_from_closes, walk  # noqa: E402

# up-leg, swing high 14.2 at bar 2 (fractal n=2 known at bar 4), pullback, then the tests append bars after the common prefix
BASE = [10, 12, 14, 12, 10, 11, 12]


def ev(path, **kw):
    t, o, h, l, c = _bars_from_closes(path, wick=0.2)
    return liquidity_events(o, h, l, c, t, "M15", method="fractal", n=2, **kw), (t, o, h, l, c)


def test_sweep_high_is_wick_through_with_close_back_below_the_level():
    path = BASE + [13]                                        # bar 7: high 13.2, below the 14.2 level: nothing
    e, _ = ev(path)
    assert e == []
    t, o, h, l, c = _bars_from_closes(BASE + [13, 14], wick=0.2)
    h = h.copy(); c = c.copy(); h[-1] = 15.0; c[-1] = 14.0     # bar 8: high 15 > 14.2 but close 14 <= 14.2
    e = liquidity_events(o, h, l, c, t, "M15", method="fractal", n=2)
    sw = [x for x in e if x["event"] == "SWEEP_HIGH"]
    assert len(sw) == 1 and sw[0]["bar_idx"] == 8 and sw[0]["level"] == pytest.approx(14.2)
    assert sw[0]["known_at"] == t[8] + 900 and sw[0]["level_known_at"] <= sw[0]["event_time"]


def test_a_close_beyond_the_level_is_a_break_not_a_sweep_and_each_level_is_swept_once():
    e, _ = ev(BASE + [13, 16])                                 # close 16 > 14.2
    assert not any(x["event"].startswith("SWEEP") for x in e)
    t, o, h, l, c = _bars_from_closes(BASE + [13, 14, 14, 14], wick=0.2)
    h = h.copy(); c = c.copy(); h[-3:] = 15.0; c[-3:] = 14.0   # three consecutive wick-throughs of the same level
    e = liquidity_events(o, h, l, c, t, "M15", method="fractal", n=2)
    assert sum(1 for x in e if x["event"] == "SWEEP_HIGH") == 1


def test_sweep_low_mirror():
    path = [14, 12, 10, 12, 14, 13, 12]                        # swing low 9.8 at bar 2
    t, o, h, l, c = _bars_from_closes(path + [11, 10], wick=0.2)
    l = l.copy(); c = c.copy(); l[-1] = 9.0; c[-1] = 10.0
    e = liquidity_events(o, h, l, c, t, "M15", method="fractal", n=2)
    assert [x["bar_idx"] for x in e if x["event"] == "SWEEP_LOW"] == [8]


def test_false_breakout_only_if_the_close_returns_inside_within_the_window():
    e, _ = ev(BASE + [13, 16, 17, 14])                         # break at bar 8 (close 16), back below 14.2 at bar 10 (within 3 bars)
    fb = [x for x in e if x["event"] == "FALSE_BREAKOUT_UP"]
    assert len(fb) == 1 and fb[0]["bar_idx"] == 10 and fb[0]["breakout_bar_idx"] == 8
    e2, _ = ev(BASE + [13, 16, 17, 17, 17, 17, 14])            # returns inside only after 5 bars: a normal break that later failed, not 'false'
    assert not any(x["event"] == "FALSE_BREAKOUT_UP" for x in e2)


def test_false_breakout_down_mirror():
    path = [14, 12, 10, 12, 14, 13, 12, 11, 8, 7, 11]          # swing low 9.8; close 8 < 9.8 at bar 8; close 11 > 9.8 at bar 10
    e, _ = ev(path)
    assert [x["bar_idx"] for x in e if x["event"] == "FALSE_BREAKOUT_DOWN"] == [10]


@pytest.mark.parametrize("method", ["zigzag", "fractal"])
@pytest.mark.parametrize("seed", [1, 2, 3, 4])
def test_liquidity_events_never_repaint_or_use_the_future(method, seed):
    t, o, h, l, c = walk(500, seed=seed, vol=1.5)
    full = liquidity_events(o, h, l, c, t, "M15", method=method)
    key = lambda L: [(e["event"], e["bar_idx"], e["level"]) for e in L]
    for cut in (150, 250, 350, 499):
        part = liquidity_events(o[:cut], h[:cut], l[:cut], c[:cut], t[:cut], "M15", method=method)
        assert key(part) == key([e for e in full if e["bar_idx"] < cut]), (method, seed, cut)
    for e in full:
        assert e["known_at"] >= e["formed_at"] and e["level_known_at"] <= e["event_time"] and e["feature_version"] == "liq-1"
