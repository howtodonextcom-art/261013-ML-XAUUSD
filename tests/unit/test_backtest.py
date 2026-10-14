"""P6 replay engine: hand-calculated simulator examples, no-lookahead (prefix invariance), determinism, ablation flag, candidate sanity.
Everything here runs on SYNTHETIC data; the real-data variants live in test_backtest_real.py."""
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in ("services/intelligence",):
    sys.path.insert(0, str(ROOT / p))
from xau_intel.backtest.engine import (COSTS, canon, decisions_from_setup, digest, run_trades, setup_run, sim_trade)  # noqa: E402
from xau_intel.backtest import candidates as C  # noqa: E402
from xau_intel.backtest.stats import day_bootstrap, summarize  # noqa: E402
from xau_intel.setups.machine import SetupPolicy  # noqa: E402

T0 = 1_760_400_000 - (1_760_400_000 % 14400)      # aligned to H4


def m5_flat(n, price=100.0, spread=0.2, t0=T0):
    t = t0 + 300 * np.arange(n)
    z = np.full(n, price)
    return {"time": t, "open": z.copy(), "high": z.copy(), "low": z.copy(), "close": z.copy(), "spread": np.full(n, spread)}


def plan(direction, entry, sl, tp, lot=1.0):
    sg = 1 if direction == "BUY" else -1
    return {"direction": direction, "entry": entry, "stop_loss": sl, "take_profit": tp, "stop_distance": abs(entry - sl), "lot": lot,
            "loss_distance_with_costs": abs(entry - sl) + 0.3}


# ------------------------------------------------------------------ hand-calculated trades (simulator validated independently of the engine)
def test_buy_take_profit_hand_calculation():
    m = m5_flat(400)
    close = int(m["time"][3])                     # decision at the close of bar 2; fill at the open of bar 3 (the bar starting at `close`)
    m["high"][5] = 102.0                          # target touched on bar 5
    o = sim_trade(plan("BUY", 100.0, 99.0, 102.0), close, m, 1.0, (0.1, 0.0))
    # fill = open 100 + spread 0.2 + slippage 0.1 = 100.3 ; exit at the TP level 102.0 on the bid ; pnl 1.7 ; stop distance 1.0
    assert o["fill_price"] == pytest.approx(100.3) and o["outcome"] == "TP_FIRST" and o["exit_price"] == pytest.approx(102.0)
    assert o["r"] == pytest.approx(1.7) and o["fill_idx"] == 3 and o["exit_idx"] == 5 and o["exit_time"] == int(m["time"][5]) + 300


def test_sell_take_profit_hand_calculation():
    m = m5_flat(400)
    close = int(m["time"][3])
    m["low"][4] = 98.0
    o = sim_trade(plan("SELL", 100.0, 101.0, 98.0), close, m, 1.0, (0.1, 0.0))
    # SELL fills at the bid minus slippage = 99.9 ; the target buys back at the ask = 98.0 + 0.2 = 98.2 ; pnl 1.7
    assert o["fill_price"] == pytest.approx(99.9) and o["exit_price"] == pytest.approx(98.2) and o["r"] == pytest.approx(1.7)


def test_buy_stop_loss_and_sell_stop_loss():
    m = m5_flat(400)
    close = int(m["time"][3])
    m["low"][6] = 98.9
    b = sim_trade(plan("BUY", 100.0, 99.0, 102.0), close, m, 1.0, (0.1, 0.0))
    assert b["outcome"] == "SL_FIRST" and b["exit_price"] == pytest.approx(98.9) and b["r"] == pytest.approx(98.9 - 100.3)       # -1.4
    m = m5_flat(400)
    m["high"][6] = 101.0
    s = sim_trade(plan("SELL", 100.0, 101.0, 98.0), close, m, 1.0, (0.1, 0.0))
    assert s["exit_price"] == pytest.approx(101.0 + 0.2 + 0.1) and s["r"] == pytest.approx(-(101.3 - 99.9))                        # -1.4


def test_stop_gap_exits_at_the_open_not_at_the_stop():
    m = m5_flat(400)
    close = int(m["time"][3])
    m["open"][7:] = 97.0
    m["high"][7:] = 97.0
    m["low"][7:] = 97.0
    m["close"][7:] = 97.0
    b = sim_trade(plan("BUY", 100.0, 99.0, 102.0), close, m, 1.0, (0.1, 0.0))
    assert b["exit_reason"] == "STOP_LOSS_GAP" and b["exit_price"] == pytest.approx(96.9) and b["r"] == pytest.approx(96.9 - 100.3)


def test_both_levels_in_one_bar_is_conservative_and_optimistic_is_only_a_bound():
    m = m5_flat(400)
    close = int(m["time"][3])
    m["high"][5], m["low"][5] = 102.5, 98.5
    cons = sim_trade(plan("BUY", 100.0, 99.0, 102.0), close, m, 1.0, (0.1, 0.0))
    opt = sim_trade(plan("BUY", 100.0, 99.0, 102.0), close, m, 1.0, (0.1, 0.0), optimistic=True)
    assert cons["outcome"] == "SL_FIRST_CONSERVATIVE" and cons["r"] < 0 and cons["ambiguous_bars"] == 1
    assert opt["outcome"] == "TP_FIRST_OPTIMISTIC" and opt["r"] == pytest.approx(1.7)


def test_commission_and_timeout():
    m = m5_flat(400)
    close = int(m["time"][3])
    m["close"][3 + 287] = 100.5                                        # the 288th bar after the fill closes at 100.5
    o = sim_trade(plan("BUY", 100.0, 99.0, 102.0), close, m, 1.0, (0.1, 7.0))
    assert o["outcome"] == "TIMEOUT" and o["exit_price"] == pytest.approx(100.5)
    # pnl 100.5 - 100.3 = 0.2 ; commission 7 USD per lot / 100 USD per unit per lot = 0.07 => 0.13
    assert o["pnl_price"] == pytest.approx(0.13) and o["r"] == pytest.approx(0.13)


def test_no_fill_without_a_bar_at_the_close_and_data_ending_early():
    m = m5_flat(400)
    close = int(m["time"][3]) + 100                                    # no bar starts at this time
    assert sim_trade(plan("BUY", 100.0, 99.0, 102.0), close, m, 1.0, (0.1, 0.0))["exit_reason"] == "NO_BAR_AT_FILL"
    short = m5_flat(50)
    o = sim_trade(plan("BUY", 100.0, 99.0, 102.0), int(short["time"][3]), short, 1.0, (0.1, 0.0))
    assert o["r"] is None                                              # data ended before the exit: dropped, never counted


def test_a_fill_is_never_taken_on_the_decision_bar():
    """The bar that ends at the decision close (index 2) contains a spike to the target; it must NOT be used."""
    m = m5_flat(400)
    m["high"][2] = 105.0
    o = sim_trade(plan("BUY", 100.0, 99.0, 102.0), int(m["time"][3]), m, 1.0, (0.1, 0.0))
    assert o["fill_idx"] == 3 and o["outcome"] == "TIMEOUT"


def test_one_position_at_a_time_and_counters():
    m = m5_flat(2000)
    t = int(m["time"][3])
    d = [{"setup_id": "a", "decision_time": t, "atr": 1.0, "direction": "BUY", "plan": plan("BUY", 100.0, 99.0, 102.0), "reason": "x"},
         {"setup_id": "b", "decision_time": t + 600, "atr": 1.0, "direction": "BUY", "plan": plan("BUY", 100.0, 99.0, 102.0), "reason": "x"},
         {"setup_id": "c", "decision_time": t + 300, "atr": 1.0, "direction": "SELL", "plan": None, "reason": "RISK:RR_TOO_LOW"}]
    trades, cnt = run_trades(d, m)
    assert [x["setup_id"] for x in trades] == ["a"] and cnt == {"SKIPPED_POSITION_OPEN": 1, "NOT_TRADED:RISK:RR_TOO_LOW": 1}


# ------------------------------------------------------------------ synthetic multi-timeframe data
def _agg(t, o, h, l, c, k):
    n = len(c) // k
    sl = slice(0, n * k)
    return {"time": t[sl][::k], "open": o[sl].reshape(n, k)[:, 0], "high": h[sl].reshape(n, k).max(1), "low": l[sl].reshape(n, k).min(1), "close": c[sl].reshape(n, k)[:, -1]}


def synth(n5=48 * 400, seed=1):
    rng = np.random.default_rng(seed)
    t = T0 + 300 * np.arange(n5)
    drift = 0.25 * np.sin(2 * np.pi * np.arange(n5) / 6000.0)             # slow waves => trends, pullbacks
    close = 2000 + np.cumsum(drift + rng.normal(0, 2.0, n5))
    open_ = np.concatenate([[2000.0], close[:-1]])
    high = np.maximum(open_, close) + np.abs(rng.normal(0, 1.0, n5))
    low = np.minimum(open_, close) - np.abs(rng.normal(0, 1.0, n5))
    m5 = {"time": t, "open": open_, "high": high, "low": low, "close": close, "spread": np.full(n5, 0.25)}
    bars = {"M5": m5}
    for tf, k in (("M15", 3), ("H1", 12), ("H4", 48)):
        bars[tf] = _agg(t, open_, high, low, close, k)
    return bars


def truncate(bars, cut):
    from xau_intel.structure import TF_SEC
    out = {}
    for tf, b in bars.items():
        m = b["time"] + TF_SEC[tf] <= cut
        out[tf] = {k: v[m] for k, v in b.items()}
    return out


@pytest.fixture(scope="module")
def sy():
    bars = synth()
    sr = setup_run(bars)
    return bars, sr


def test_synthetic_data_produces_setups_and_trades(sy):
    bars, sr = sy
    ev = sr["res"]["events"]
    assert len(ev) > 20 and any(e["state"] == "ENTRY_ELIGIBLE" for e in ev), "the synthetic series must exercise the pipeline"
    (tr, cnt), _ = C.c4(bars, bars["M5"], "synthetic")
    assert len(tr) >= 1
    assert all(t["fill_time"] == t["decision_time"] for t in tr), "fill at the open of the bar that starts at the decision close"


def prefix_ok(bars, full_events):
    n = 0
    for frac in (0.3, 0.5, 0.7, 0.9):
        cut = int(bars["M15"]["time"][int(len(bars["M15"]["time"]) * frac)])
        pre = setup_run(truncate(bars, cut))["res"]["events"]
        want = [e for e in full_events if e["known_at"] <= cut]
        if canon(pre) != canon(want):
            return False, n
        n += len(want)
    return True, n


def test_prefix_invariance_no_lookahead(sy):
    """Events known at a cut are identical whether or not the future bars exist."""
    bars, sr = sy
    ok, n = prefix_ok(bars, sr["res"]["events"])
    assert ok and n > 50


def test_the_lookahead_detector_really_detects_lookahead(sy, monkeypatch):
    """Mutation check: a direction series that peeks 20 higher-timeframe bars ahead must make the prefix test fail."""
    import xau_intel.backtest.engine as eng
    real = eng.direction_series

    def peeking(o, h, l, c, t, tf, k=2.5):
        d = real(o, h, l, c, t, tf, k)
        return np.concatenate([d[20:], np.array(["UNKNOWN"] * 20, dtype=object)])
    monkeypatch.setattr(eng, "direction_series", peeking)
    bars, _ = sy
    full = setup_run(bars)["res"]["events"]
    ok, _ = prefix_ok(bars, full)
    assert not ok, "the prefix-invariance test is blind to look-ahead"


def test_decisions_are_prefix_invariant_too(sy):
    bars, sr = sy
    full = decisions_from_setup(sr, bars["M5"], "s")
    cut = int(bars["M15"]["time"][int(len(bars["M15"]["time"]) * 0.6)])
    pre_bars = truncate(bars, cut)
    pre = decisions_from_setup(setup_run(pre_bars), pre_bars["M5"], "s")
    assert canon(pre) == canon([d for d in full if d["decision_time"] <= cut])


def test_future_corruption_does_not_change_the_past(sy):
    """Wreck every bar after the cut: nothing known at the cut may change."""
    bars, sr = sy
    cut = int(bars["M15"]["time"][int(len(bars["M15"]["time"]) * 0.6)])
    bad = {tf: {k: v.copy() for k, v in b.items()} for tf, b in bars.items()}
    for tf, b in bad.items():
        after = b["time"] >= cut
        for k in ("open", "high", "low", "close"):
            b[k][after] = b[k][after] * 3.0 + 500
    ev_bad = setup_run(bad)["res"]["events"]
    ev = sr["res"]["events"]
    assert canon([e for e in ev_bad if e["known_at"] <= cut]) == canon([e for e in ev if e["known_at"] <= cut])


def test_determinism(sy):
    bars, _ = sy
    a, _ = C.c4(bars, bars["M5"], "synthetic")
    b, _ = C.c4(bars, bars["M5"], "synthetic")
    assert digest(a) == digest(b) and len(canon(a)) > 100


def test_c6_is_identical_to_c4_and_c7_only_buys(sy):
    bars, sr = sy
    (t4, k4), _ = C.c4(bars, bars["M5"], "s", sr)
    (t6, k6), _ = C.c6(bars, bars["M5"], "s", sr)
    assert digest(t4) == digest(t6) and k4 == k6                       # setup-1 never uses liquidity-sweep evidence: C6 == C4
    t7, _ = C.c7(bars, bars["M5"], "s", sr)
    assert all(t["direction"] == "BUY" for t in t7)
    buy_setups = {d["setup_id"] for d in decisions_from_setup(sr, bars["M5"], "s") if d["direction"] == "BUY" and d["plan"] is not None}
    assert {t["setup_id"] for t in t7} <= buy_setups and len(t7) >= 1


def test_c5_ablation_flag_changes_setups_but_default_is_unchanged(sy):
    bars, sr = sy
    assert SetupPolicy().require_zone is True
    ev5 = setup_run(bars, SetupPolicy(require_zone=False))["res"]["events"]
    assert canon(ev5) != canon(sr["res"]["events"]) and len(ev5) > len(sr["res"]["events"])
    zless = [e for e in ev5 if e["zone"] and e["zone"]["touches"] == 1]
    assert zless, "pseudo-zone setups must exist in the ablation"


def test_c3_and_c1_run_and_are_reproducible(sy):
    bars, sr = sy
    t3, cnt3 = C.c3(sr, bars["M5"])
    assert len(t3) >= 1 and all(t["direction"] in ("BUY", "SELL") for t in t3)
    (t4, _), _ = C.c4(bars, bars["M5"], "s", sr)
    lo, hi = int(bars["M5"]["time"][0]), int(bars["M5"]["time"][-1])
    a = C.c1(t4, sr, bars["M5"], lo, hi, 3)
    b = C.c1(t4, sr, bars["M5"], lo, hi, 3)
    assert digest(a) == digest(b) and len(a) == 3


def test_bootstrap_and_summary_are_deterministic_and_sane():
    tr = [{"decision_time": T0 + 86400 * i, "exit_time": T0 + 86400 * i + 600, "r": {"base": r}} for i, r in enumerate([1.0, -1.0, 2.0, -1.0, 1.5, -1.0, 0.5, 1.0])]
    s = summarize(tr)
    assert s["n"] == 8 and s["mean_r"] == pytest.approx(0.375) and s["win_rate"] == pytest.approx(5 / 8) and s["longest_losing_streak"] == 1
    assert s["max_drawdown_r"] == pytest.approx(1.0) and s["profit_factor"] == pytest.approx(6.0 / 3.0)
    b1, b2 = day_bootstrap(tr), day_bootstrap(tr)
    assert b1 == b2 and b1["ci95"][0] < b1["mean_r"] < b1["ci95"][1]
    assert day_bootstrap([]) == {"n": 0}


# ------------------------------------------------------------------ round-6 review additions
def test_sell_stop_is_triggered_by_the_ask_not_the_bid_high():
    m = m5_flat(400, spread=0.4)
    close = int(m["time"][3])
    m["high"][6] = 100.7                              # bid high 100.7 < SL 101.0, but the ask (100.7 + 0.4 = 101.1) reaches the stop
    s = sim_trade(plan("SELL", 100.0, 101.0, 98.0), close, m, 1.0, (0.1, 0.0, 0.0))
    assert s["outcome"] == "SL_FIRST" and s["exit_idx"] == 6
    m["high"][6] = 100.5                              # ask 100.9 < 101.0: no stop
    assert sim_trade(plan("SELL", 100.0, 101.0, 98.0), close, m, 1.0, (0.1, 0.0, 0.0))["outcome"] == "TIMEOUT"


def test_spread_floor_sensitivity_replaces_a_tiny_recorded_spread():
    m = m5_flat(400, spread=0.0)
    close = int(m["time"][3])
    m["high"][5] = 102.0
    a = sim_trade(plan("BUY", 100.0, 99.0, 102.0), close, m, 1.0, (0.1, 0.0, 0.0))
    b = sim_trade(plan("BUY", 100.0, 99.0, 102.0), close, m, 1.0, (0.1, 0.0, 0.4))
    assert a["fill_price"] == pytest.approx(100.1) and b["fill_price"] == pytest.approx(100.5)      # open + spread(floor) + slippage
    assert b["r"] < a["r"] and set(COSTS) >= {"spread0.2", "spread0.4"}


def test_a_trade_absent_at_one_cost_level_does_not_crash_run_trades_or_the_statistics():
    m = m5_flat(2000, spread=0.0)
    t = int(m["time"][3])
    m["high"][8] = 102.0
    d = [{"setup_id": "a", "decision_time": t, "atr": 0.25, "direction": "BUY", "plan": plan("BUY", 100.0, 99.0, 102.0), "reason": "x"}]
    trades, _ = run_trades(d, m)
    assert len(trades) == 1 and trades[0]["r"]["base"] is not None
    assert trades[0]["r"]["slip0.3"] is None                          # fill 100.3 is 0.3 above the planned entry: beyond the chase limit (0.25) only at the higher slippage
    assert summarize(trades, "slip0.3") == {"n": 0} and summarize(trades, "base")["n"] == 1
    assert day_bootstrap(trades, "slip0.3") == {"n": 0}


def test_last_closed_m5_and_spread_at():
    from xau_intel.backtest.engine import last_closed_m5, spread_at
    m = m5_flat(10)
    m["spread"][:] = np.arange(10) * 0.1
    t = m["time"]
    assert last_closed_m5(t, int(t[3])) == 2 and last_closed_m5(t, int(t[3]) + 299) == 2 and last_closed_m5(t, int(t[4])) == 3
    assert spread_at(m, int(t[3])) == pytest.approx(0.2)                  # the bar that CLOSED at the decision time, not the one starting then
    assert spread_at(m, int(t[9]) + 300 + 10_000) is None                 # no fresh spread: unknown, never silently reused


def test_seal_verification():
    sys.path.insert(0, str(ROOT / "benchmarks"))
    import p6_backtest as P
    seal = {"code": {"sha": "abc"}, "config_hash": "c", "devval_dataset_hash": "d"}
    ok = {"dirty": False, "sha": "abc", "config_hash": "c", "devval_dataset_hash": "d"}
    assert P.verify_seal(seal, ok) is None
    for bad in ({"dirty": True}, {"sha": "zzz"}, {"config_hash": "x"}, {"devval_dataset_hash": "y"}):
        assert P.verify_seal(seal, {**ok, **bad}), bad


def test_fixed_boundaries_cannot_drift_when_the_store_grows():
    sys.path.insert(0, str(ROOT / "benchmarks"))
    import p6_backtest as P
    t = np.arange(0, 100_000, 300)
    fixed = {"t0": 0, "t1": 90_000, "dev_end": 54_000, "val_end": 72_000}
    assert P.boundaries(t, fixed) == fixed and P.boundaries(np.arange(0, 200_000, 300), fixed) == fixed
    assert P.boundaries(np.arange(0, 200_000, 300))["val_end"] != fixed["val_end"]          # without the seal the window WOULD move
