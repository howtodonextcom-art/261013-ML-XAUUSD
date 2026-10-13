import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "gateway"))
from xau_gateway.tick_cursor import RawTick, TickCursor  # noqa: E402


def tk(msc, bid=100.0, ask=100.1, flags=1030):
    return RawTick(msc, bid, ask, 0.0, 0, flags)


def poll(src, cur, page=None, continuation=False):
    """Simulates a source read from cur.fetch_from_msc(), optionally truncated to `page` ticks (batch limit)."""
    start = cur.fetch_from_msc(continuation)
    rows = [t for t in src if t.time_msc >= (start // 1000) * 1000]  # MT5 API granularity is seconds
    return cur.ingest(rows[:page] if page else rows, continuation)


def drain(src, cur, page):
    """What the real source loop does: keep paging with continuation while pages come back full."""
    out, cont = [], False
    while True:
        start = cur.fetch_from_msc(cont)
        rows = [t for t in src if t.time_msc >= (start // 1000) * 1000][:page]
        out += cur.ingest(rows, cont)
        if len(rows) < page:
            return out
        cont = True


def test_many_ticks_same_msc_all_captured():
    for n in (2, 10, 100):
        src = [tk(1_000_000, bid=100 + i * 0.01) for i in range(n)]
        cur = TickCursor()
        assert len(poll(src, cur)) == n
        assert poll(src, cur) == []  # repoll: no duplicates


def test_same_msc_different_bid_ask_are_distinct():
    src = [tk(5000, 1, 2), tk(5000, 1, 3), tk(5000, 2, 3)]
    cur = TickCursor()
    assert len(poll(src, cur)) == 3


def test_identical_payload_ticks_counted_by_occurrence():
    src = [tk(5000), tk(5000), tk(5000)]
    cur = TickCursor()
    assert len(poll(src, cur)) == 3
    assert poll(src, cur) == []
    src.append(tk(5000))  # a 4th identical tick appears later in the same ms
    new = poll(src, cur)
    assert len(new) == 1 and new[0].occurrence == 3


def test_batch_boundary_inside_same_ms_loses_nothing():
    src = [tk(1000 + i) for i in range(5)] + [tk(2000, 100 + i) for i in range(7)] + [tk(3000)]
    cur = TickCursor()
    got = drain(src, cur, page=8)  # page size 8 cuts the 7-tick ms group in half
    assert [e.tick for e in got] == src
    assert drain(src, cur, page=8) == []


def test_pagination_retry_is_idempotent():
    src = [tk(1000 + i) for i in range(20)]
    cur = TickCursor()
    a = poll(src, cur, page=10)
    b = cur.ingest(src[:10])  # retry of the same page
    assert len(a) == 10 and b == []


def test_restart_from_checkpoint_no_loss_no_dup():
    src = [tk(1000 + i // 3, bid=100 + i) for i in range(30)]
    cur = TickCursor()
    first = poll(src[:15], cur)
    cur2 = TickCursor.from_json(cur.to_json())  # process restart
    rest = poll(src, cur2)
    assert len(first) + len(rest) == 30
    assert [e.tick for e in first + rest] == src


def test_late_inserted_tick_in_consumed_ms_is_flagged_not_lost():
    src = [tk(1000), tk(2000), tk(3000)]
    cur = TickCursor()
    poll(src, cur)
    src.insert(1, tk(2000, bid=99.0))  # history back-filled a tick into an already consumed ms
    new = poll(src, cur)
    assert len(new) == 1 and new[0].late is True and cur.late_total == 1


def test_restart_without_checkpoint_replays_overlap_only_via_fresh_cursor():
    # A fresh cursor has no memory: documents that a checkpoint is required for exactly-once across restarts.
    src = [tk(1000), tk(2000)]
    assert len(poll(src, TickCursor())) == 2


def test_cold_start_catchup_ticks_are_not_marked_late():
    src = [tk(1000 + i) for i in range(10)]
    cur = TickCursor()
    cur.initial_from_msc = 1000
    got = poll(src, cur)
    assert len(got) == 10 and not any(e.late for e in got) and cur.late_total == 0


def test_long_polling_simulation_emits_each_tick_exactly_once():
    """Regression for the live bug: 100 ticks/s polled every 10 ms for 30 s through second-granular reads."""
    import random
    random.seed(1)
    src, cur, got = [], TickCursor(), []
    t = 1_000_000
    for step in range(3000):
        t += 10
        for _ in range(random.choice([0, 1, 1, 2, 3])):
            src.append(tk(t - random.choice([0, 0, 0, 5, 40]), bid=100 + random.random()))  # some arrive slightly out of order
        got += poll(src, cur)
    got += poll(src, cur)
    assert len(got) == len(src), (len(got), len(src))
    assert len({(e.tick, e.occurrence) for e in got}) == len(got)


def test_prune_never_drops_state_the_next_read_can_return():
    cur = TickCursor(overlap_ms=2000)
    src = [tk(10_000 + i * 100) for i in range(60)]
    poll(src, cur)
    for _ in range(5):
        assert poll(src, cur) == []
