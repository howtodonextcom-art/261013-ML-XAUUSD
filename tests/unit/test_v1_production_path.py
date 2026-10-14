"""V1 production path on deterministic market replays (Level 6.2): bars -> compute_heavy -> make_decision -> v1_event_from_decision -> durable log.

The moments come from tests/fixtures/v1_scenarios.json (chosen by the BACKTEST path, a different code path); these tests re-derive every answer through the PRODUCTION path
and check the event stream rules: one event per episode, no event for WAIT/stale/ineligible, no lot or equity, stable ids, restart-safe dedup."""
import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in ("services/gateway", "services/intelligence"):
    sys.path.insert(0, str(ROOT / p))
from xau_gateway.intel_logic import compute_heavy, load_v1_events, log_v1_events, make_decision, v1_event_from_decision  # noqa: E402
from xau_intel.backtest.engine import GATE, RISK, XAU_SPEC  # noqa: E402

FIX = ROOT / "tests" / "fixtures"
SC = json.loads((FIX / "v1_scenarios.json").read_text())["scenarios"]


@pytest.fixture(scope="module")
def bars():
    z = np.load(FIX / "xau_v1_scenarios.npz")
    return {tf: {"time": z[f"{tf}_time"], **{k: z[f"{tf}_{k}"].astype(float) / 100.0 for k in ("open", "high", "low", "close")}} for tf in ("M15", "H1", "H4")}


def production(bars, name):
    now, spread = SC[name]["now"], SC[name]["spread"]
    heavy = compute_heavy(bars, now)
    t = bars["M15"]["time"]
    j = int(np.searchsorted(t + 900, now, side="right")) - 1                    # the last M15 bar closed at `now`
    bid = float(bars["M15"]["close"][j])
    dec = make_decision(heavy, spread=spread, bid=bid, data_age_s=1.0, spec=XAU_SPEC, equity=1e4, free_margin=1e4, risk_policy=RISK, gate_policy=GATE,
                        dataset_version="fixture", now_server_s=now)
    ev = v1_event_from_decision(dec, bid=bid, published_at=now + 1, published_wall_ms=1_000, evaluated_at=heavy["evaluated_at"])
    return heavy, dec, ev


@pytest.mark.parametrize("name,direction", [("BUY_PUBLISHED", "BUY"), ("SELL_PUBLISHED", "SELL")])
def test_the_production_path_publishes_buy_and_sell_through_every_risk_gate_and_records_exactly_one_event(bars, tmp_path, name, direction):
    heavy, dec, ev = production(bars, name)
    assert dec["action"] == direction and dec["strategy_eligible"] and dec["primary_reason"] == "ENTRY_ELIGIBLE" and dec["risk"]["status"] == "OK"
    assert not dec["reasons"]["gate"] and dec["execution_authorized"] is False
    assert ev and ev["action"] == direction and ev["decision_id"] == f"{dec['setup']['setup_id']}|{direction}" and ev["kind"] == "RESEARCH_DECISION_EVENT"
    for k in ("decision_id", "setup_id", "action", "event_time", "known_at", "evaluated_at", "published_at", "source_timeframe", "price", "strategy_version", "dataset_version", "risk_status", "valid", "plan"):
        assert ev.get(k) is not None, k
    assert ev["plan"]["stop_loss"] < ev["plan"]["entry"] < ev["plan"]["take_profit"] if direction == "BUY" else ev["plan"]["take_profit"] < ev["plan"]["entry"] < ev["plan"]["stop_loss"]
    assert ev["source_timeframe"] == "M15" and ev["published_at"] >= ev["known_at"] and ev["publish_latency_s"] == ev["published_at"] - ev["known_at"]
    text = json.dumps(ev)
    assert "lot" not in ev["plan"] and "equity" not in text and "free_margin" not in text and "risk_budget" not in text              # no account data in the history
    path, seen = tmp_path / "d" / "v1.jsonl", set()
    for _ in range(40):                                                                # the same decision republished on 40 successive refreshes / ticks
        _, d2, e2 = production(bars, name)
        log_v1_events(path, [e2], seen)
    evs, bad = load_v1_events(path)
    assert len(evs) == 1 and bad == 0 and evs[0]["decision_id"] == ev["decision_id"]
    seen2 = set()                                                                      # a gateway restart (empty memory, same file): still one event
    log_v1_events(path, [ev], {e["decision_id"] for e in load_v1_events(path)[0]})
    assert len(load_v1_events(path)[0]) == 1


@pytest.mark.parametrize("name,direction", [("BUY_BLOCKED", "BUY"), ("SELL_BLOCKED", "SELL")])
def test_an_eligible_setup_stopped_by_risk_is_BLOCKED_never_a_buy_sell_event(bars, name, direction):
    heavy, dec, ev = production(bars, name)
    assert dec["action"] == "BLOCKED" and dec["strategy_eligible"] and dec["primary_reason"].startswith(SC[name]["expect_reason"])
    assert dec["risk"]["status"] != "OK" or dec["reasons"]["gate"]
    assert ev and ev["action"] == "BLOCKED" and ev["decision_id"].startswith(f"{dec['setup']['setup_id']}|BLOCKED|")
    assert "BUY" not in ev["decision_id"].split("|")[1:] and "SELL" not in ev["decision_id"].split("|")[1:]
    assert ev["action"] not in ("BUY", "SELL")


@pytest.mark.parametrize("name", ["NO_VALID_IMPULSE_DOWN", "NO_VALID_IMPULSE_UP", "NO_DIRECTION", "IMPULSE_NO_PULLBACK", "CONFLICT", "MISSED", "INVALIDATED", "EXPIRED"])
def test_wait_states_have_the_right_reason_and_never_produce_an_event(bars, name):
    heavy, dec, ev = production(bars, name)
    assert ev is None and dec["action"] == "WAIT" and dec["next_required"]
    exp = SC[name].get("expect_reason")
    if exp:
        assert dec["primary_reason"] == exp
    if name == "IMPULSE_NO_PULLBACK":
        assert dec["primary_reason"] in ("AWAITING_PULLBACK", "NO_VALID_IMPULSE") and (dec["setup"] or dec["primary_reason"] == "NO_VALID_IMPULSE")
    if name in ("MISSED", "INVALIDATED", "EXPIRED"):
        states = [e["state"] for e in heavy["setup_events"]]
        assert SC[name]["expect_event_state"] in states                         # the terminal event is listed, and the setup is no longer active


def test_a_stale_decision_never_records_an_event_and_ids_are_stable_across_evaluations(bars):
    heavy = compute_heavy(bars, SC["BUY_PUBLISHED"]["now"])
    t = bars["M15"]["time"]
    j = int(np.searchsorted(t + 900, SC["BUY_PUBLISHED"]["now"], side="right")) - 1
    kw = dict(spread=SC["BUY_PUBLISHED"]["spread"], bid=float(bars["M15"]["close"][j]), spec=XAU_SPEC, equity=1e4, free_margin=1e4, risk_policy=RISK, gate_policy=GATE,
              dataset_version="fixture", now_server_s=SC["BUY_PUBLISHED"]["now"])
    stale = make_decision(heavy, data_age_s=60.0, **kw)
    assert stale["action"] == "WAIT" and stale["primary_reason"] == "DATA_STALE"
    assert v1_event_from_decision(stale, bid=1.0, published_at=1, published_wall_ms=1, evaluated_at=1) is None
    a = v1_event_from_decision(make_decision(heavy, data_age_s=1.0, **kw), bid=1.0, published_at=10, published_wall_ms=1, evaluated_at=1)
    b = v1_event_from_decision(make_decision(heavy, data_age_s=2.0, **kw), bid=1.0, published_at=99, published_wall_ms=2, evaluated_at=1)
    assert a["decision_id"] == b["decision_id"]                                   # same decision, different tick/refresh: the same id (deduplicated downstream)


def test_prefix_invariance_the_decision_at_a_moment_does_not_depend_on_later_bars(bars):
    now = SC["SELL_PUBLISHED"]["now"]
    h1 = compute_heavy(bars, now)
    future = {tf: {k: (np.concatenate([v[:], v[-50:]]) if False else v) for k, v in b.items()} for tf, b in bars.items()}
    for tf in future:                                                            # corrupt every bar that closes after `now`
        t = future[tf]["time"]
        later = t + {"M15": 900, "H1": 3600, "H4": 14400}[tf] > now
        for k in ("open", "high", "low", "close"):
            future[tf][k] = np.where(later, 9999.0, future[tf][k])
    h2 = compute_heavy(future, now)
    assert h1["status"] == h2["status"] and h1["setup_events"] == h2["setup_events"] and h1["market"] == h2["market"]


def test_a_torn_log_line_and_duplicates_do_not_lose_or_double_events(tmp_path):
    path = tmp_path / "v.jsonl"
    seen = set()
    e1 = {"decision_id": "S1|BUY", "action": "BUY"}
    e2 = {"decision_id": "S2|SELL", "action": "SELL"}
    assert log_v1_events(path, [e1], seen) == 1
    with open(path, "a", encoding="utf-8", newline="") as f:
        f.write('{"decision_id": "TORN", "act')                                   # crash mid-line
    assert log_v1_events(path, [e1, e2], seen) == 1                               # e1 not duplicated, e2 starts on its own line
    evs, bad = load_v1_events(path)
    assert [e["decision_id"] for e in evs] == ["S1|BUY", "S2|SELL"] and bad == 1
