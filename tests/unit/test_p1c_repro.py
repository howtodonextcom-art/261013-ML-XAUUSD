"""P1C: tests reproducing the audit risks A-K (written BEFORE the fixes; each must fail on the old code)."""
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "gateway"))
from xau_gateway.models import Tick  # noqa: E402
from xau_gateway.quality import certified_parity, quality_report  # noqa: E402
from xau_gateway.storage import BAR_SCHEMA, TICK_SCHEMA, LiveTickWriter, Store  # noqa: E402
from xau_gateway.tick_cursor import RawTick, TickCursor  # noqa: E402

H = 1_700_002_800


def live_tick(msc, seq, bid=100.0, server="S", symbol="X"):
    return Tick("mt5_py_poll", server, symbol, msc, bid, bid + 0.3, 0.0, 0, 1030, seq, 0, ())


def write_session(store, session, ticks):
    w = LiveTickWriter(store, session_id=session)
    w._flush(ticks)
    return w


# ---- A: chunk identity after restart (bridge_seq resets) --------------------------------------------------------
def test_A_restart_with_reset_bridge_seq_does_not_supersede_earlier_session():
    with tempfile.TemporaryDirectory() as d:
        s = Store(Path(d))
        write_session(s, "sess-1", [live_tick((H + i) * 1000, i + 1) for i in range(5)])
        write_session(s, "sess-2", [live_tick((H + 100 + i) * 1000, i + 1) for i in range(5)])  # seq restarts at 1
        files = s.files("ticks")
        assert len(files) == 2 and sum(f["rows"] for f in files) == 10
        assert s.read_table("ticks").num_rows == 10


# ---- C/D: reads must be isolated by source/server/symbol -------------------------------------------------------
def test_CD_read_table_filters_by_source_server_symbol_and_session():
    with tempfile.TemporaryDirectory() as d:
        s = Store(Path(d))
        write_session(s, "a", [live_tick(H * 1000 + i, i + 1, server="S1", symbol="X") for i in range(3)])
        write_session(s, "b", [live_tick(H * 1000 + i, i + 1, server="S2", symbol="X") for i in range(4)])
        write_session(s, "c", [live_tick(H * 1000 + i, i + 1, server="S1", symbol="Y") for i in range(5)])
        assert s.read_table("ticks", server="S1", symbol="X").num_rows == 3
        assert s.read_table("ticks", server="S2").num_rows == 4
        assert s.read_table("ticks", symbol="Y").num_rows == 5
        assert s.read_table("ticks", session="b").num_rows == 4
        assert s.read_table("ticks", source_id="mt5_hist_ticks").num_rows == 0


def mk_hist_ticks(store, rows, server="S", symbol="X", h=H, source="mt5_hist_ticks"):
    n = len(rows)
    cols = {"source_id": [source] * n, "terminal_ref": [""] * n, "server": [server] * n, "symbol": [symbol] * n,
            "time_msc": [m for m, _, _ in rows], "bid": [b for _, b, _ in rows], "ask": [b + 0.3 for _, b, _ in rows],
            "last": [0.0] * n, "volume": [0] * n, "flags": [f for _, _, f in rows], "received_at_ns": [0] * n,
            "quality_flags": [""] * n, "dataset_version": ["t"] * n, "capture_session_id": [""] * n, "provenance": ["HISTORY"] * n}
    store.write_chunk("ticks", TICK_SCHEMA, cols, source_id=source, server=server, symbol=symbol, chunk=f"h{h}",
                      key_col="time_msc", partition="date=x")


def mk_bars(store, bars, server="S", symbol="X", source="mt5_hist_bars"):
    n = len(bars)
    cols = {"source_id": [source] * n, "server": [server] * n, "symbol": [symbol] * n, "tf": ["M1"] * n,
            "time": [b[0] for b in bars], "open": [b[1] for b in bars], "high": [b[2] for b in bars],
            "low": [b[3] for b in bars], "close": [b[4] for b in bars], "tick_volume": [b[5] for b in bars],
            "spread": [30] * n, "real_volume": [0] * n, "dataset_version": ["t"] * n}
    store.write_chunk("bars_m1", BAR_SCHEMA, cols, source_id=source, server=server, symbol=symbol, chunk=f"d{server}{symbol}",
                      key_col="time", partition="date=x")


TICKS = [((H + 1) * 1000, 10.0, 1030), ((H + 20) * 1000, 12.0, 1030), ((H + 61) * 1000, 11.0, 1030), ((H + 65) * 1000, 9.0, 1030),
         ((H + 121) * 1000, 9.5, 1030)]


def test_D_parity_ignores_live_ticks_and_other_servers():
    with tempfile.TemporaryDirectory() as d:
        s = Store(Path(d))
        mk_hist_ticks(s, TICKS)
        write_session(s, "live", [live_tick((H + 30) * 1000, 1, bid=500.0)])  # would corrupt bar H if mixed in
        mk_hist_ticks(s, [((H + 2) * 1000, 999.0, 1030)], server="OTHER", h=H + 7)  # other broker, same hour id style
        mk_bars(s, [(H, 10, 12, 10, 12, 2), (H + 60, 11, 11, 9, 9, 2)])
        r = certified_parity(s, symbol="X", server="S")
        assert r["status"] == "CERTIFIED" and r["compared"] == 2, r


# ---- E: covered minute with an MT5 bar but no local ticks must be a mismatch, not an exclusion ----------------------
def test_E_covered_minute_without_local_ticks_is_mismatch_not_excluded():
    with tempfile.TemporaryDirectory() as d:
        s = Store(Path(d))
        mk_hist_ticks(s, TICKS)  # chunk covers the whole hour but has no ticks in minute H+1800
        mk_bars(s, [(H, 10, 12, 10, 12, 2), (H + 1800, 5, 5, 5, 5, 40), (H + 3540, 1, 1, 1, 1, 1)])
        r = certified_parity(s, symbol="X", server="S")
        bad = [m for m in r["mismatches"] if m["time"] == H + 1800]
        assert bad and r["status"] == "NOT_CERTIFIED"


# ---- J: tick size must come from symbol metadata, not 0.01 -----------------------------------------------------------
def test_J_tick_size_check_uses_symbol_metadata():
    with tempfile.TemporaryDirectory() as d:
        s = Store(Path(d))
        mk_hist_ticks(s, TICKS)
        mk_bars(s, [(H, 10.005, 12.005, 10.005, 12.005, 2)])  # valid on a 0.005 tick-size instrument
        s.set_meta("symbol:X:tick_size", "0.005")
        q = quality_report(s, symbol="X", server="S")
        assert q["tick_size_check_ok"] is True and q["tick_size"] == 0.005
        s2 = Store(Path(d) / "nometa")
        mk_hist_ticks(s2, TICKS)
        mk_bars(s2, [(H, 10, 12, 10, 12, 2)])
        assert quality_report(s2, symbol="X", server="S")["tick_size_check_ok"] == "UNKNOWN_NO_SYMBOL_METADATA"


# ---- B: restart recovery from persisted watermark (checkpoint may be ahead of persisted data) -----------------------
def test_B_restart_recovers_ticks_consumed_but_not_persisted():
    """Simulates: ticks 0..99 consumed by the cursor; only 0..59 flushed to disk; process dies; restart.
    A checkpoint-driven restart would skip 60..99 forever. A store-driven restart must re-read them without duplicating 0..59."""
    src = [RawTick(1_000_000 + i * 10, 100 + i, 100.3 + i, 0.0, 0, 1030) for i in range(100)]
    c1 = TickCursor()
    c1.ingest(src)  # consumed all 100 (checkpoint would say watermark=src[-1])
    with tempfile.TemporaryDirectory() as d:
        s = Store(Path(d))
        write_session(s, "s1", [live_tick(t.time_msc, i + 1, bid=t.bid) for i, t in enumerate(src[:60])])
        c2 = s.restore_cursor(source_id="mt5_py_poll", server="S", symbol="X", overlap_ms=2000)
        got = c2.ingest([t for t in src if t.time_msc >= (c2.fetch_from_msc() // 1000) * 1000])
        persisted = s.read_table("ticks", symbol="X").num_rows
        assert persisted + len(got) == 100, (persisted, len(got))
        assert {e.tick.time_msc for e in got} == {t.time_msc for t in src[60:]}


def test_B_restore_cursor_on_empty_store_starts_cold():
    with tempfile.TemporaryDirectory() as d:
        c = Store(Path(d)).restore_cursor(source_id="mt5_py_poll", server="S", symbol="X", overlap_ms=2000)
        assert c.watermark_msc == 0
