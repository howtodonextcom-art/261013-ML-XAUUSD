"""The frozen V2 evaluation: the gate refuses before any bar is read; the simulation follows the registered rules on synthetic bars."""
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in ("services/intelligence",):
    sys.path.insert(0, str(ROOT / p))
from xau_intel.m1 import evaluate_v2 as EV  # noqa: E402

T0 = 1_792_000_000 - (1_792_000_000 % 60)
REG = T0 - 10 * 86400


def ev(i, direction="BUY", kind="M1_REJECTION", stage="M1_TRIGGERED", close=4100.0, low=4096.0, zone=(4092.0, 4096.5), atr5=4.0, v1=None, step=60 * 30):
    bt = T0 + i * step
    e = {"event_id": f"{direction}-{kind}-{bt}", "direction": direction, "stage": stage, "kind": kind, "bar_time": bt, "known_at": bt + 60, "zone": {"low": zone[0], "high": zone[1]},
         "trigger_close": close, "trigger_low": low, "atr5": atr5}
    if v1 is not None:
        e["v1_target"] = v1
    return e


def bars(n=60 * 24 * 12, drift=0.0, noise=0.4, seed=1):
    rng = np.random.default_rng(seed)
    t = T0 + 60 * np.arange(n)
    c = 4100 + np.cumsum(rng.normal(drift, noise, n))
    o = np.concatenate([[4100.0], c[:-1]])
    return {"time": t, "open": o, "high": np.maximum(o, c) + 0.1, "low": np.minimum(o, c) - 0.1, "close": c, "spread": np.full(n, 0.3)}


class Boom(dict):
    def __getitem__(self, k):
        raise AssertionError("a price was read before the evaluation gate opened")


def test_the_gate_refuses_before_any_bar_is_read_when_triggers_or_days_are_missing():
    few = [ev(i) for i in range(99)]
    r = EV.evaluate(few, Boom(), T0 + 60 * 86400, REG)                      # 99 triggers, 70 days: not enough triggers
    assert r["status"] == "INSUFFICIENT_EVIDENCE" and r["triggers"] == 99 and r["performance_claim"] == "NONE" and "verdict" not in r
    many = [ev(i) for i in range(150)]
    r2 = EV.evaluate(many, Boom(), REG + 29 * 86400, REG)                    # 150 triggers, 29 days: not enough time
    assert r2["status"] == "INSUFFICIENT_EVIDENCE" and r2["days_since_registration"] < 30
    assert EV.gate(many, REG + 31 * 86400, REG) is None                       # both satisfied: the gate opens


def test_window_state_changes_and_duplicates_are_not_triggers():
    evs = [ev(1), ev(2, stage="ENTRY_WINDOW", kind="WINDOW_STATE"), ev(3, stage="M1_TRIGGERED", kind="WINDOW_STATE"), ev(1), ev(4, stage="M5_CONFIRMED_AWAITING_M1", kind="M5_CONFIRMED")]
    assert [e["bar_time"] for e in EV.triggers_of(evs)] == [T0 + 1 * 1800]


def test_plan_rules_buy_sell_and_target_source():
    plan, why = EV.plan_for(ev(1, close=4100.0, low=4096.0, zone=(4092.0, 4096.5), atr5=4.0), 0.3)
    assert why == "OK" and plan["stop_loss"] == pytest.approx(4092.0 - 1.0) and plan["take_profit"] == pytest.approx(4100.0 + 2 * 9.0)       # SL = zone.low - 0.25 ATR5, TP = 2R
    p2, w2 = EV.plan_for(ev(1, v1=4125.0), 0.3)
    assert p2["take_profit"] == 4125.0                                                                                                        # the V1 impulse extreme when active
    p3, _ = EV.plan_for(ev(1, v1=4090.0), 0.3)
    assert p3["take_profit"] == pytest.approx(4118.0)                                                                                         # a V1 target on the wrong side is ignored
    s, ws = EV.plan_for(ev(1, "SELL", close=4100.0, low=4104.0, zone=(4103.5, 4108.0)), 0.3)
    assert ws == "OK" and s["stop_loss"] == pytest.approx(4109.0) and s["take_profit"] < s["entry"] < s["stop_loss"]
    tight, wt = EV.plan_for(ev(1, close=4094.0, low=4092.8, zone=(4091.0, 4093.0), atr5=3.0), 0.3)
    assert tight is None and "SL_TOO_CLOSE" in wt                                                                                            # the broker stops level blocks it


def test_the_simulation_enters_after_the_trigger_bar_and_uses_the_registered_exits():
    m1 = bars(drift=0.0)
    # force the price path after bar 100 so the TP of a BUY trigger at bar 100 is reached
    i = 100
    entry = float(m1["close"][i])
    for k in range(i + 1, i + 40):
        m1["open"][k] = m1["close"][k - 1] if k > i + 1 else entry
        m1["close"][k] = entry + (k - i) * 0.9
        m1["high"][k] = max(m1["open"][k], m1["close"][k]) + 0.1
        m1["low"][k] = min(m1["open"][k], m1["close"][k]) - 0.1
    e = ev(0, close=entry, low=entry - 4, zone=(entry - 8.0, entry - 3.5))
    e["bar_time"] = int(m1["time"][i]); e["known_at"] = e["bar_time"] + 60; e["event_id"] = "BUY-X-1"
    trades, cnt = EV.run_trades([e], m1)
    assert len(trades) == 1 and trades[0]["outcome"] in ("TP_FIRST", "TP_FIRST_OPTIMISTIC") and trades[0]["r"]["base"] > 0.5
    assert trades[0]["exit_time"] > e["known_at"]                                                                                             # nothing is decided with a bar at or before the trigger bar
    again, _ = EV.run_trades([e, {**e, "event_id": "BUY-X-2", "bar_time": e["bar_time"] + 120, "known_at": e["bar_time"] + 180}], m1)
    assert len(again) == 1                                                                                                                    # one open position per direction: the second trigger is skipped


def test_full_evaluation_on_synthetic_data_is_deterministic_and_never_a_profitability_claim():
    m1 = bars(n=60 * 24 * 40, seed=5)
    rng = np.random.default_rng(2)
    evs = []
    for k in range(160):
        i = int(rng.integers(500, len(m1["time"]) - 600))
        c = float(m1["close"][i])
        e = ev(0, close=c, low=c - 5, zone=(c - 12, c - 6), atr5=4.0)
        e["bar_time"] = int(m1["time"][i]); e["known_at"] = e["bar_time"] + 60; e["event_id"] = f"BUY-S-{k}"
        evs.append(e)
    now = int(m1["time"][-1]) + 60
    reg = int(m1["time"][0]) - 1
    a = EV.evaluate(evs, m1, now, reg)
    b = EV.evaluate(evs, m1, now, reg)
    assert a == b and a["status"] == "EVALUATED" and a["verdict"] in ("SHOWS_EVIDENCE", "NO_EVIDENCE_OF_EDGE", "INSUFFICIENT_EVIDENCE")
    assert "profitab" not in a["note"].lower().replace("never a profitability claim", "")
    assert a["b2_random"]["seeds"] > 0 and set(a["costs"]) == set(EV.COSTS)
    assert a["verdict"] != "SHOWS_EVIDENCE" or a["base"]["mean_r"] > 0                                                                       # on a driftless random walk it must not find an edge


def test_week_concentration_follows_the_frozen_wording_share_of_total_r():
    m1 = bars(n=60 * 24 * 40, seed=5)
    evs = []
    for k in range(160):
        e = ev(0)
        i = 500 + k * 200
        e["bar_time"] = int(m1["time"][i]); e["known_at"] = e["bar_time"] + 60; e["event_id"] = f"BUY-W-{k}"
        c = float(m1["close"][i]); e["trigger_close"], e["trigger_low"], e["zone"] = c, c - 5, {"low": c - 12, "high": c - 6}
        evs.append(e)
    res = EV.evaluate(evs, m1, int(m1["time"][-1]) + 60, int(m1["time"][0]) - 1)
    share = res.get("max_week_share")
    assert share is None or share > 0                                                    # None when total R <= 0 (cannot satisfy the 40% rule), else max positive week / total R
    if share is None:
        assert res["verdict"] != "SHOWS_EVIDENCE"


# ---------------- Level 5.4 WP-A1: gap-safe evaluation (amendment A8)
def _flat(n, price=4100.0):
    t = T0 + 60 * np.arange(n)
    return {"time": t, "open": np.full(n, price), "high": np.full(n, price + 0.2), "low": np.full(n, price - 0.2), "close": np.full(n, price), "spread": np.full(n, 0.3)}


def _drop(m1, idx):
    keep = np.ones(len(m1["time"]), dtype=bool)
    keep[idx] = False
    return {k: v[keep] for k, v in m1.items()}


def _trigger_at(m1, i, direction="BUY"):
    c = float(m1["close"][i])
    e = ev(0, direction=direction, close=c, low=c - 4 if direction == "BUY" else c + 4,
           zone=(c - 8.0, c - 3.5) if direction == "BUY" else (c + 3.5, c + 8.0))
    e["bar_time"] = int(m1["time"][i]); e["known_at"] = e["bar_time"] + 60; e["event_id"] = f"{direction}-G-{i}"
    return e


@pytest.mark.parametrize("direction", ["BUY", "SELL"])
def test_a_missing_entry_bar_means_no_fill_and_the_next_array_row_is_never_used_as_the_next_minute(direction):
    m1 = _drop(_flat(700), [101])                                       # the M1 bar right after the trigger bar (index 100) does not exist
    e = _trigger_at(m1, 100, direction)
    assert int(m1["time"][101]) == int(m1["time"][100]) + 120           # array row 101 is TWO minutes later: it must not be treated as the entry bar
    trades, cnt = EV.run_trades([e], m1)
    assert trades == [] and cnt.get("NOT_COUNTED:ENTRY_BAR_MISSING") == 1


def test_the_timeout_is_288_minutes_of_timeline_not_288_available_bars():
    m1 = _flat(900)
    keep = np.ones(900, dtype=bool)
    keep[300:420] = False                                               # a 120-minute market closure inside the position window (longer than the genuine-gap limit)
    m1 = {k: v[keep] for k, v in m1.items()}
    view, tb, why = EV.window_view(m1, np.asarray(m1["time"]), int(T0 + 60 * 200))
    assert why == "OK" and int(view["time"][-1]) < int(T0 + 60 * 200) + 60 + 288 * 60      # never reaches past 288 minutes of timeline
    assert len(view["time"]) < 289 and tb == len(view["time"]) - 1                           # closure bars do not extend the position; data covers the window so it times out cleanly
    trades, cnt = EV.run_trades([_trigger_at(m1, 200)], m1)
    assert len(trades) == 1 and trades[0]["outcome"] == "TIMEOUT"


def test_a_hole_inside_the_window_is_missing_data_and_the_trade_is_not_counted():
    m1 = _drop(_flat(900), [210, 211, 212])                             # 3 genuinely missing bars while the position is open (price path unknown)
    trades, cnt = EV.run_trades([_trigger_at(m1, 200)], m1)
    assert trades == [] and cnt.get("NOT_COUNTED:MISSING_DATA_IN_WINDOW") == 1


def test_a_closure_gap_stop_is_filled_at_the_open_and_a_hole_does_not_select_trades_by_outcome():
    g = _flat(900)
    g = {k: np.concatenate([v[:210], v[330:]]) for k, v in g.items()}   # closure of exactly 120 minutes after bar 209
    g["open"][210:] = 4080.0; g["high"][210:] = 4080.2; g["low"][210:] = 4079.8; g["close"][210:] = 4080.0   # reopens far below the BUY stop
    tr2, _ = EV.run_trades([_trigger_at(g, 200)], g)
    assert len(tr2) == 1 and tr2[0]["outcome"] == "SL_FIRST" and tr2[0]["r"]["base"] < -1.0     # filled at the gap open: worse than -1R
    # review round 11, H1: the same 8-bar hole 60 minutes after entry must exclude the trade WHETHER IT TIMES OUT OR HITS TP EARLY
    slow = _drop(_flat(900), list(range(260, 268)))
    fast = _flat(900)
    fast["high"][205] = 4130.0                                          # TP is reached at bar 205, long before the hole
    fast = _drop(fast, list(range(260, 268)))
    for m in (slow, fast):
        trades, cnt = EV.run_trades([_trigger_at(m, 200)], m)
        assert trades == [] and cnt.get("NOT_COUNTED:MISSING_DATA_IN_WINDOW") == 1


def test_a_40_bar_feed_outage_is_missing_data_not_a_market_closure():
    m1 = _drop(_flat(900), list(range(300, 340)))
    trades, cnt = EV.run_trades([_trigger_at(m1, 200)], m1)
    assert trades == [] and cnt.get("NOT_COUNTED:MISSING_DATA_IN_WINDOW") == 1


def test_a_trade_that_is_uncountable_under_one_cost_scenario_is_out_of_all_scenarios(monkeypatch):
    m1 = _flat(900)
    real = EV._sim
    def flaky(plan, i, view, cost, optimistic=False, timeout_bars=EV.TIMEOUT_M1):
        o, r = real(plan, i, view, cost, optimistic, timeout_bars)
        if cost == EV.COSTS["slip0.3"]:
            return {**o, "outcome": "NO_FILL"}, None                     # only the +0.3 slippage scenario cannot fill
        return o, r
    monkeypatch.setattr(EV, "_sim", flaky)
    trades, cnt = EV.run_trades([_trigger_at(m1, 200)], m1)
    assert trades == [] and cnt.get("NOT_COUNTED:COST_SCENARIO_slip0.3") == 1            # not silently kept in the base sample only
    monkeypatch.setattr(EV, "_sim", real)
    trades, _ = EV.run_trades([_trigger_at(m1, 200)], m1)
    assert len(trades) == 1 and set(trades[0]["r"]) == set(EV.COSTS) and all(v is not None for v in trades[0]["r"].values())


def test_quarters_are_quarters_of_the_forward_period_not_of_the_trade_span():
    m1 = bars(n=60 * 24 * 40, seed=5)
    rng = np.random.default_rng(7)
    evs = []
    for k in range(160):
        i = int(rng.integers(500, 60 * 24 * 10))                         # all trades in the first quarter of the 40-day period
        c = float(m1["close"][i])
        e = ev(0, close=c, low=c - 5, zone=(c - 12, c - 6), atr5=4.0)
        e["bar_time"] = int(m1["time"][i]); e["known_at"] = e["bar_time"] + 60; e["event_id"] = f"BUY-Q-{k}"
        evs.append(e)
    res = EV.evaluate(evs, m1, int(m1["time"][-1]) + 60, int(m1["time"][0]) - 1)
    q = res["quarters_mean_r"]
    assert len(q) == 4 and q[1] is None and q[2] is None and q[3] is None and q[0] is not None   # a trade-span split would have filled all four
def test_data_that_ends_before_the_window_closes_is_inconclusive_not_a_timeout_win_or_loss():
    m1 = _flat(250)                                                     # only 49 minutes after the trigger bar: the 288-minute window outruns the data
    trades, cnt = EV.run_trades([_trigger_at(m1, 200)], m1)
    assert trades == [] and cnt.get("NOT_COUNTED:WINDOW_NOT_COMPLETE") == 1


# ---------------- Level 5.4 WP-A2: UTC / DST handling (amendment A9)
def test_the_gate_is_a_pure_utc_difference_and_survives_a_dst_switch_in_the_forward_period():
    reg_utc = 1_791_960_048
    now_utc = reg_utc + 31 * 86400 + 5                                                       # 31 days later (UTC)
    summer = [{**ev(i), "server_utc_offset_s": 10800} for i in range(100)]
    winter = [{**ev(100 + i), "server_utc_offset_s": 7200} for i in range(20)]               # the server moved to UTC+2 inside the period
    evs = summer + winter
    c = EV.clock(evs, now_utc)
    assert c["offset_at_registration_s"] == 10800 and c["offset_now_s"] == 7200
    assert c["now_server"] - c["reg_server"] == (now_utc - reg_utc) - 3600                   # server-time difference is one hour shorter: it must NOT be used for the gate
    assert EV.gate(evs, c["now_utc"], c["reg_utc"]) is None                                   # UTC: 31.0 days, 120 triggers -> opens
    edge = EV.clock(evs, reg_utc + 30 * 86400 + 1800)                                        # 30 days + 30 min in UTC
    assert EV.gate(evs, edge["now_utc"], edge["reg_utc"]) is None                             # the gate opens (UTC) ...
    assert EV.gate(evs, edge["now_server"], edge["reg_server"])["days_since_registration"] < 30    # ... a server-time difference would wrongly stay closed after a spring/fall switch
    just_short = EV.clock(evs, reg_utc + 30 * 86400 - 1)
    assert EV.gate(evs, just_short["now_utc"], just_short["reg_utc"])["status"] == "INSUFFICIENT_EVIDENCE"        # one second short of 30 days stays closed


def test_legacy_records_without_an_offset_assume_the_offset_measured_at_registration():
    c = EV.clock([ev(1)], 1_791_960_048 + 86400)
    assert c["offset_at_registration_s"] == 10800 and c["offset_now_s"] == 10800 and c["now_server"] == 1_791_960_048 + 86400 + 10800


def test_duplicate_or_backward_bar_times_refuse_the_evaluation():
    m1 = bars(n=500)
    m1["time"] = m1["time"].copy(); m1["time"][300:] -= 3600                                  # a fall-back hour repeats server times
    evs = [ev(i) for i in range(120)]
    r = EV.evaluate(evs, m1, REG + 40 * 86400, REG, REG + 40 * 86400, REG)
    assert r["status"] == "REFUSED_NON_MONOTONIC_BAR_TIMES" and r["performance_claim"] == "NONE"
