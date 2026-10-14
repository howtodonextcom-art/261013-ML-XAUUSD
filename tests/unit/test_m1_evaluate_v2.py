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
