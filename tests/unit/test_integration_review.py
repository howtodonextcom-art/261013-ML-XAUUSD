"""Regression tests for the independent review of the live integration."""
import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in ("services/gateway", "services/intelligence", "tests/unit"):
    sys.path.insert(0, str(ROOT / p))
from xau_gateway.intel_logic import make_decision, overlays, strict  # noqa: E402
from xau_intel.decision.decide import GatePolicy, decide  # noqa: E402
from xau_intel.decision.risk import RiskPolicy  # noqa: E402
from test_intel_logic import eligible_heavy  # noqa: E402
from test_risk import XAU  # noqa: E402

RP = RiskPolicy(risk_fraction=0.01, min_net_rr=1.0)
GP = GatePolicy()


def dec(h=None, **kw):
    base = dict(spread=0.4, bid=100.0, data_age_s=1.0, spec=XAU, equity=1e4, free_margin=9e3, risk_policy=RP, gate_policy=GP)
    base.update(kw)
    return make_decision(h or eligible_heavy(), **base)


def test_a_stale_decision_publishes_no_levels():
    assert overlays(dec())["lines"]                                        # fresh: levels exist
    s = dec(data_age_s=999.0)
    assert s["action"] == "WAIT" and s["primary_reason"] == "DATA_STALE"
    o = overlays(s)
    assert o["lines"] == [] and o["zone"] is None
    assert overlays(dec(data_age_s=None))["lines"] == []


def test_the_displayed_setup_is_the_one_the_decision_is_based_on():
    h = eligible_heavy()
    elig = h["status"]["active"]["BUY"]
    forming = {**elig, "setup_id": "FORMING-1", "state": "SETUP_FORMING", "direction": "SELL"}
    h["status"]["active"] = {"SELL": forming, "BUY": elig}                # the non-eligible one comes first
    d = dec(h)
    assert d["action"] == "BUY" and d["setup"]["setup_id"] == elig["setup_id"] and d["setup"]["state"] == "ENTRY_ELIGIBLE"
    assert overlays(d)["direction"] == "BUY"


def test_extra_gates_such_as_a_failed_bar_fill_block_an_eligible_setup():
    d = dec(extra_gates=["BAR_HISTORY_FILL_FAILED"])
    assert d["action"] == "BLOCKED" and d["strategy_eligible"] is True and d["primary_reason"] == "BAR_HISTORY_FILL_FAILED"
    n = dec(h={"status": {"decision_context": "WAIT", "wait_reason": "AWAITING_PULLBACK", "active": {}}, "atr": 4.0, "market": {"history": "OK"}, "evaluated_at": 1},
            extra_gates=["BAR_HISTORY_FILL_FAILED"])
    assert n["primary_reason"] == "AWAITING_PULLBACK" and "BAR_HISTORY_FILL_FAILED" in n["reasons"]["gate"]       # still never hides the strategy reason


def test_strict_json_replaces_non_finite_numbers_so_the_browser_can_parse_them():
    p = {"a": float("nan"), "b": [1.0, float("inf"), {"c": float("-inf")}], "d": np.float64("nan"), "e": 3, "f": np.float32(2.5)}
    s = strict(p)
    out = json.dumps(s, allow_nan=False)
    assert json.loads(out) == {"a": None, "b": [1.0, None, {"c": None}], "d": None, "e": 3, "f": 2.5}


def test_a_nan_spread_degrades_to_not_evaluable_instead_of_raising(monkeypatch):
    monkeypatch.setenv("XAU_REVEAL_SIZE", "1")                                  # live sizing: the real equity is used (in privacy mode it is ignored, see test_privacy)
    d = dec(spread=float("nan"))
    assert d["action"] in ("BLOCKED", "WAIT")
    assert d["risk"]["status"] == "RISK_NOT_EVALUABLE" or d["action"] == "WAIT"
    d2 = dec(equity=float("nan"))
    assert d2["action"] == "BLOCKED" and d2["risk"]["status"] == "RISK_NOT_EVALUABLE"


# ---------------------------------------------------------------- worker behaviour (app.py)
def _run_worker(seconds=3.0):
    import threading
    import time
    from types import SimpleNamespace
    from xau_gateway import app as appmod
    src = SimpleNamespace(stop_ev=threading.Event(), status={"last_data_monotonic": time.monotonic()}, spec=None, account=None)
    t = threading.Thread(target=appmod.intel_worker, args=(src, "ds-test"), daemon=True)
    t.start()
    time.sleep(seconds)
    src.stop_ev.set()
    appmod.INTEL_EVENT.set()
    t.join(5)
    return appmod


def test_engine_error_publishes_a_visible_wait_record_and_never_leaks_exception_text(monkeypatch):
    from xau_gateway import app as appmod

    def boom(*a, **k):
        raise RuntimeError("equity=12345.67 free=999.9")
    monkeypatch.setattr(appmod, "compute_heavy", boom)
    appmod.INTEL.update(payload=None, pub=None, heavy=None, error=None, updated_monotonic=None, heavy_at=0.0)
    appmod.S.last_tick = {"time_msc": 1_791_925_680_000, "bid": 100.0, "ask": 100.4, "spread": 0.4}
    appmod.INTEL_EVENT.set()
    _run_worker(3.0)
    p = appmod.INTEL["payload"]
    assert p is not None and p["decision"]["action"] == "WAIT" and p["decision"]["primary_reason"] == "INTEL_ENGINE_ERROR"
    assert appmod.INTEL["error"] == "RuntimeError"
    blob = json.dumps(p, allow_nan=False)
    assert "12345" not in blob and "999.9" not in blob and p["overlays"]["lines"] == []


def test_worker_does_not_spin_when_there_is_no_tick_yet(monkeypatch):
    from xau_gateway import app as appmod
    calls = {"n": 0}
    real = appmod.INTEL_EVENT.wait

    def counting_wait(timeout=None):
        calls["n"] += 1
        return real(timeout)
    monkeypatch.setattr(appmod.INTEL_EVENT, "wait", counting_wait, raising=False)
    appmod.S.last_tick = None
    appmod.INTEL.update(payload=None, pub=None, heavy=None, error=None, updated_monotonic=None, heavy_at=0.0)
    appmod.INTEL_EVENT.set()                       # fill_recent_bars sets it at start-up, before any tick exists
    _run_worker(1.5)
    assert calls["n"] <= 3, calls                   # a busy loop would call wait() thousands of times
    assert appmod.INTEL["payload"] is None


# ---------------------------------------------------------------- round 6 (independent re-review of the round-5 fixes)
def test_host_and_origin_guard_helper():
    from xau_gateway.app import _host_ok
    for good in (None, "", "127.0.0.1:8765", "localhost:8765", "http://127.0.0.1:8765", "http://localhost:8765", "[::1]:8765"):
        assert _host_ok(good), good
    for bad in ("evil.example", "evil.example:8765", "https://evil.example", "http://127.0.0.1.evil.example:8765", "192.168.1.5:8765", "null", "http://localhost.evil.com"):
        assert not _host_ok(bad), bad


def test_http_and_websocket_refuse_foreign_host_and_origin():
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect
    from xau_gateway.app import app
    c = TestClient(app, base_url="http://127.0.0.1:8765")           # no lifespan: no MT5 is started
    assert c.get("/api/intel", headers={"host": "evil.example:8765"}).status_code == 403          # DNS rebinding
    assert c.get("/api/intel", headers={"origin": "https://evil.example"}).status_code == 403
    assert c.get("/api/intel").status_code == 200
    for hdr in ({"origin": "https://evil.example"}, {"host": "evil.example:8765"}):
        with pytest.raises(WebSocketDisconnect):
            with c.websocket_connect("/ws", headers=hdr) as w:
                w.receive_text()


def test_the_backend_never_serves_an_old_decision_as_current():
    import time
    from xau_gateway import app as appmod
    buy = dec()
    assert buy["action"] == "BUY"
    appmod.INTEL.update(pub=({"type": "intel", "decision": buy, "overlays": overlays(buy), "seq": 7}, time.monotonic() - 100), error=None)
    out = appmod.served_intel()
    d = out["decision"]
    assert d["action"] == "WAIT" and d["primary_reason"] == "DATA_STALE" and d["setup"] is None and d["plan"] is None
    assert out["overlays"]["lines"] == [] and out["intel_age_s"] > 90
    assert out["decision"]["strategy_eligible"] is False and out["decision"]["risk"] is None and "hypothetical" not in out["decision"]["next_required"]
    appmod.INTEL.update(pub=({"type": "intel", "decision": buy, "overlays": overlays(buy), "seq": 7}, time.monotonic() - 1))
    assert appmod.served_intel()["decision"]["action"] == "BUY"        # fresh: served as is
    appmod.INTEL.update(pub=None)
    assert appmod.served_intel() is None


def test_payload_is_published_with_its_age_and_a_monotonic_sequence():
    from xau_gateway import app as appmod
    appmod.INTEL.update(pub=None)
    a = appmod.INTEL["seq"]
    appmod.publish_intel({"type": "intel"})
    appmod.publish_intel({"type": "intel"})
    p, t = appmod.INTEL["pub"]
    assert p["seq"] == a + 2 and t is not None and appmod.served_intel()["seq"] == a + 2


def test_a_failed_recompute_discards_the_old_setup_instead_of_republishing_it(monkeypatch):
    import time
    from xau_gateway import app as appmod

    def boom(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr(appmod, "compute_heavy", boom)
    appmod.INTEL.update(payload=None, pub=None, heavy=eligible_heavy(), error=None, updated_monotonic=None, heavy_at=time.monotonic(), retry_at=0.0)
    appmod.S.last_tick = {"time_msc": 1_791_925_680_000, "bid": 100.0, "ask": 100.4, "spread": 0.4}
    appmod.INTEL_EVENT.set()                                           # a bar close: recompute is attempted and fails
    _run_worker(5.0)                                                   # >= 2 worker cycles: the second one must NOT fall back to the pre-error heavy result
    p = appmod.INTEL["payload"]
    assert appmod.INTEL["heavy"] is None
    assert p["decision"]["action"] == "WAIT" and p["decision"]["primary_reason"] == "INTEL_ENGINE_ERROR" and p["overlays"]["lines"] == []


def test_strict_converts_numpy_arrays():
    assert strict({"a": np.array([1.0, float("nan")])}) == {"a": [1.0, None]}


# ---------------------------------------------------------------- round 6b (second independent re-review)
def test_host_origin_parser_rejects_userinfo_port_tricks_and_foreign_ports():
    from xau_gateway.app import request_allowed
    ok = ("127.0.0.1:8765", None), ("localhost:8765", "http://localhost:8765"), ("127.0.0.1:8765", "http://127.0.0.1:8765"), ("[::1]:8765", "http://[::1]:8765"), ("127.0.0.1:8765", "")
    for host, origin in ok:
        assert request_allowed(host, origin), (host, origin)
    bad = [("127.0.0.1:x@evil.com", None), ("127.0.0.1:80@evil.com", None), ("127.0.0.1:8765", "http://127.0.0.1:80@evil.com"), ("127.0.0.1:8765", "http://127.0.0.1@evil.com"),
           ("127.0.0.1:8765", "http://127.0.0.1:9999"), ("127.0.0.1:8765", "null"), ("127.0.0.1:8765", "file://"), ("127.0.0.1.evil.com:8765", None),
           ("evil.com", None), (None, None), ("testserver", None), ("127.0.0.1:99999", None), ("127.0.0.1:8765", "https://evil.example")]
    for host, origin in bad:
        assert not request_allowed(host, origin), (host, origin)


def test_the_error_backoff_never_becomes_a_hot_loop(monkeypatch):
    import time
    from xau_gateway import app as appmod
    seqs = []
    real = appmod.publish_intel
    monkeypatch.setattr(appmod, "publish_intel", lambda p: (seqs.append(1), real(p))[1])
    appmod.INTEL.update(payload=None, pub=None, heavy=None, error=None, updated_monotonic=None, heavy_at=0.0, retry_at=time.monotonic() + 30.0)   # in back-off
    appmod.S.last_tick = {"time_msc": 1_791_925_680_000, "bid": 100.0, "ask": 100.4, "spread": 0.4}
    appmod.INTEL_EVENT.set()                                           # a bar close arrives during the back-off
    _run_worker(1.5)
    assert len(seqs) <= 4, f"{len(seqs)} publishes in 1.5 s: the worker spins while in back-off"


def test_a_failing_error_payload_builder_cannot_kill_the_worker(monkeypatch):
    from xau_gateway import app as appmod
    monkeypatch.setattr(appmod, "strict", lambda o: (_ for _ in ()).throw(ValueError("boom")))
    p = appmod._error_payload(RuntimeError("x"), "ds")
    assert p["decision"]["action"] == "WAIT" and p["decision"]["primary_reason"] == "INTEL_ENGINE_ERROR" and p["decision"]["plan"] is None


def test_next_required_names_the_real_blocker():
    from xau_intel.decision.decide import GatePolicy, decide
    h = eligible_heavy()
    def d(**kw):
        a = dict(atr=h["atr"], spread=0.4, spec=XAU, equity=1e4, free_margin=9e3, data_age_s=1.0, market_open=True, price_now_bid=100.0, risk_policy=RP, gate_policy=GP)
        a.update(kw)
        return decide(h["status"], **a)
    assert "spread" in d(spread=10.0)["next_required"]
    assert "free margin" in d(free_margin=1e-3)["next_required"]
    assert "reward-to-risk" in d(risk_policy=RiskPolicy(risk_fraction=0.01, min_net_rr=50.0))["next_required"]
    assert "conflicting" in decide({**h["status"], "wait_reason": "SIGNAL_CONFLICT"}, atr=h["atr"], spread=0.4, spec=XAU, equity=1e4, free_margin=9e3, data_age_s=1.0,
                                   market_open=True, price_now_bid=100.0, risk_policy=RP, gate_policy=GP)["next_required"]
    assert "fresh data" in d(data_age_s=999.0)["next_required"]
    assert "hypothetical" in d()["next_required"]
