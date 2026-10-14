"""Gateway integration of the V1 decision events: first publication only, durable, restart-safe, served by /api/decisions, stale clears the current id (Level 6.2)."""
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in ("services/gateway", "services/intelligence", "tests/unit"):
    sys.path.insert(0, str(ROOT / p))
import test_v1_production_path as P  # noqa: E402
from test_v1_production_path import SC, bars, production  # noqa: E402,F401


@pytest.fixture()
def gw(tmp_path, monkeypatch):
    from xau_gateway import app as appmod
    monkeypatch.setattr(appmod, "V1_EVENTS_PATH", tmp_path / "decisions" / "v1_events.jsonl")
    monkeypatch.setattr(appmod, "SOURCE", None)
    appmod.V1EV.update(seen=set(), seeded=False, recent=[], logged=0, error=None)
    yield appmod
    appmod.V1EV.update(seen=set(), seeded=False, recent=[], logged=0, error=None)


def test_a_published_buy_is_recorded_once_across_many_refreshes_and_survives_a_restart(gw, bars):
    heavy, dec, _ = production(bars, "BUY_PUBLISHED")
    tick = {"bid": 4100.0}
    ids = [gw.v1_event_step(dec, tick, SC["BUY_PUBLISHED"]["now"] + 1 + i, heavy) for i in range(30)]       # 30 refreshes, 2 s apart, same decision
    assert set(ids) == {f"{dec['setup']['setup_id']}|BUY"}                                                  # the current id is reported every time, the record is written once
    assert gw.V1EV["logged"] == 1 and len(gw.V1EV["recent"]) == 1
    gw.V1EV.update(seen=set(), seeded=False, recent=[], logged=0)                                           # gateway restart: memory gone, file stays
    gw.v1_event_step(dec, tick, SC["BUY_PUBLISHED"]["now"] + 99, heavy)
    assert gw.V1EV["logged"] == 0 and len(gw.V1EV["recent"]) == 1                                           # reloaded from the file, nothing duplicated
    body = __import__("json").loads(gw.api_decisions(limit=10).body)
    assert body["historical"] is True and body["execution_authorized"] is False and len(body["events"]) == 1 and body["events"][0]["action"] == "BUY"


def test_wait_and_stale_decisions_record_nothing_and_have_no_current_id(gw, bars):
    heavy, dec, _ = production(bars, "NO_VALID_IMPULSE_DOWN")
    assert gw.v1_event_step(dec, {"bid": 1.0}, 1, heavy) is None and gw.V1EV["logged"] == 0
    heavy, dec, _ = production(bars, "BUY_BLOCKED")
    assert gw.v1_event_step(dec, {"bid": 1.0}, 2, heavy) is None and gw.V1EV["logged"] == 1                 # a BLOCKED event is stored, but it is never the current BUY/SELL
    assert gw.V1EV["recent"][0]["action"] == "BLOCKED"


def test_the_payload_served_after_a_stall_keeps_the_history_but_drops_the_current_id(gw):
    ev = {"decision_id": "S|BUY", "action": "BUY"}
    gw.INTEL.update(pub=({"type": "intel", "decision": {"action": "BUY"}, "overlays": {}, "m1_shadow": None, "v1_events": [ev], "v1_current_id": "S|BUY", "seq": 1}, time.monotonic() - 100))
    out = gw.served_intel()
    assert out["v1_current_id"] is None and out["v1_events"] == [ev] and out["decision"]["action"] == "WAIT" and out["decision"]["primary_reason"] == "DATA_STALE"
    gw.INTEL.update(pub=None)


def test_a_failing_history_log_never_changes_the_decision_and_is_surfaced(gw, bars, monkeypatch):
    heavy, dec, _ = production(bars, "BUY_PUBLISHED")
    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(gw, "log_v1_events", boom)
    cur = gw.v1_event_step(dec, {"bid": 1.0}, 5, heavy)
    assert cur == f"{dec['setup']['setup_id']}|BUY"                                   # the current decision is still reported
    assert gw.V1EV["error"] == "OSError" and gw.V1EV["logged"] == 0 and gw.V1EV["recent"] == []
    monkeypatch.undo()
    gw.v1_event_step(dec, {"bid": 1.0}, 6, heavy)                                     # the next cycle retries and clears the error
    assert gw.V1EV["error"] is None and gw.V1EV["logged"] == 1
