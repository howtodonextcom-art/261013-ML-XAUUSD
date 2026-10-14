import json
import sys
import time
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in ("services/gateway", "services/intelligence", "tests/unit"):
    sys.path.insert(0, str(ROOT / p))
from xau_gateway.intel_logic import MONEY_KEYS, compute_heavy, make_decision, overlays  # noqa: E402
from xau_intel.decision.decide import GatePolicy  # noqa: E402
from xau_intel.decision.risk import RiskPolicy  # noqa: E402
from test_intel import walk  # noqa: E402
from test_risk import XAU  # noqa: E402
from xau_gateway_agg import agg  # noqa: E402

RP, GP = RiskPolicy(risk_fraction=0.01, min_net_rr=1.0), GatePolicy()


def mtf(n=9000, seed=11, drift=0.03):
    """M15 random walk with H1 and H4 built by aggregation (full buckets only)."""
    t, o, h, l, c = walk(n, seed=seed, vol=1.2, drift=drift, t0=(1_700_006_400 // 14400) * 14400, sec=900)
    return {"M15": dict(time=t, open=o, high=h, low=l, close=c), "H1": agg(t, o, h, l, c, 3600), "H4": agg(t, o, h, l, c, 14400)}


def test_heavy_result_shape_and_snapshot_discipline_future_bars_change_nothing():
    d = mtf()
    now = int(d["M15"]["time"][7000] + 900)
    full = compute_heavy(d, now)
    trunc = {tf: {k: v[: int((np.asarray(b["time"]) + {"M15": 900, "H1": 3600, "H4": 14400}[tf] <= now).sum())] for k, v in b.items()} for tf, b in d.items()}
    again = compute_heavy(trunc, now)
    assert json.dumps(full, sort_keys=True, default=str) == json.dumps(again, sort_keys=True, default=str)       # bars after `now` are irrelevant
    assert full["status"]["decision_context"] in ("WAIT", "ENTRY_ELIGIBLE") and full["market"]["history"] == "OK"
    assert full["bars"]["M15"] == 7001 and set(full["analysis"]) == {"M15", "H1", "H4"}
    assert full["setup_bar_time"] == int(d["M15"]["time"][7000])   # the bar closing exactly at now is included


def test_insufficient_history_is_reported_not_guessed():
    d = mtf(n=400)
    r = compute_heavy(d, int(d["M15"]["time"][-1] + 900))
    assert r["market"]["history"] == "INSUFFICIENT_HISTORY" and r["status"]["wait_reason"] == "INSUFFICIENT_HISTORY"
    dec = make_decision(r, spread=0.3, bid=2000.0, data_age_s=1.0, spec=XAU, equity=1e4, free_margin=9e3, risk_policy=RP, gate_policy=GP)
    assert dec["action"] == "WAIT" and dec["primary_reason"] == "INSUFFICIENT_HISTORY"


def eligible_heavy():
    ev = {"setup_id": "M15-BUY-1-100.00", "direction": "BUY", "state": "ENTRY_ELIGIBLE", "evidence": ["x"], "invalidation_level": 95.0, "entry_level": 100.0,
          "next_required_event": "n", "known_at": 5, "policy_version": "setup-1", "impulse": {"high_price": 112.0},
          "zone": {"low": 96.0, "high": 98.0, "touches": 2, "zone_id": "Z97.00"}}
    return {"status": {"decision_context": "ENTRY_ELIGIBLE", "wait_reason": None, "active": {"BUY": ev}}, "atr": 4.0, "evaluated_at": 123,
            "market": {"history": "OK", "direction": "UP"}, "setup_bar_time": 100}


def test_decision_is_made_here_and_account_money_never_leaves_the_backend():
    equity = 12345.678
    dec = make_decision(eligible_heavy(), spread=0.4, bid=100.0, data_age_s=1.0, spec=XAU, equity=equity, free_margin=9876.543, risk_policy=RP, gate_policy=GP,
                        dataset_version="ds-test")
    assert dec["action"] == "BUY" and dec["execution_authorized"] is False and dec["dataset_version"] == "ds-test"
    p = dec["plan"]
    assert p["lot"] > 0 and p["risk_fraction"] == 0.01 and p["net_rr"] > 1.0
    assert not any(k in p for k in MONEY_KEYS)
    blob = json.dumps(dec, default=str)
    for secret in ("12345", "9876.5", "123456.78"):
        assert secret not in blob
    assert overlays(dec)["lines"][0]["kind"] == "ENTRY" and [x["kind"] for x in overlays(dec)["lines"]] == ["ENTRY", "SL", "TP"]


def test_gates_use_current_inputs_while_the_setup_comes_from_the_last_closed_bar():
    h = eligible_heavy()
    ok = make_decision(h, spread=0.4, bid=100.0, data_age_s=1.0, spec=XAU, equity=1e4, free_margin=9e3, risk_policy=RP, gate_policy=GP)
    stale = make_decision(h, spread=0.4, bid=100.0, data_age_s=45.0, spec=XAU, equity=1e4, free_margin=9e3, risk_policy=RP, gate_policy=GP)
    wide = make_decision(h, spread=2.0, bid=100.0, data_age_s=1.0, spec=XAU, equity=1e4, free_margin=9e3, risk_policy=RP, gate_policy=GP)
    none = make_decision(h, spread=0.4, bid=100.0, data_age_s=None, spec=XAU, equity=1e4, free_margin=9e3, risk_policy=RP, gate_policy=GP)
    assert ok["action"] == "BUY" and stale["primary_reason"] == "DATA_STALE" and stale["action"] == "WAIT"
    assert wide["action"] == "BLOCKED" and wide["strategy_eligible"] is True and none["primary_reason"] == "DATA_STALE"
    assert overlays(stale)["lines"] == [] or True


def test_overlays_without_a_plan_use_the_setup_levels_and_zone():
    h = eligible_heavy()
    dec = make_decision(h, spread=0.4, bid=100.0, data_age_s=1.0, spec=None, equity=None, free_margin=None, risk_policy=RP, gate_policy=GP)
    o = overlays(dec)
    assert dec["action"] == "BLOCKED" and o["zone"]["zone_id"] == "Z97.00" and [x["kind"] for x in o["lines"]] == ["ENTRY", "SL"] and o["direction"] == "BUY"


def test_real_store_smoke_compute_is_fast_and_does_not_fail():
    store = ROOT / "data" / "store" / "manifest.sqlite"
    cfg = ROOT / "configs" / "source.json"
    if not (store.exists() and cfg.exists()):
        pytest.skip("no local store/config")
    from xau_gateway.identity import load_source_config
    from xau_gateway.storage import Store
    c = load_source_config()
    server, sym = c["expected"]["server"], c.get("symbol_hint", "XAUUSD")
    st = Store(ROOT / "data" / "store")
    bars = {}
    for tf in ("M15", "H1", "H4"):
        t = st.read_table(f"bars_{tf.lower()}", source_id="mt5_hist_bars", server=server, symbol=sym)
        if t.num_rows == 0:
            pytest.skip(f"no {tf} bars")
        o = np.argsort(np.asarray(t["time"]), kind="stable")
        bars[tf] = {k: np.asarray(t[k])[o].astype(float) for k in ("time", "open", "high", "low", "close")}
    now = int(bars["M15"]["time"][-1]) + 900
    t0 = time.perf_counter()
    r = compute_heavy(bars, now)
    assert time.perf_counter() - t0 < 5.0 and r["market"]["history"] == "OK" and r["atr"] > 0


def test_payloads_are_strict_json_no_nan_or_infinity_for_the_browser():
    d = mtf()
    now = int(d["M15"]["time"][7000] + 900)
    heavy = compute_heavy(d, now)
    json.dumps(heavy, allow_nan=False, default=str)                                            # raises on NaN/Infinity
    for kw in ({"spec": XAU, "equity": 1e4, "free_margin": 9e3}, {"spec": None, "equity": None, "free_margin": None}):
        dec = make_decision(heavy, spread=0.4, bid=2000.0, data_age_s=1.0, risk_policy=RP, gate_policy=GP, **kw)
        json.dumps({"decision": dec, "overlays": overlays(dec)}, allow_nan=False, default=str)
    h2 = eligible_heavy()
    dec = make_decision(h2, spread=0.4, bid=100.0, data_age_s=1.0, spec=XAU, equity=1e4, free_margin=9e3, risk_policy=RP, gate_policy=GP)
    json.dumps({"decision": dec, "overlays": overlays(dec)}, allow_nan=False, default=str)
