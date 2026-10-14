"""V2 shadow integration: the public view, the forward-only log, stale stripping, V1 independence, the worker-process path."""
import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in ("services/gateway", "services/intelligence", "tests/unit"):
    sys.path.insert(0, str(ROOT / p))
from xau_gateway.intel_logic import build_v2_view, log_new_v2_events, make_decision  # noqa: E402
from xau_intel.decision.decide import GatePolicy  # noqa: E402
from xau_intel.decision.risk import RiskPolicy  # noqa: E402
from test_intel_logic import eligible_heavy  # noqa: E402
from test_risk import XAU  # noqa: E402
import test_m1_entry_v2 as T  # noqa: E402

RP = RiskPolicy(risk_fraction=0.01, min_net_rr=1.0)
GP = GatePolicy()


def v2_state(stage, direction="BUY", close=4100.0, extreme=4096.0, zone=(4092.0, 4096.5), atr5=4.0):
    st = {"direction": direction, "stage": stage, "zone": {"low": min(zone), "high": max(zone)}, "next_required": "x"}        # the state carries REAL prices for both directions
    if stage in ("M1_TRIGGERED", "ENTRY_WINDOW"):
        st["trigger"] = {"kind": "M1_REJECTION", "flags": ["M1_REJECTION"], "bar_close": close, "bar_extreme": extreme, "known_at": 1, "window_ends_at": 99, "invalidation": 0, "atr5": atr5}
    return st


def v2(stage, direction="BUY", **kw):
    return {"version": "m1v2-1", "label": "SHADOW: x", "now": 1, "context": {"direction": "UP"}, "primary": direction, "directions": {direction: v2_state(stage, direction, **kw)},
            "events": [{"event_id": f"e{i}", "known_at": i} for i in range(20)], "funnel": {"M1_REJECTION": 1}, "atr": {"M1": 0.4}}


def view(r, spread=0.3, v1=None):
    return build_v2_view(r, partial=None, spread=spread, v1_active=v1, risk_policy=RP, gate_policy=GP)


def test_no_plan_before_a_closed_trigger_exists_and_never_a_buy_sell_action():
    for stage in ("NO_CONTEXT", "NO_ZONE", "WATCHING_ZONE", "M5_CONFIRMED_AWAITING_M1"):
        r = v2(stage)
        r["primary"] = "BUY"
        v = view(r)
        assert v["plan"] is None and v["entry_check"] is None and "action" not in v and v["execution_authorized"] is False and v["kind"] == "SHADOW_OBSERVATION"
    assert len(view(v2("WATCHING_ZONE"))["events_recent"]) == 8


def test_a_triggered_setup_gets_a_reference_account_plan_without_a_lot_and_the_entry_check_reflects_gates():
    v = view(v2("ENTRY_WINDOW"))
    assert v["plan"] and "lot" not in v["plan"] and v["plan"]["sizing"] == "REFERENCE_ACCOUNT" and v["plan"]["stop_loss"] < v["plan"]["entry"] < v["plan"]["take_profit"]
    assert v["plan"]["target_source"] == "2R_FROM_STOP" and v["entry_check"]["stage"] == "ENTRY_WINDOW" and v["entry_check"]["research_entry_ready"] in (True, False)
    wide = view(v2("ENTRY_WINDOW"), spread=5.0)                                          # a wide spread blocks the plan: not ready, and it says why
    assert wide["plan"] is None and wide["entry_check"]["research_entry_ready"] is False and wide["entry_check"]["plan_status"].startswith("GATE")
    triggered_only = view(v2("M1_TRIGGERED"))
    assert triggered_only["entry_check"]["research_entry_ready"] is False                  # the price is outside the entry band: no readiness


def test_a_tight_m1_stop_is_blocked_by_the_broker_stops_level_and_says_so():
    """Product finding: MetaQuotes-Demo XAUUSD has a 6.00 USD stops level, so an M1-scale stop of about 3 USD can never be placed: the plan is BLOCKED, not shown as an opportunity."""
    tight = view(v2("ENTRY_WINDOW", close=4094.0, extreme=4092.8, zone=(4091.0, 4093.0), atr5=3.0))
    assert tight["plan"] is None and tight["entry_check"]["research_entry_ready"] is False and "SL_TOO_CLOSE" in tight["entry_check"]["plan_status"]


def test_sell_levels_are_mirrored_and_the_v1_impulse_target_is_used_when_it_is_on_the_right_side():
    s = view(v2("ENTRY_WINDOW", "SELL", close=4100.0, extreme=4104.0, zone=(4103.5, 4108.0)))
    assert s["plan"]["take_profit"] < s["plan"]["entry"] < s["plan"]["stop_loss"]
    v1 = {"BUY": {"impulse": {"high_price": 4112.0}}}
    b = view(v2("ENTRY_WINDOW"), v1=v1)
    assert b["plan"] and b["plan"]["take_profit"] == 4112.0 and b["plan"]["target_source"] == "V1_IMPULSE_EXTREME"
    wrong_side = view(v2("ENTRY_WINDOW"), v1={"BUY": {"impulse": {"high_price": 4090.0}}})
    assert wrong_side["plan"]["target_source"] == "2R_FROM_STOP"


def test_the_v2_view_never_changes_the_v1_decision():
    h = eligible_heavy()
    kw = dict(spread=0.4, bid=100.0, data_age_s=1.0, spec=XAU, equity=1e4, free_margin=9e3, risk_policy=RP, gate_policy=GP)
    before = json.dumps(make_decision(h, **kw), sort_keys=True, default=str)
    h2 = copy.deepcopy(h)
    view(v2("ENTRY_WINDOW"), v1=h2["status"]["active"])
    assert json.dumps(make_decision(h2, **kw), sort_keys=True, default=str) == before
    assert json.dumps(h2["status"], sort_keys=True, default=str) == json.dumps(h["status"], sort_keys=True, default=str)       # the V1 status passed in was not mutated


def test_the_forward_log_is_append_only_deduplicated_and_never_contains_history(tmp_path):
    path = tmp_path / "shadow" / "v2_events.jsonl"
    ev = [{"event_id": f"E{i}", "version": "m1v2-1", "direction": "BUY", "stage": "M1_TRIGGERED", "kind": "M1_REJECTION", "bar_time": i, "known_at": 1000 + i, "zone": None, "reasons": [],
           "atr5": 1.5} for i in range(10)]
    seen = set()
    assert log_new_v2_events(path, ev, seen, None) == 0 and not path.exists()           # unknown registration offset: nothing is written
    assert log_new_v2_events(path, ev, seen, 1005) == 5                                  # events 5..9 only: 0..4 are history
    assert log_new_v2_events(path, ev, seen, 1005) == 0                                  # deduplicated on the next refresh
    more = ev + [{**ev[0], "event_id": "E10", "known_at": 1010}]
    assert log_new_v2_events(path, more, seen, 1005) == 1
    lines = path.read_text().splitlines()
    assert len(lines) == 6 and all(json.loads(x)["known_at"] >= 1005 for x in lines)
    assert all("equity" not in x and "margin" not in x and "lot" not in x for x in lines)   # market data and decision-time evidence only


def test_a_stale_served_payload_carries_no_shadow_section():
    import time
    from xau_gateway import app as appmod
    appmod.INTEL.update(pub=({"type": "intel", "decision": {"action": "BUY"}, "overlays": {}, "m1_shadow": {"primary": "BUY"}, "seq": 3}, time.monotonic() - 100))
    assert appmod.served_intel()["m1_shadow"] is None
    appmod.INTEL.update(pub=None)


def test_v2_step_runs_on_the_real_candle_engine_data_and_is_contained(monkeypatch):
    """The gateway step on synthetic closed M1..H4 bars in the real engine structures: returns a SHADOW view, never raises into V1, writes no log without a known offset."""
    from xau_gateway import app as appmod
    from xau_gateway.candles import Candle
    mk = T.synth_market(n1=60 * 24 * 6)
    appmod.S.engine.closed = {tf: [] for tf in ("M1", "M5", "M15", "H1", "H4")}
    appmod.S.engine.history = {tf: [Candle(tf, int(t), float(o), float(h), float(l), float(c), 1, state="CLOSED", source="MT5_HISTORY", completeness="HISTORICAL")
                                    for t, o, h, l, c in zip(b["time"], b["open"], b["high"], b["low"], b["close"])] for tf, b in mk.items()}
    appmod.S.engine.open = {}
    appmod.V2.update(result=None, m1_t=None, seen=set(), log_from=None, logged=0)
    monkeypatch.setattr(appmod, "SOURCE", None)
    now = int(mk["M1"]["time"][-1]) + 60
    heavy = eligible_heavy()
    out = appmod.v2_step({"spread": 0.3}, now, heavy, 0.3, RP, GP)
    assert out and out["kind"] == "SHADOW_OBSERVATION" and out["version"] == "m1v2-1" and appmod.V2["logged"] == 0
    again = appmod.v2_step({"spread": 0.3}, now, heavy, 0.3, RP, GP)
    assert again["events_recent"] == out["events_recent"]                              # cached per closed M1 bar, deterministic
    appmod.S.engine.history = {}


@pytest.mark.heavy_pool
def test_the_v2_computation_in_the_worker_process_equals_the_in_process_result(monkeypatch):
    import os
    from xau_gateway import app as appmod
    from xau_intel.backtest.engine import canon
    from xau_intel.m1.entry_v2 import run_v2
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join([str(ROOT / "services/gateway"), str(ROOT / "services/intelligence")]))
    monkeypatch.delenv("XAU_HEAVY_INPROC", raising=False)
    appmod._HEAVY["pool"] = None
    try:
        mk = T.synth_market(n1=60 * 24 * 4)
        now = int(mk["M1"]["time"][-1]) + 60
        assert canon(appmod.run_in_worker(run_v2, mk, now)) == canon(run_v2(mk, now))
    finally:
        pool = appmod._HEAVY["pool"]
        if pool is not None:
            appmod._discard_pool()


# ---------------- review round 9 fixes
def test_an_elapsed_entry_window_shows_no_plan_even_if_no_new_closed_bar_arrived():
    r = v2("ENTRY_WINDOW")                                                              # window_ends_at = 99 in the fixture
    live = build_v2_view(r, partial=None, spread=0.3, v1_active=None, risk_policy=RP, gate_policy=GP, now_server=50)
    assert live["plan"] is not None
    late = build_v2_view(r, partial=None, spread=0.3, v1_active=None, risk_policy=RP, gate_policy=GP, now_server=99)
    assert late["plan"] is None and late["entry_check"]["research_entry_ready"] is False and late["entry_check"]["stage"] == "WINDOW_EXPIRED"


def test_the_forward_log_records_the_v1_target_active_at_the_trigger_for_the_frozen_tp_rule(tmp_path):
    path = tmp_path / "v.jsonl"
    trig = {"event_id": "T1", "version": "m1v2-1", "direction": "BUY", "stage": "M1_TRIGGERED", "kind": "M1_REJECTION", "bar_time": 1, "known_at": 2000, "zone": None, "reasons": [], "atr5": 2.0}
    other = {**trig, "event_id": "W1", "kind": "WINDOW_STATE"}
    log_new_v2_events(path, [trig, other], set(), 1000, {"BUY": {"impulse": {"high_price": 4123.5}}})
    recs = {json.loads(x)["event_id"]: json.loads(x) for x in path.read_text().splitlines()}
    assert recs["T1"]["v1_target"] == 4123.5 and "v1_target" not in recs["W1"]
    path2 = tmp_path / "w.jsonl"
    log_new_v2_events(path2, [trig], set(), 1000, None)
    assert "v1_target" not in json.loads(path2.read_text())


def test_a_hung_shadow_job_never_blocks_the_v1_publish_path(monkeypatch):
    """v2_step must return at once while the shadow job runs in its own thread (process mode); a failing job retries once per closed bar, not every cycle."""
    import threading
    import time
    from xau_gateway import app as appmod
    from xau_gateway.candles import Candle
    mk = T.synth_market(n1=60 * 24 * 3)
    appmod.S.engine.closed = {tf: [] for tf in ("M1", "M5", "M15", "H1", "H4")}
    appmod.S.engine.history = {tf: [Candle(tf, int(t), float(o), float(h), float(l), float(c), 1, state="CLOSED", source="MT5_HISTORY", completeness="HISTORICAL")
                                    for t, o, h, l, c in zip(b["time"], b["open"], b["high"], b["low"], b["close"])] for tf, b in mk.items()}
    appmod.S.engine.open = {}
    appmod.V2.update(result=None, m1_t=None, result_t=None, seen=set(), log_from=None, logged=0, job=None, error=None)
    monkeypatch.delenv("XAU_HEAVY_INPROC", raising=False)
    gate = threading.Event()
    calls = []
    monkeypatch.setattr(appmod, "_v2_job", lambda *a: (calls.append(1), gate.wait(5)))
    heavy = eligible_heavy()
    t0 = time.monotonic()
    out = appmod.v2_step({"spread": 0.3}, int(mk["M1"]["time"][-1]) + 60, heavy, 0.3, RP, GP)
    assert out is None and time.monotonic() - t0 < 1.0                                   # no result yet, and it did not wait for the job
    appmod.v2_step({"spread": 0.3}, int(mk["M1"]["time"][-1]) + 61, heavy, 0.3, RP, GP)
    time.sleep(0.2)
    assert len(calls) == 1                                                               # same closed bar: no second submission
    gate.set()
    appmod.V2.update(result=None, m1_t=None, result_t=None, job=None)
    appmod.S.engine.history = {}


# ---------------- Level 5.3: forward-log durability
def _trig(i, **kw):
    return {"event_id": f"T{i}", "version": "m1v2-1", "direction": "BUY", "stage": "M1_TRIGGERED", "kind": "M1_REJECTION", "bar_time": i, "known_at": 2000 + i, "zone": None, "reasons": [], "atr5": 2.0, **kw}


def test_a_failed_write_leaves_ids_unmarked_so_the_next_bar_retries(tmp_path, monkeypatch):
    import os
    path = tmp_path / "v.jsonl"
    seen = set()
    real = os.fsync
    monkeypatch.setattr(os, "fsync", lambda fd: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        log_new_v2_events(path, [_trig(1)], seen, 0)
    assert seen == set()                                                          # never marked before a successful write
    monkeypatch.setattr(os, "fsync", real)
    assert log_new_v2_events(path, [_trig(1)], seen, 0) == 1 and seen == {"T1"}
    assert len([x for x in path.read_text().splitlines() if x.strip()]) >= 1


def test_a_torn_last_line_and_a_restart_do_not_duplicate_or_merge_records(tmp_path):
    from xau_gateway.intel_logic import load_seen_v2
    path = tmp_path / "v.jsonl"
    log_new_v2_events(path, [_trig(1)], set(), 0)
    with open(path, "a", encoding="utf-8", newline="") as f:
        f.write('{"event_id": "TORN", "known_at": 99')                           # crash in the middle of a line
    seen = load_seen_v2(path)                                                      # restart: only complete records count
    assert seen == {"T1"}
    assert log_new_v2_events(path, [_trig(1), _trig(2)], seen, 0) == 1             # T1 not duplicated; T2 starts on its own line
    from xau_intel.m1.evaluate_v2 import read_log
    evs, bad = read_log(path.read_text())
    assert [e["event_id"] for e in evs] == ["T1", "T2"] and bad == 1               # the torn fragment is reported, not fatal, and T2 is intact


def test_legacy_sell_records_are_repaired_on_read_and_the_stored_line_is_untouched():
    from xau_intel.m1.evaluate_v2 import normalize
    old = {"event_id": "S", "direction": "SELL", "trigger_close": -4147.18, "trigger_low": -4148.01}
    fixed = normalize(old)
    assert fixed["trigger_close"] == 4147.18 and fixed["trigger_low"] == 4148.01 and old["trigger_close"] == -4147.18
    new = {"event_id": "S", "direction": "SELL", "trigger_close": 4147.18, "trigger_low": 4148.01, "log_schema": 2}
    assert normalize(new) == new                                                   # schema 2 is already real prices


def test_a_bar_skipped_because_a_job_is_running_is_retried_and_the_job_gets_the_v1_state_known_at_launch(monkeypatch):
    import threading
    import time
    from xau_gateway import app as appmod
    from xau_gateway.candles import Candle
    mk = T.synth_market(n1=60 * 24 * 3)
    appmod.S.engine.closed = {tf: [] for tf in ("M1", "M5", "M15", "H1", "H4")}
    appmod.S.engine.history = {tf: [Candle(tf, int(t), float(o), float(h), float(l), float(c), 1, state="CLOSED", source="MT5_HISTORY", completeness="HISTORICAL")
                                    for t, o, h, l, c in zip(b["time"], b["open"], b["high"], b["low"], b["close"])] for tf, b in mk.items()}
    appmod.S.engine.open = {}
    appmod.V2.update(result=None, m1_t=None, result_t=None, seen=set(), log_from=None, logged=0, job=None, error=None)
    monkeypatch.delenv("XAU_HEAVY_INPROC", raising=False)
    gate, got = threading.Event(), []
    monkeypatch.setattr(appmod, "_v2_job", lambda bars, now, m1_t, v1: (got.append((m1_t, v1)), gate.wait(5)))
    heavy = eligible_heavy()
    heavy["status"]["active"] = {"BUY": {"impulse": {"high_price": 4111.0}}}
    now = int(mk["M1"]["time"][-1]) + 60
    appmod.v2_step({"spread": 0.3}, now, heavy, 0.3, RP, GP)
    time.sleep(0.2)
    heavy["status"]["active"]["BUY"]["impulse"]["high_price"] = 9999.0                   # V1 moves on after the launch: the job must keep what was known at launch
    assert got and got[0][1]["BUY"]["impulse"]["high_price"] == 4111.0
    first_m1 = appmod.V2["m1_t"]
    appmod.S.engine.history["M1"] = appmod.S.engine.history["M1"] + [Candle("M1", int(mk["M1"]["time"][-1]) + 60, 1.0, 1.0, 1.0, 1.0, 1, state="CLOSED", source="MT5_HISTORY", completeness="HISTORICAL")]
    appmod.v2_step({"spread": 0.3}, now + 60, heavy, 0.3, RP, GP)                       # a NEW bar while the job still runs: skipped, and NOT marked as attempted
    assert appmod.V2["m1_t"] == first_m1 and len(got) == 1
    gate.set()
    time.sleep(0.3)
    appmod.v2_step({"spread": 0.3}, now + 60, heavy, 0.3, RP, GP)                       # the job ended: the skipped bar is now retried
    time.sleep(0.2)
    assert len(got) == 2 and got[1][0] > first_m1
    appmod.V2.update(result=None, m1_t=None, result_t=None, job=None)
    appmod.S.engine.history = {}
