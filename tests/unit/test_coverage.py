import sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "gateway"))
from xau_gateway.coverage import coverage_report
from xau_gateway.storage import Store, LiveTickWriter
sys.path.insert(0, str(Path(__file__).parent))
from test_p1c_repro import mk_hist_ticks, mk_bars, live_tick, H


def hour_ticks(h, n=5, bid0=100.0):
    return [((h + i * 10) * 1000, bid0 + i, 1030) for i in range(n)]


def test_classification_of_hours():
    with tempfile.TemporaryDirectory() as d:
        s = Store(Path(d))
        mk_hist_ticks(s, hour_ticks(H), h=H)                       # hour 0: history
        mk_hist_ticks(s, hour_ticks(H + 3600), h=H + 3600)         # hour 1: history AND live (same ticks)
        w = LiveTickWriter(s, session_id="s1")
        w._flush([live_tick(m, i + 1, bid=b) for i, (m, b, _) in enumerate(hour_ticks(H + 3600))])
        # hour 2: nothing but MT5 has an M1 bar there -> unresolved; hour 3: nothing, no bars -> market break; hour 4: live only
        w2 = LiveTickWriter(s, session_id="s2")
        w2._flush([live_tick((H + 4 * 3600 + i) * 1000, i + 1) for i in range(3)])
        mk_bars(s, [(H, 1, 1, 1, 1, 1), (H + 3600, 1, 1, 1, 1, 1), (H + 7200 + 60, 1, 1, 1, 1, 1), (H + 4 * 3600, 1, 1, 1, 1, 1)])
        r = coverage_report(s, "S", "X", H, H + 5 * 3600)
        st = {x["hour"]: x["status"] for x in r["rows"]}
        assert st[H] == "HIST_ONLY" and st[H + 3600] == "BOTH_MATCH" and st[H + 7200] == "UNRESOLVED_GAP"
        assert st[H + 3 * 3600] == "MARKET_BREAK" and st[H + 4 * 3600] == "LIVE_ONLY"
        assert r["continuous"] is False and r["unresolved"] == [H + 7200]


def test_live_hist_difference_is_reported_not_hidden():
    with tempfile.TemporaryDirectory() as d:
        s = Store(Path(d))
        mk_hist_ticks(s, hour_ticks(H), h=H)
        w = LiveTickWriter(s, session_id="s1")
        t = hour_ticks(H)
        w._flush([live_tick(m, i + 1, bid=b) for i, (m, b, _) in enumerate(t[:3])] + [live_tick(t[3][0], 9, bid=999.0)])
        mk_bars(s, [(H, 1, 1, 1, 1, 1)])
        r = coverage_report(s, "S", "X", H, H + 3600)
        assert r["rows"][0]["status"] == "BOTH_DIFFER" and r["rows"][0]["only_in_live"] == 1 and r["continuous"] is False


def test_overlapping_sessions_that_saw_the_same_ticks_are_not_double_counted():
    with tempfile.TemporaryDirectory() as d:
        s = Store(Path(d))
        mk_hist_ticks(s, hour_ticks(H), h=H)
        tt = hour_ticks(H)
        LiveTickWriter(s, session_id="a")._flush([live_tick(m, i + 1, bid=b) for i, (m, b, _) in enumerate(tt[:4])])
        LiveTickWriter(s, session_id="b")._flush([live_tick(m, i + 1, bid=b) for i, (m, b, _) in enumerate(tt[2:])])  # overlaps ticks 2,3
        mk_bars(s, [(H, 1, 1, 1, 1, 1)])
        r = coverage_report(s, "S", "X", H, H + 3600)
        assert r["rows"][0]["status"] == "BOTH_MATCH", r["rows"][0]
