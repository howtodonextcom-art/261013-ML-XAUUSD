import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "gateway"))
from xau_gateway.candles import CandleEngine  # noqa: E402


def T(sec, ms=0):
    return (sec * 1000) + ms


def test_ohlc_and_close_on_boundary():
    e = CandleEngine(("M1",))
    base = 1_700_000_040  # multiple of 60
    e.on_tick(T(base + 1), 10.0, 10.5)
    e.on_tick(T(base + 20), 12.0, 12.5)
    e.on_tick(T(base + 40), 9.0, 9.5)
    ev = e.on_tick(T(base + 60), 11.0, 11.5)
    kinds = [k for k, _ in ev]
    assert kinds == ["close", "update"]
    c = e.closed["M1"][0]
    assert (c.o, c.h, c.l, c.c, c.tick_volume, c.state) == (10.0, 12.0, 9.0, 9.0, 3, "CLOSED")
    assert e.open["M1"].t == base + 60 and e.open["M1"].o == 11.0


def test_no_synthetic_tick_or_bar_across_gap():
    e = CandleEngine(("M1",))
    base = 1_700_000_040
    e.on_tick(T(base + 5), 10, 10.1)
    e.on_tick(T(base + 600), 20, 20.1)  # 10 minutes of silence
    assert len(e.closed["M1"]) == 1, "missing minutes must stay missing, not be filled"
    assert e.open["M1"].o == 20  # opens at first real tick, not previous close


def test_late_tick_never_rewrites_closed_bar():
    e = CandleEngine(("M1",))
    base = 1_700_000_040
    e.on_tick(T(base + 5), 10, 10.1)
    e.on_tick(T(base + 65), 11, 11.1)
    e.on_tick(T(base + 10), 99, 99.1)  # out-of-order, older bucket
    assert e.closed["M1"][0].h == 10 and e.open["M1"].h == 11


def test_same_ms_ticks_are_all_counted():
    e = CandleEngine(("M1",))
    base = 1_700_000_040
    for _ in range(3):
        e.on_tick(T(base + 1, 500), 10, 10.1)
    assert e.open["M1"].tick_volume == 3


def test_first_bar_marked_partial_and_multi_tf_alignment():
    e = CandleEngine()
    t0 = 1_700_006_400 + 7  # inside an H1/H4-aligned region
    e.on_tick(T(t0), 5, 5.2)
    assert e.open["M1"].completeness == "PARTIAL_STARTED_MID_BAR"
    for tf, sec in {"M5": 300, "M15": 900, "H1": 3600, "H4": 14400}.items():
        assert e.open[tf].t % sec == 0


def test_bid_basis_and_spread_stats():
    e = CandleEngine(("M1",), price="bid")
    e.on_tick(T(1_700_000_041), 100.0, 100.4)
    e.on_tick(T(1_700_000_042), 100.0, 100.8)
    c = e.open["M1"]
    assert c.c == 100.0 and abs(c.spread_max - 0.8) < 1e-9


def test_tick_volume_counts_only_bid_flag_ticks_like_mt5():
    e = CandleEngine(("M1",), price="bid")
    base = 1_700_000_040
    e.on_tick(T(base + 1), 10, 10.1, flags=1030)  # bid+ask
    e.on_tick(T(base + 2), 10, 10.2, flags=1028)  # ask-only: not counted
    e.on_tick(T(base + 3), 10.1, 10.2, flags=1026)  # bid-only
    c = e.open["M1"]
    assert c.tick_volume == 2 and c.h == 10.1


def test_late_tick_inside_open_bar_updates_hl_volume_not_close():
    e = CandleEngine(("M1",), price="bid")
    base = 1_700_000_040
    e.on_tick(T(base + 10), 10.0, 10.1, 1030)
    e.on_tick(T(base + 30), 11.0, 11.1, 1030)
    e.on_tick(T(base + 20), 12.0, 12.1, 1030)  # late: older than last tick, same bar
    c = e.open["M1"]
    assert (c.o, c.h, c.l, c.c, c.tick_volume, c.late_applied) == (10.0, 12.0, 10.0, 11.0, 3, 1)


def test_late_tick_before_first_seen_tick_becomes_open():
    e = CandleEngine(("M1",), price="bid")
    base = 1_700_000_040
    e.on_tick(T(base + 10), 10.0, 10.1, 1030)
    e.on_tick(T(base + 5), 9.0, 9.1, 1030)
    c = e.open["M1"]
    assert c.o == 9.0 and c.l == 9.0 and c.c == 10.0


def test_late_tick_for_closed_bar_is_counted_not_applied():
    e = CandleEngine(("M1",), price="bid")
    base = 1_700_000_040
    e.on_tick(T(base + 10), 10.0, 10.1, 1030)
    e.on_tick(T(base + 70), 11.0, 11.1, 1030)
    e.on_tick(T(base + 20), 99.0, 99.1, 1030)
    assert e.closed["M1"][0].h == 10.0 and e.late_closed_ticks >= 1
