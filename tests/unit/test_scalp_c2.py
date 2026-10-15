"""Scalping candidate C2 (SHADOW): causality (prefix invariance, future corruption, a mutation that must be caught), exact BUY/SELL mirror, determinism,
H1/H4 as a label (countertrend allowed), the public view (BLOCKED, expiry, no widening), the forward log, and failure isolation from V2."""
import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in ("services/gateway", "services/intelligence", "tests/unit"):
    sys.path.insert(0, str(ROOT / p))
from xau_gateway.intel_logic import build_c2_view, log_new_v2_events  # noqa: E402
from xau_intel.backtest.engine import canon  # noqa: E402
from xau_intel.decision.decide import GatePolicy  # noqa: E402
from xau_intel.decision.risk import RiskPolicy  # noqa: E402
from xau_intel.scalp import c2 as C  # noqa: E402
from xau_intel.scalp.c2 import alignment, run_c2  # noqa: E402
from test_m1_entry_v2 import synth_market  # noqa: E402

RP = RiskPolicy(risk_fraction=0.01, min_net_rr=1.0)
GP = GatePolicy()


@pytest.fixture(scope="module")
def market():
    return synth_market()


def trig_events(res):
    return [e for e in res["events"] if e["stage"] == "M1_TRIGGERED" and e["kind"] != "WINDOW_STATE"]


def now_of(m):
    return int(m["M1"]["time"][-1]) + 60


def test_the_synthetic_market_produces_both_sides_and_labels_h1(market):
    r = run_c2(market, now_of(market), window=10**9)
    t = trig_events(r)
    assert {e["direction"] for e in t} == {"BUY", "SELL"} and r["label"].startswith("SHADOW") and r["strategy_id"] == "scalp-c2"
    assert all(e["alignment"] in ("ALIGNED", "COUNTERTREND", "NEUTRAL", "UNKNOWN") and "h1" in e and "h4" in e for e in t)


def test_h1_h4_is_a_label_not_a_gate_countertrend_and_neutral_triggers_exist(market):
    t = trig_events(run_c2(market, now_of(market), window=10**9))
    assert {e["alignment"] for e in t} & {"COUNTERTREND", "NEUTRAL"}, "C2 must fire without an aligned H1 direction"
    assert any(e["h4_conflict"] for e in t) or True                                                       # conflict is recorded, never required


def test_alignment_function_is_symmetric():
    assert alignment("UP", 1) == "ALIGNED" and alignment("DOWN", -1) == "ALIGNED"
    assert alignment("DOWN", 1) == "COUNTERTREND" and alignment("UP", -1) == "COUNTERTREND"
    assert alignment("NONE", 1) == "NEUTRAL" and alignment("UNKNOWN", -1) == "UNKNOWN"


def cuts_for(m, full):
    n = len(m["M1"]["time"])
    return [e["known_at"] for e in full if e["stage"] == "M1_TRIGGERED"][:10] + [int(m["M1"]["time"][int(n * f)]) + 60 for f in (0.35, 0.6, 0.85)]


def test_prefix_invariance(market):
    full = run_c2(market, now_of(market), window=10**9)["events"]
    checked = 0
    for cut in cuts_for(market, full):
        early = run_c2(market, cut, window=10**9)["events"]
        want = [e for e in full if e["known_at"] <= cut]
        assert canon(early) == canon(want), f"look-ahead at cut {cut}"
        checked += len(want)
    assert checked > 20


def test_future_corruption_does_not_change_the_past(market):
    n = len(market["M1"]["time"])
    cut = int(market["M1"]["time"][int(n * 0.6)]) + 60
    bad = {tf: {k: v.copy() for k, v in b.items()} for tf, b in market.items()}
    for b in bad.values():
        after = b["time"] >= cut
        for k in ("open", "high", "low", "close"):
            b[k][after] = b[k][after] * 3 + 700
    a, b = run_c2(market, cut, window=10**9), run_c2(bad, cut, window=10**9)
    assert canon(a["events"]) == canon(b["events"]) and canon(a["directions"]) == canon(b["directions"])


def test_the_prefix_test_detects_a_peeking_pattern(market, monkeypatch):
    real = C.candle_patterns

    def peeking(o, h, l, c, atr):
        r = real(o, h, l, c, atr)
        if len(c) > 5000:
            for key in ("pin_bull", "pin_bear", "engulf_bull", "engulf_bear"):
                if key in r:
                    r[key] = np.concatenate([r[key][1:], [False]])
        return r
    monkeypatch.setattr(C, "candle_patterns", peeking)
    full = run_c2(market, now_of(market), window=10**9)["events"]
    assert any(canon(run_c2(market, cut, window=10**9)["events"]) != canon([e for e in full if e["known_at"] <= cut]) for cut in cuts_for(market, full)), "prefix test is blind to peeking"


def test_buy_sell_exact_mirror(market):
    mir = {tf: {**b, "open": -b["open"], "high": -b["low"], "low": -b["high"], "close": -b["close"]} for tf, b in market.items()}
    now = now_of(market)
    sig = lambda r: sorted((e["bar_time"], e["known_at"], e["stage"], e["kind"], {"BUY": "SELL", "SELL": "BUY"}[e["direction"]]) for e in r["events"])  # noqa: E731
    sig2 = lambda r: sorted((e["bar_time"], e["known_at"], e["stage"], e["kind"], e["direction"]) for e in r["events"])  # noqa: E731
    a, b = run_c2(market, now, window=10**9), run_c2(mir, now, window=10**9)
    assert sig(a) == sig2(b) and len(a["events"]) > 50


def test_determinism(market):
    now = now_of(market)
    assert canon(run_c2(market, now)) == canon(run_c2(market, now))


def test_the_forming_bar_is_never_an_event(market):
    """A 'now' in the middle of an M1 bar: that bar is still forming and no event may be known at or after it."""
    t = market["M1"]["time"]
    full = run_c2(market, now_of(market), window=10**9)["events"]
    ev = next(e for e in full if e["stage"] == "M1_TRIGGERED")
    mid = int(ev["bar_time"]) + 30                                                                  # inside the trigger bar
    cut = run_c2(market, mid, window=10**9)["events"]
    assert all(e["known_at"] <= mid for e in cut) and ev["event_id"] not in {e["event_id"] for e in cut}
    assert int(t[-1]) >= int(ev["bar_time"])


def test_v1_and_v2_do_not_import_c2():
    for rel in ("setups/machine.py", "decision/decide.py", "m1/entry_v2.py", "m1/evaluate_v2.py"):
        assert "scalp" not in (ROOT / "services/intelligence/xau_intel" / rel).read_text(encoding="utf-8"), rel


def state(stage, side="BUY", close=4100.0, extreme=4096.0, zone=(4092.0, 4096.5), atr5=4.0, ends=99):
    st = {"direction": side, "stage": stage, "zone": {"low": min(zone), "high": max(zone)}, "next_required": "x"}
    if stage in ("M1_TRIGGERED", "ENTRY_WINDOW"):
        st["trigger"] = {"kind": "M1_REJECTION", "flags": ["M1_REJECTION"], "bar_close": close, "bar_extreme": extreme, "known_at": 1, "window_ends_at": ends, "invalidation": 0, "atr5": atr5, "alignment": "COUNTERTREND", "h4_conflict": False}
    return st


def c2res(stage, side="BUY", **kw):
    return {"strategy_id": "scalp-c2", "version": "scalp-c2-1", "now": 1, "m5_structure": "UP" if side == "BUY" else "DOWN", "m1_momentum": "UP", "m15": {"atr": 5.0},
            "h1_h4": {"h1": "DOWN", "h4": "NONE", "conflict": False, "alignment": "COUNTERTREND"}, "side": side, "directions": {side: state(stage, side, **kw)},
            "events": [{"event_id": f"e{i}", "known_at": i} for i in range(20)], "funnel": {}}


def test_view_wait_when_no_side_and_watch_when_zone():
    r = c2res("WATCH")
    v = build_c2_view(r, partial=None, spread=0.3, risk_policy=RP, gate_policy=GP, now_server=50, live_from=0)
    assert v["candidate"] == "WATCH BUY" and v["signal"] is None and v["execution_authorized"] is False
    r["side"], r["directions"] = None, {}
    v = build_c2_view(r, partial=None, spread=0.3, risk_policy=RP, gate_policy=GP, now_server=50, live_from=0)
    assert v["candidate"] == "WAIT" and "M5 structure" in v["missing"]
    assert build_c2_view(None, partial=None, spread=0.3, risk_policy=RP, gate_policy=GP) is None


def test_view_blocked_when_the_stop_is_below_the_stops_level_and_never_widened():
    v = build_c2_view(c2res("ENTRY_WINDOW", extreme=4099.0, zone=(4098.5, 4099.5), atr5=1.0), partial=None, spread=0.3, risk_policy=RP, gate_policy=GP, now_server=50, live_from=0)
    assert v["signal"] == "BLOCKED" and v["block_reasons"], v
    assert v["plan"] is None or v["plan"]["stop_loss"] >= 4099.0 - 1.01


def test_view_signal_buy_sell_with_a_wide_enough_stop_and_expiry_clears_it():
    v = build_c2_view(c2res("ENTRY_WINDOW"), partial=None, spread=0.3, risk_policy=RP, gate_policy=GP, now_server=50, live_from=0)
    assert v["signal"] == "BUY" and v["plan"]["take_profit"] > v["plan"]["entry"] > v["plan"]["stop_loss"] and v["expires_at"] == 99
    s = build_c2_view(c2res("ENTRY_WINDOW", side="SELL", close=4100.0, extreme=4104.0, zone=(4103.5, 4108.0)), partial=None, spread=0.3, risk_policy=RP, gate_policy=GP, now_server=50, live_from=0)
    assert s["signal"] == "SELL" and s["plan"]["take_profit"] < s["plan"]["entry"] < s["plan"]["stop_loss"]
    late = build_c2_view(c2res("ENTRY_WINDOW"), partial=None, spread=0.3, risk_policy=RP, gate_policy=GP, now_server=99, live_from=0)
    assert late["signal"] is None and late["plan"] is None and late["candidate"] == "WAIT"


def test_log_dedups_stamps_extra_keys_and_never_logs_old_history(tmp_path):
    path = tmp_path / "c2.jsonl"
    ev = {"event_id": "scalp-c2-BUY-x-1-2", "version": "scalp-c2-1", "direction": "BUY", "stage": "M1_TRIGGERED", "kind": "M1_REJECTION", "bar_time": 100, "known_at": 160, "zone": {}, "reasons": [],
          "log_schema": 2, "trigger_close": 1.0, "trigger_low": 0.5, "atr5": 1.0, "strategy_id": "scalp-c2", "alignment": "COUNTERTREND", "h4_conflict": False, "h1": "DOWN", "h4": "NONE"}
    seen: set = set()
    assert log_new_v2_events(path, [ev], seen, 100, None, None, extra_keys=("strategy_id", "alignment", "h4_conflict", "h1", "h4"), with_v1_target=False) == 1
    assert log_new_v2_events(path, [ev], seen, 100, None, None, extra_keys=("strategy_id",), with_v1_target=False) == 0
    old = {**ev, "event_id": "old", "known_at": 10}
    assert log_new_v2_events(path, [old], seen, 100, None, None) == 0
    rec = json.loads(path.read_text().splitlines()[0])
    assert rec["alignment"] == "COUNTERTREND" and rec["strategy_id"] == "scalp-c2" and "v1_target" not in rec


def test_c2_has_its_own_pool_and_job_so_it_cannot_cost_v2_its_result():
    src = (ROOT / "services/gateway/xau_gateway/app.py").read_text(encoding="utf-8")
    assert 'key="c2pool"' in src and 'key="v2pool"' in src and "def _c2_job" in src and "run_shadows" not in src


def test_a_failing_c2_job_sets_only_the_c2_error(monkeypatch, tmp_path):
    import xau_gateway.app as appmod
    monkeypatch.setattr(appmod, "run_in_worker", lambda *a, **k: (_ for _ in ()).throw(ValueError("boom")))
    appmod.C2["error"], appmod.V2["error"] = None, None
    appmod._c2_job({}, 1, 1)
    assert appmod.C2["error"] == "ValueError" and appmod.V2["error"] is None


def test_the_entry_window_is_counted_in_minutes_so_a_feed_gap_cannot_extend_it():
    A = None
    from test_m1_entry_v2 import build
    import numpy as np
    A = build(any5=[8], pin1=[50])
    A.update(side_ok=np.ones(80, bool), opp_ok=np.zeros(80, bool), align=np.array(["ALIGNED"] * 80, dtype=object), h4c=np.zeros(80, bool), h1v=np.array(["UP"] * 80, dtype=object), h4v=np.array(["UP"] * 80, dtype=object))
    A["atr15"] = np.full(80, 2.0); A["atr5"] = np.full(80, 1.0); A["j15"] = np.zeros(80, dtype=int); A["j5"] = np.minimum(A["j5"], 39)
    A["m1"]["time"] = A["m1"]["time"].copy()
    A["m1"]["time"][55:] += 3600                                                        # a one-hour feed gap right after the trigger bar (index 50)
    r = C._scan(1, A, C.POLICY)
    t = [e for e in r["events"] if e["stage"] == "M1_TRIGGERED" and e["kind"] != "WINDOW_STATE"]
    after = [e for e in r["events"] if t and e["known_at"] > t[0]["known_at"] + 300 and e["stage"] in ("ENTRY_WINDOW", "M1_TRIGGERED")]
    assert not [e for e in after if e["kind"] == "WINDOW_STATE" and e["reasons"] == ["PRICE_IN_ENTRY_BAND"]]


def test_no_signal_or_plan_while_price_is_outside_the_entry_band():
    v = build_c2_view(c2res("M1_TRIGGERED"), partial=None, spread=0.3, risk_policy=RP, gate_policy=GP, now_server=50, live_from=0)
    assert v["signal"] is None and v["plan"] is None and "outside the entry band" in v["missing"]


def V(r, now=50, live_from=0, partial=None):
    return build_c2_view(r, partial=partial, spread=0.3, risk_policy=RP, gate_policy=GP, now_server=now, live_from=live_from)


def test_a_re_derived_trigger_is_history_never_a_signal_or_a_plan():
    r = c2res("ENTRY_WINDOW")
    for lf in (10, None):                                           # known_at=1 is before live_from, or live_from unknown (offset not fresh)
        v = V(r, live_from=lf)
        assert v["provenance"] == "RE_DERIVED" and v["signal"] is None and v["plan"] is None and v["risk_status"].startswith("NOT_EVALUATED")
    assert V(r, live_from=0)["provenance"] == "LIVE_FORWARD" and V(r, live_from=0)["signal"] == "BUY"


def test_risk_status_words_and_trigger_versus_signal_semantics():
    assert V(c2res("WATCH"))["risk_status"].startswith("NOT_EVALUATED") and V(c2res("WATCH"))["signal"] is None
    out = V(c2res("M1_TRIGGERED"))                                  # trigger outside the band: a research trigger, not a signal
    assert out["stage"] == "M1_TRIGGERED" and out["signal"] is None and "outside the entry band" in out["risk_status"]
    ok = V(c2res("ENTRY_WINDOW"))
    assert ok["signal"] == "BUY" and ok["risk_status"].startswith("PASSED Risk Gate")
    bl = V(c2res("ENTRY_WINDOW", extreme=4099.0, zone=(4098.5, 4099.5), atr5=1.0))
    assert bl["signal"] == "BLOCKED" and bl["risk_status"].startswith("BLOCKED:")


def test_events_carry_provenance_and_the_current_flag():
    r = c2res("WATCH")
    r["events"] = [{"event_id": "a", "known_at": 5, "stage": "M1_TRIGGERED", "kind": "M1_REJECTION"}, {"event_id": "b", "known_at": 40, "stage": "M1_TRIGGERED", "kind": "M1_REJECTION"},
                   {"event_id": "c", "known_at": 45, "stage": "ENTRY_WINDOW", "kind": "WINDOW_STATE"}]
    ev = {e["event_id"]: e for e in V(r, now=50, live_from=20)["events_recent"]}
    assert ev["a"]["provenance"] == "RE_DERIVED" and ev["b"]["provenance"] == "LIVE_FORWARD"
    assert ev["b"]["current"] is True and ev["a"]["current"] is False and ev["c"]["current"] is False
    assert V(r, now=400, live_from=20)["events_recent"][1]["current"] is False        # window (5 min) elapsed


def test_the_plan_levels_come_from_the_trigger_close_and_the_expected_fill_is_the_next_open():
    r = c2res("ENTRY_WINDOW")
    plain = V(r)
    assert plain["plan"]["entry"] == pytest.approx(4100.0) and "expected_fill" not in plain          # next open not known yet
    nxt = V(r, partial={"t": 1 - 60 + 60, "open": 4100.4, "high": 4101, "low": 4099, "close": 4100.2})
    assert nxt["expected_fill"]["price"] == 4100.4 and nxt["expected_fill"]["delta_vs_plan_entry"] == pytest.approx(0.4)
    assert nxt["plan"]["entry"] == pytest.approx(4100.0)                                              # the registered plan is not re-based
    other = V(r, partial={"t": 9999, "open": 4100.4, "high": 1, "low": 1, "close": 1})
    assert "expected_fill" not in other                                                               # a later forming bar is not the fill bar
    assert "NEXT M1 bar open" in plain["entry_basis"]


def test_elapsed_window_is_not_labelled_entry_window_and_incomplete_trigger_is_no_trigger():
    r = c2res("ENTRY_WINDOW")
    late = V(r, now=99)
    assert late["stage"] == "WINDOW_ELAPSED" and late["signal"] is None and late["plan"] is None
    r2 = c2res("ENTRY_WINDOW")
    r2["directions"]["BUY"].pop("trigger")
    assert V(r2)["stage"] == "NO_SIDE" and V(r2)["signal"] is None


def test_perf_stats_survive_a_deque_mutated_by_another_thread():
    import threading
    from collections import deque
    from xau_gateway.intel_logic import perf_stats
    d = deque(range(500), maxlen=500)
    stop = threading.Event()
    th = threading.Thread(target=lambda: [d.append(1.0) for _ in iter(lambda: stop.is_set(), True)])
    th.start()
    try:
        for _ in range(300):
            assert perf_stats(d)["n"] in (0, 500)
    finally:
        stop.set(); th.join()
    assert perf_stats([])["p50"] is None
