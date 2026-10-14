import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "intelligence"))
sys.path.insert(0, str(Path(__file__).parent))
from xau_intel.decision.risk import RiskPolicy, plan_trade  # noqa: E402
from xau_intel.decision.shadow import simulate_outcome  # noqa: E402
from test_risk import XAU  # noqa: E402

POL = RiskPolicy(risk_fraction=0.01, min_net_rr=1.0)


def plan(direction="BUY", entry=100.0, sl=95.0, tp=112.0, spread=0.4):
    if direction == "SELL":
        entry, sl, tp = 100.0, 105.0, 88.0
    p = plan_trade(direction, entry, sl, tp, 4.0, spread, XAU, 10_000.0, 9_000.0, POL)
    assert p.status == "OK", p.reasons
    return p.plan


def bars(rows, spread=0.4):
    o, h, l, c = (np.array([r[i] for r in rows], dtype=float) for i in range(4))
    return o, h, l, c, np.full(len(rows), spread)


FLAT = (100.0, 100.2, 99.8, 100.0)


def test_buy_take_profit_first_fills_at_next_open_and_pays_the_spread():
    p = plan()
    o, h, l, c, s = bars([FLAT, (100.0, 101.0, 99.5, 100.5), (100.5, 112.5, 100.4, 112.0)])
    r = simulate_outcome(p, 0, o, h, l, c, s)
    assert r["outcome"] == "TP_FIRST" and r["fill_idx"] == 1 and r["exit_idx"] == 2 and r["exit_reason"] == "TAKE_PROFIT"
    assert r["fill_price"] == pytest.approx(100.0 + 0.4 + 0.2) and r["exit_price"] == pytest.approx(112.0)
    assert r["pnl_price"] == pytest.approx(112.0 - 100.6) and r["r_multiple"] == pytest.approx((112.0 - 100.6) / p["loss_distance_with_costs"])
    assert r["pnl_money"] > 0


def test_buy_stop_loss_first_costs_about_one_r():
    p = plan()
    o, h, l, c, s = bars([FLAT, (100.0, 100.5, 94.0, 94.5)])
    r = simulate_outcome(p, 0, o, h, l, c, s)
    assert r["outcome"] == "SL_FIRST" and r["exit_price"] == pytest.approx(95.0 - 0.2)
    assert r["r_multiple"] == pytest.approx(-(100.6 - 94.8) / p["loss_distance_with_costs"]) and -1.2 < r["r_multiple"] < -0.9


def test_both_levels_in_one_bar_is_inconclusive_conservative_is_a_distinct_label_and_ticks_resolve_it():
    p = plan()
    o, h, l, c, s = bars([FLAT, (100.0, 113.0, 94.0, 100.0)])
    assert simulate_outcome(p, 0, o, h, l, c, s)["outcome"] == "INCONCLUSIVE"
    cons = simulate_outcome(p, 0, o, h, l, c, s, conservative=True)
    assert cons["outcome"] == "SL_FIRST_CONSERVATIVE" and cons["r_multiple"] < 0
    t0 = 1_700_000_000_000
    times = np.array([t0, t0 + 60_000])
    up_first = [(t0 + 60_000 + 1000, 100.0), (t0 + 60_000 + 2000, 112.5), (t0 + 60_000 + 3000, 94.0)]
    down_first = [(t0 + 60_000 + 1000, 94.0), (t0 + 60_000 + 2000, 112.5)]
    assert simulate_outcome(p, 0, o, h, l, c, s, bar_times_ms=times, ticks=up_first)["outcome"] == "TP_FIRST"
    assert simulate_outcome(p, 0, o, h, l, c, s, bar_times_ms=times, ticks=down_first)["outcome"] == "SL_FIRST"


def test_price_gapping_away_before_the_fill_is_no_fill_not_a_win():
    p = plan()
    o, h, l, c, s = bars([FLAT, (103.5, 112.5, 103.0, 112.0)])             # opens 3.5 above the planned entry: beyond the chase limit
    r = simulate_outcome(p, 0, o, h, l, c, s, max_chase=1.0, planned_entry=100.0)
    assert r["outcome"] == "NO_FILL" and r["exit_reason"] == "CHASE_EXCEEDED" and r["pnl_money"] is None and r["r_multiple"] is None


def test_timeout_closes_at_the_bar_close_and_short_data_is_inconclusive_not_a_result():
    p = plan()
    rows = [FLAT] + [(100.0, 101.0, 99.0, 100.5)] * 5
    o, h, l, c, s = bars(rows)
    r = simulate_outcome(p, 0, o, h, l, c, s, timeout_bars=5)
    assert r["outcome"] == "TIMEOUT" and r["exit_idx"] == 5 and r["exit_price"] == pytest.approx(100.5) and r["bars_held"] == 5
    short = simulate_outcome(p, 0, o, h, l, c, s, timeout_bars=50)
    assert short["outcome"] == "INCONCLUSIVE" and short["exit_reason"] == "DATA_ENDED_BEFORE_EXIT" and short["r_multiple"] is None
    assert simulate_outcome(p, 5, o, h, l, c, s)["outcome"] == "NO_DATA"


def test_sell_mirror_gives_the_same_r_multiple_for_a_mirrored_market():
    pb, ps = plan("BUY"), plan("SELL")
    rows_b = [FLAT, (100.0, 101.0, 99.5, 100.5), (100.5, 112.5, 100.4, 112.0)]
    ob, hb, lb, cb, sb = bars(rows_b)
    rb = simulate_outcome(pb, 0, ob, hb, lb, cb, sb)
    C = 200.0
    om, hm, lm, cm = C - ob, C - lb, C - hb, C - cb                              # the same market upside down; a SELL at 100.0 here mirrors the BUY at 100.0
    rs = simulate_outcome(ps | {"direction": "SELL", "stop_loss": C - 95.0 - 0.0, "take_profit": C - 112.0, "entry": C - 100.0}, 0, om, hm, lm, cm, sb)
    assert rb["outcome"] == "TP_FIRST" and rs["outcome"] == "TP_FIRST"
    assert rs["r_multiple"] == pytest.approx(rb["r_multiple"], rel=1e-6) and rs["pnl_price"] == pytest.approx(rb["pnl_price"])
    sell_stop = simulate_outcome(ps | {"direction": "SELL", "stop_loss": C - 95.0, "take_profit": C - 112.0}, 0, *[C - x for x in (bars([FLAT, (100.0, 100.5, 94.0, 94.5)])[0],)], *[C - x for x in (bars([FLAT, (100.0, 100.5, 94.0, 94.5)])[2],)], *[C - x for x in (bars([FLAT, (100.0, 100.5, 94.0, 94.5)])[1],)], *[C - x for x in (bars([FLAT, (100.0, 100.5, 94.0, 94.5)])[3],)], sb[:2])
    buy_stop = simulate_outcome(pb, 0, *bars([FLAT, (100.0, 100.5, 94.0, 94.5)])[:4], sb[:2])
    assert sell_stop["outcome"] == "SL_FIRST" and sell_stop["r_multiple"] == pytest.approx(buy_stop["r_multiple"], rel=1e-6)


def test_result_does_not_depend_on_bars_after_the_exit():
    p = plan()
    rng = np.random.default_rng(5)
    base = [FLAT, (100.0, 101.0, 99.5, 100.5), (100.5, 112.5, 100.4, 112.0)]
    tail1 = [tuple(100 + rng.normal(0, 3, 4)) for _ in range(20)]
    tail2 = [tuple(100 + rng.normal(0, 3, 4)) for _ in range(20)]
    a = simulate_outcome(p, 0, *bars(base + tail1)[:4], np.full(23, 0.4))
    b = simulate_outcome(p, 0, *bars(base + tail2)[:4], np.full(23, 0.4))
    assert a == b


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5, 6])
def test_random_paths_label_and_pnl_are_consistent(seed):
    rng = np.random.default_rng(seed)
    p = plan()
    for _ in range(40):
        c = 100 + np.cumsum(rng.normal(0, 1.2, 80))
        o = np.r_[100.0, c[:-1]]
        h = np.maximum(o, c) + rng.uniform(0, 0.8, 80)
        l = np.minimum(o, c) - rng.uniform(0, 0.8, 80)
        r = simulate_outcome(p, 3, o, h, l, c, np.full(80, 0.4), timeout_bars=40)
        assert r["outcome"] in ("TP_FIRST", "SL_FIRST", "TIMEOUT", "INCONCLUSIVE", "NO_FILL", "NO_DATA")
        if r["outcome"] == "TP_FIRST":
            assert r["exit_price"] == pytest.approx(p["take_profit"]) and r["pnl_money"] > 0 and r["r_multiple"] > 0
        if r["outcome"] == "SL_FIRST":
            assert r["pnl_money"] < 0 and r["r_multiple"] < 0
        if r["outcome"] == "INCONCLUSIVE":
            assert r["pnl_money"] is None
        if r["fill_idx"] is not None:
            assert r["fill_idx"] == 4                                    # always the open of the bar AFTER the decision bar


def test_a_fill_beyond_the_stop_or_the_target_is_no_fill_never_a_win_or_a_loss():
    p = plan()
    o, h, l, c, s = bars([FLAT, (90.0, 91.0, 89.0, 90.5)])                  # next open far below the stop: stop already breached at the fill
    r = simulate_outcome(p, 0, o, h, l, c, s)
    assert r["outcome"] == "NO_FILL" and r["exit_reason"] == "FILL_BEYOND_STOP" and r["pnl_money"] is None
    o, h, l, c, s = bars([FLAT, (113.0, 114.0, 112.5, 113.5)])               # next open already above the target
    r2 = simulate_outcome(p, 0, o, h, l, c, s)
    assert r2["outcome"] == "NO_FILL" and r2["exit_reason"] == "FILL_BEYOND_TARGET"
    ps = plan("SELL")
    o, h, l, c, s = bars([FLAT, (106.0, 107.0, 105.5, 106.5)])               # SELL: open above the stop
    assert simulate_outcome(ps, 0, o, h, l, c, s)["exit_reason"] == "FILL_BEYOND_STOP"
