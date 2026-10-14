import inspect
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "intelligence"))
sys.path.insert(0, str(Path(__file__).parent))
from xau_intel.decision.decide import STRATEGY_VERSION, GatePolicy, decide, gate_checks  # noqa: E402
from xau_intel.decision.risk import RiskPolicy  # noqa: E402
from xau_intel.setups.machine import current_status, run_setups  # noqa: E402
from test_risk import XAU  # noqa: E402
from test_setups import bar, scenario, market, T0, SEC  # noqa: E402
from xau_intel.structure import Swing  # noqa: E402

RP = RiskPolicy(risk_fraction=0.01, min_net_rr=1.0)


def status_eligible(direction="BUY"):
    extra = [bar(103.7, 104.4, 103.6, 104.2), bar(104.2, 104.3, 103.6, 103.8)]
    o, h, l, c, t, s = scenario(extra)
    if direction == "BUY":
        res = run_setups(o, h, l, c, t, "M15", s, np.full(len(c), "UP", dtype=object))
        return current_status(res, len(c), "UP")
    ms = [Swing("L" if x.kind == "H" else "H", x.idx, x.known_idx, -x.price, x.formed_at, x.known_at, "M15") for x in s]
    res = run_setups(-o, -l, -h, -c, t, "M15", ms, np.full(len(c), "DOWN", dtype=object))
    return current_status(res, len(c), "DOWN")


GOOD = dict(atr=1.0, spread=0.05, spec=XAU, equity=10_000.0, free_margin=9_000.0, data_age_s=1.0, market_open=True, risk_policy=RP)


def test_eligible_setup_with_passing_gates_and_risk_is_a_research_buy_never_an_order():
    d = decide(status_eligible(), price_now_bid=103.8, **GOOD)
    assert d["action"] == "BUY" and d["primary_reason"] == "ENTRY_ELIGIBLE" and d["strategy_eligible"] is True
    assert d["execution_authorized"] is False and d["kind"] == "RESEARCH_DECISION" and d["strategy_version"] == STRATEGY_VERSION
    p = d["plan"]
    assert p["stop_loss"] < p["entry"] < p["take_profit"] and p["lot"] >= 0.01 and d["setup"]["setup_id"].startswith("M15-BUY-")
    assert d["setup"]["invalidation_level"] == p["stop_loss"] and p["take_profit"] == pytest.approx(108.1)       # the impulse high is the target
    assert d["reasons"]["gate"] == []


def test_sell_mirror_decision():
    d = decide(status_eligible("SELL"), price_now_bid=-103.8, **{**GOOD, "atr": 1.0})
    # the mirrored market has negative prices; only direction and ordering are checked here
    assert d["action"] in ("SELL", "BLOCKED") and d["setup"]["direction"] == "SELL"
    if d["action"] == "SELL":
        assert d["plan"]["take_profit"] < d["plan"]["entry"] < d["plan"]["stop_loss"]


def test_eligible_but_spread_wide_is_blocked_with_strategy_eligible_true():
    d = decide(status_eligible(), price_now_bid=103.8, **{**GOOD, "spread": 0.6})
    assert d["action"] == "BLOCKED" and d["strategy_eligible"] is True and d["layer"] == "gate"
    assert d["primary_reason"].startswith("SPREAD_TOO_WIDE") and d["execution_authorized"] is False


def test_not_eligible_and_spread_wide_primary_reason_is_the_strategy_not_the_spread():
    st = {"decision_context": "WAIT", "wait_reason": "AWAITING_CONFIRMATION", "active": {}}
    d = decide(st, **{**GOOD, "spread": 0.6})
    assert d["action"] == "WAIT" and d["primary_reason"] == "AWAITING_CONFIRMATION" and d["layer"] == "strategy"
    assert any(g.startswith("SPREAD_TOO_WIDE") for g in d["reasons"]["gate"])          # still visible, but not the headline
    d2 = decide({"decision_context": "WAIT", "wait_reason": "NO_DIRECTION", "active": {}}, **{**GOOD, "spread": 0.6})
    assert d2["primary_reason"] == "NO_DIRECTION" and d2["layer"] == "market"


def test_stale_data_never_decides_even_with_an_eligible_setup():
    d = decide(status_eligible(), price_now_bid=103.8, **{**GOOD, "data_age_s": 60.0})
    assert d["action"] == "WAIT" and d["primary_reason"] == "DATA_STALE"
    assert decide(status_eligible(), price_now_bid=103.8, **{**GOOD, "data_age_s": None})["primary_reason"] == "DATA_STALE"


def test_market_closed_and_unknown_session_block_an_eligible_setup():
    assert decide(status_eligible(), price_now_bid=103.8, **{**GOOD, "market_open": False})["primary_reason"] == "MARKET_CLOSED"
    d = decide(status_eligible(), price_now_bid=103.8, **{**GOOD, "market_open": None})
    assert d["action"] == "BLOCKED" and d["primary_reason"] == "MARKET_SESSION_UNKNOWN"


def test_missing_risk_inputs_block_and_never_produce_buy():
    for kw in ({"equity": None}, {"free_margin": None}, {"spec": None}):
        d = decide(status_eligible(), price_now_bid=103.8, **{**GOOD, **kw})
        assert d["action"] == "BLOCKED" and d["strategy_eligible"] is True and d["risk"]["status"] == "RISK_NOT_EVALUABLE", kw
        assert d["primary_reason"].startswith("RISK:MISSING")


def test_daily_loss_limit_is_a_configured_gate_never_hard_coded():
    assert decide(status_eligible(), price_now_bid=103.8, **GOOD)["action"] == "BUY"          # not configured: not evaluated
    gp = GatePolicy(daily_loss_limit_fraction=0.035)
    d = decide(status_eligible(), price_now_bid=103.8, daily_loss_used_fraction=0.04, gate_policy=gp, **GOOD)
    assert d["action"] == "BLOCKED" and d["primary_reason"].startswith("DAILY_LOSS_LIMIT_REACHED")
    assert decide(status_eligible(), price_now_bid=103.8, daily_loss_used_fraction=0.01, gate_policy=gp, **GOOD)["action"] == "BUY"
    assert decide(status_eligible(), price_now_bid=103.8, daily_loss_used_fraction=None, gate_policy=gp, **GOOD)["primary_reason"] == "DAILY_LOSS_UNKNOWN"


def test_risk_gate_does_not_hide_an_unformed_setup():
    d = decide({"decision_context": "WAIT", "wait_reason": "PULLBACK_IN_PROGRESS", "active": {}}, **{**GOOD, "equity": None})
    assert d["primary_reason"] == "PULLBACK_IN_PROGRESS" and d["action"] == "WAIT"


def test_signal_conflict_two_active_setups():
    e = {"setup_id": "a", "direction": "BUY", "state": "ENTRY_ELIGIBLE", "evidence": [], "invalidation_level": 1, "entry_level": 2, "next_required_event": "x",
         "known_at": 1, "policy_version": "setup-1", "impulse": {"high_price": 3}}
    st = {"decision_context": "ENTRY_ELIGIBLE", "wait_reason": None, "active": {"BUY": e, "SELL": {**e, "setup_id": "b", "direction": "SELL"}}}
    d = decide(st, **GOOD)
    assert d["action"] == "WAIT" and d["primary_reason"] == "SIGNAL_CONFLICT"


def test_decision_has_no_indicator_input_by_construction():
    params = set(inspect.signature(decide).parameters)
    assert not any(k in params for k in ("rsi", "macd", "ema", "crossover", "indicator"))


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5, 6])
def test_buy_or_sell_only_ever_follow_an_entry_eligible_setup_with_clean_gates_on_random_markets(seed):
    t, o, h, l, c, sws, ctx = market(seed)
    res = run_setups(o, h, l, c, t, "M15", sws, ctx)
    rng = np.random.default_rng(seed)
    n_dec = 0
    for cut in range(100, len(c), 37):
        part = {"events": [e for e in res["events"] if e["bar_idx"] <= cut]}
        st = current_status(part, cut + 1, str(ctx[cut]))
        kw = dict(GOOD, spread=float(rng.choice([0.05, 0.9])), data_age_s=float(rng.choice([1.0, 99.0])), market_open=bool(rng.choice([True, False])),
                  equity=float(rng.choice([10_000.0, 50.0])))
        d = decide(st, price_now_bid=float(c[cut]), **kw)
        n_dec += 1
        assert d["execution_authorized"] is False
        if d["action"] in ("BUY", "SELL"):
            assert st["decision_context"] == "ENTRY_ELIGIBLE" and d["setup"]["state"] == "ENTRY_ELIGIBLE"
            assert d["reasons"]["gate"] == [] and d["risk"]["status"] == "OK" and kw["data_age_s"] < 10 and kw["market_open"]
        if d["action"] == "BLOCKED":
            assert d["strategy_eligible"] is True
        assert d["primary_reason"]
    assert n_dec > 20


def test_gate_checks_unit():
    pol = GatePolicy()
    assert gate_checks(atr=1.0, spread=0.1, data_age_s=1, market_open=True, daily_loss_used_fraction=None, pol=pol) == []
    assert "SPREAD_OR_ATR_UNKNOWN" in gate_checks(atr=None, spread=0.1, data_age_s=1, market_open=True, daily_loss_used_fraction=None, pol=pol)
