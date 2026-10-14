"""Historical setup events (Level 6.3): the realtime payload keeps 12, the history API serves everything, paged, with stable ids and provenance."""
import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in ("services/gateway", "services/intelligence", "tests/unit"):
    sys.path.insert(0, str(ROOT / p))
from xau_gateway.setup_history import compact, merge, page, replay_events  # noqa: E402
import test_v1_production_path as P  # noqa: E402
from test_v1_production_path import SC, bars  # noqa: E402,F401


def raw(i, state="SETUP_FORMING", direction="BUY", known=None):
    return {"setup_id": f"M15-{direction}-{i}", "direction": direction, "setup_timeframe": "M15", "state": state, "prev_state": None, "event_time": 900 * i, "known_at": 900 * i + 900 if known is None else known,
            "reasons": ["R"], "entry_level": None, "invalidation_level": None, "policy_version": "setup-1", "expires_at": None}


def test_event_ids_are_stable_and_live_wins_a_duplicate_with_replay():
    live = [compact(raw(1), "LIVE_ENGINE")]
    rep = [compact(raw(1), "REPLAY"), compact(raw(2), "REPLAY")]
    assert live[0]["event_id"] == "M15-BUY-1|SETUP_FORMING|1800" == rep[0]["event_id"]
    m = merge(live, rep)
    assert [e["event_id"] for e in m] == ["M15-BUY-1|SETUP_FORMING|1800", "M15-BUY-2|SETUP_FORMING|2700"]
    assert m[0]["provenance"] == "LIVE_ENGINE" and m[1]["provenance"] == "REPLAY"


def test_paging_returns_every_event_exactly_once_and_never_splits_one_second():
    evs = [compact(raw(i, direction="BUY" if i % 2 else "SELL"), "REPLAY") for i in range(50)]
    evs += [compact(raw(100 + j, state="EXPIRED", known=900 * 10 + 900), "REPLAY") for j in range(4)]       # four more events with the SAME known_at as event 10
    evs = merge(evs)
    got, cursor, pages = [], None, 0
    while True:
        pg = page(evs, None, None, limit=12, cursor=cursor)
        got += pg["events"]
        pages += 1
        assert pg["total_in_range"] == 54
        if not pg["truncated"]:
            break
        cursor = pg["next_cursor"]
    assert [e["event_id"] for e in got] == [e["event_id"] for e in evs] and len(set(e["event_id"] for e in got)) == 54 and pages >= 4
    ranged = page(evs, 900 * 20, 900 * 30, limit=2000)
    assert all(900 * 20 <= e["known_at"] <= 900 * 30 for e in ranged["events"]) and not ranged["truncated"]


def test_the_limit_is_capped_to_protect_the_server():
    evs = [compact(raw(i), "REPLAY") for i in range(3000)]
    assert page(evs, None, None, limit=10 ** 9)["returned"] == 2000


def test_the_api_serves_the_full_engine_history_that_the_realtime_payload_cannot_carry(monkeypatch):
    from xau_gateway import app as appmod
    live = [compact(raw(i, direction="BUY" if i % 3 else "SELL", state="CONFIRMED" if i % 5 == 0 else "SETUP_FORMING"), "LIVE_ENGINE") for i in range(50)]
    monkeypatch.setitem(appmod.INTEL, "heavy", {"setup_events_all": live, "setup_events": live[-12:], "setup_events_total": 50})
    body = json.loads(appmod.api_setup_events(frm=None, to=None, limit=500, cursor=None, replay=0).body)
    assert body["total_events"] == 50 and body["returned"] == 50 and body["live_engine_events"] == 50 and not body["truncated"] and body["execution_authorized"] is False
    assert all(e["provenance"] == "LIVE_ENGINE" for e in body["events"]) and len({e["event_id"] for e in body["events"]}) == 50
    assert body["returned"] - 12 == 38                                                        # the 38 events a 12-event payload would have lost
    first = json.loads(appmod.api_setup_events(frm=None, to=None, limit=20, cursor=None, replay=0).body)
    second = json.loads(appmod.api_setup_events(frm=None, to=None, limit=20, cursor=first["next_cursor"], replay=0).body)
    assert first["truncated"] and len(first["events"]) + len(second["events"]) <= 50 and first["events"][-1]["known_at"] < second["events"][0]["known_at"]


def test_the_production_path_keeps_every_backend_event_and_the_realtime_payload_is_its_newest_12(bars):
    from xau_gateway.intel_logic import compute_heavy
    now = SC["SELL_PUBLISHED"]["now"] + 40 * 86400                                          # a moment with a long history behind it
    now = min(now, int(bars["M15"]["time"][-1]))
    heavy = compute_heavy(bars, now)
    allev = heavy["setup_events_all"]
    assert len(allev) > 12 and heavy["setup_events_total"] == len(allev)
    assert [e["event_id"] for e in heavy["setup_events"]] == [e["event_id"] for e in allev[-12:]]
    assert len({e["event_id"] for e in allev}) == len(allev) and all(e["provenance"] == "LIVE_ENGINE" for e in allev)
    assert len(allev) - len(heavy["setup_events"]) > 0                                       # events the cap used to drop from the chart


def test_the_replay_is_causal_events_known_at_t_do_not_change_when_later_bars_arrive(bars):
    t1 = int(bars["M15"]["time"][9000])
    cut = lambda b, t: {tf: {k: v[x["time"] + {"M15": 900, "H1": 3600, "H4": 14400}[tf] <= t] for k, v in x.items()} for tf, x in b.items()}   # noqa: E731
    early = replay_events(cut(bars, t1))["events"]
    late = replay_events(cut(bars, t1 + 30 * 86400))["events"]
    ids_early = {e["event_id"] for e in early}
    ids_late_before = {e["event_id"] for e in late if e["known_at"] <= t1}
    assert ids_early == ids_late_before and len(ids_early) > 20                              # the same events, at the same known_at, whatever arrived later
    corrupted = {tf: {k: np.where(x["time"] + {"M15": 900, "H1": 3600, "H4": 14400}[tf] > t1, 9999.0, v) if k != "time" else v for k, v in x.items()} for tf, x in bars.items()}
    cor = replay_events({tf: {k: v[x["time"] + {"M15": 900, "H1": 3600, "H4": 14400}[tf] <= t1 + 5 * 86400] for k, v in x.items()} for tf, x in corrupted.items()})["events"]
    assert {e["event_id"] for e in cor if e["known_at"] <= t1} == ids_early                  # future prices (corrupted) cannot change the past


def test_one_consistent_timeline_live_is_authoritative_inside_its_window_and_replay_only_fills_before_it():
    from xau_gateway.setup_history import compose
    live = [compact(raw(i), "LIVE_ENGINE") for i in range(10, 15)]
    replay = [compact(raw(i), "REPLAY") for i in range(0, 14)] + [compact(raw(12, state="EXPIRED", direction="SELL"), "REPLAY")]     # overlaps the live window and DISAGREES with it (a different setup)
    ev, rep = compose(live, replay)
    assert rep["live_window_start"] == live[0]["known_at"] and rep["replay_events_used"] == 10 and rep["replay_events_superseded_by_live"] == 5
    assert [e["provenance"] for e in ev].count("LIVE_ENGINE") == 5 and all(e["known_at"] < live[0]["known_at"] for e in ev if e["provenance"] == "REPLAY")
    assert len({e["event_id"] for e in ev}) == len(ev) == 15 and not any(e["event_id"].startswith("M15-SELL-12") for e in ev)   # the disagreeing replay setup inside the live window is not shown
    assert compose([], replay)[0] == merge(replay) and compose([], replay)[1]["live_window_start"] is None
