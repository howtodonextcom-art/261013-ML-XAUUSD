"""Review round 3: one consistent level lifecycle between structure_events and liquidity_events."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "intelligence"))
sys.path.insert(0, str(Path(__file__).parent))
from xau_intel.liquidity import liquidity_events  # noqa: E402
from xau_intel.structure import structure_events, zigzag_swings  # noqa: E402
from test_intel import _bars_from_closes, walk  # noqa: E402
from test_liquidity import BASE  # noqa: E402


def test_sweep_does_not_consume_the_level_for_breaks_and_matches_structure_events():
    t, o, h, l, c = _bars_from_closes(BASE + [13, 14, 16, 17], wick=0.2)
    h = h.copy(); c = c.copy(); h[8] = 15.0; c[8] = 14.0        # bar 8 sweeps the 14.2 level, bar 9 then closes beyond it (16)
    liq = liquidity_events(o, h, l, c, t, "M15", method="fractal", n=2)
    core = structure_events(o, h, l, c, t, "M15", n=2, method="fractal")
    assert [x["bar_idx"] for x in liq if x["event"] == "SWEEP_HIGH"] == [8]
    brk = [e for e in core if e["event"] in ("BREAKOUT_UP", "BOS_UP", "CHOCH_UP") and e["level"] == pytest.approx(14.2)]
    assert [e["bar_idx"] for e in brk] == [9]


def test_every_false_breakout_refers_to_a_break_the_core_engine_also_reports():
    for seed in (21, 22, 23):
        t, o, h, l, c = walk(900, seed=seed, vol=1.5)
        core = structure_events(o, h, l, c, t, "M15")
        breaks = {(e["bar_idx"], e["level"]) for e in core}
        fb = [e for e in liquidity_events(o, h, l, c, t, "M15") if e["event"].startswith("FALSE_BREAKOUT")]
        for e in fb:
            assert (e["breakout_bar_idx"], e["level"]) in breaks, (seed, e)


def test_artifact_swings_never_become_liquidity_levels():
    t, o, h, l, c = walk(400, seed=5, vol=1.5)
    art = [s for s in zigzag_swings(h, l, c, t, "M15") if s.window_start_artifact]
    assert art
    for e in liquidity_events(o, h, l, c, t, "M15"):
        assert not any(abs(e["level"] - a.price) < 1e-9 and e["level_known_at"] == a.known_at for a in art)


def test_prefix_equals_full_including_the_full_length():
    t, o, h, l, c = walk(300, seed=8, vol=1.5)
    full = liquidity_events(o, h, l, c, t, "M15")
    n = len(c)
    part = liquidity_events(o[:n], h[:n], l[:n], c[:n], t[:n], "M15")
    assert [(e["event"], e["bar_idx"]) for e in part] == [(e["event"], e["bar_idx"]) for e in full]
