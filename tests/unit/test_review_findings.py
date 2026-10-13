"""Regression tests for findings of the independent review (written before the fixes)."""
import sys
import tempfile
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "gateway"))
sys.path.insert(0, str(Path(__file__).parent))
from xau_gateway import app as appmod  # noqa: E402
from xau_gateway.coverage import coverage_report  # noqa: E402
from xau_gateway.models import Tick  # noqa: E402
from xau_gateway.storage import TICK_SCHEMA, LiveTickWriter, Store  # noqa: E402
from test_p1c_repro import H, live_tick, mk_bars, mk_hist_ticks  # noqa: E402


# ---- finding 1: a pipeline exception must not kill the thread nor leave health reporting a healthy live feed -----------
def test_pipeline_exception_is_contained_counted_and_degrades_health():
    class Boom:
        tfs = {}
        history = {}
        late_closed_ticks = 0
        price = "bid"
        def on_tick(self, *a, **k):
            raise RuntimeError("boom")
    old = appmod.S.engine
    appmod.S.engine = Boom()
    try:
        appmod.S.pipeline_errors = 0
        appmod.process_tick(live_tick(H * 1000, 1))      # must not raise
        appmod.process_tick(live_tick(H * 1000 + 1, 2))
        assert appmod.S.pipeline_errors == 2 and "boom" in appmod.S.pipeline_last_error
        reasons = appmod.degraded_reasons(writer=None)
        assert any(r.startswith("PIPELINE_ERRORS") for r in reasons)
        assert appmod.connection_state({"state": "CONNECTED", "identity_verified": True}, 0.1, reasons) == "DEGRADED"
    finally:
        appmod.S.engine = old
        appmod.S.pipeline_errors = 0


def test_stalled_pipeline_heartbeat_degrades_health():
    appmod.S.pipeline_alive = time.monotonic() - 30
    try:
        assert any(r.startswith("PIPELINE_STALLED") for r in appmod.degraded_reasons(writer=None))
    finally:
        appmod.S.pipeline_alive = time.monotonic()


def test_disconnected_is_not_hidden_by_degraded():
    assert appmod.connection_state({"state": "DISCONNECTED"}, None, ["PIPELINE_STALLED"]) == "DISCONNECTED"


# ---- finding 2: writer must retry, and an unrecoverable loss must be a loud, permanent flag --------------------------
class FlakyStore(Store):
    fails = 2
    def write_chunk(self, *a, **k):
        if FlakyStore.fails > 0:
            FlakyStore.fails -= 1
            raise OSError("disk hiccup")
        return super().write_chunk(*a, **k)


def test_writer_retries_failed_flush_without_dropping_ticks():
    FlakyStore.fails = 2
    with tempfile.TemporaryDirectory() as d:
        s = FlakyStore(Path(d))
        w = LiveTickWriter(s, session_id="r", flush_s=0.1, flush_n=3, retry_base_s=0.05)
        w.start()
        for i in range(10):
            w.offer(live_tick((H + i) * 1000, i + 1))
        deadline = time.time() + 15
        while s.read_table("ticks").num_rows < 10 and time.time() < deadline:
            time.sleep(0.2)
        w.stop_ev.set(); w.join(10)
        assert s.read_table("ticks").num_rows == 10 and w.dropped == 0 and w.hole is False and w.failed_flushes >= 2


def test_writer_hole_is_flagged_when_buffer_cap_exceeded():
    class Dead(Store):
        def write_chunk(self, *a, **k):
            raise OSError("disk gone")
    with tempfile.TemporaryDirectory() as d:
        s = Dead(Path(d))
        w = LiveTickWriter(s, session_id="h", flush_s=0.05, flush_n=2, retry_base_s=0.05, max_buffer=5)
        w.start()
        for i in range(30):
            w.offer(live_tick((H + i) * 1000, i + 1))
        time.sleep(1.5)
        w.stop_ev.set(); w.join(10)
        assert w.hole is True and w.dropped > 0
        assert any(r.startswith("PERSISTENCE_HOLE") for r in appmod.degraded_reasons(writer=w))


# ---- finding 4: quarantine is scoped to its server/symbol --------------------------------------------------------------
def test_quarantine_does_not_leak_across_server_or_symbol():
    with tempfile.TemporaryDirectory() as d:
        s = Store(Path(d))
        s.quarantine("bar_m1_parity", 1000, "R", "", server="A", symbol="X")
        assert s.quarantined("bar_m1_parity", "A", "X") == {1000: "R"}
        assert s.quarantined("bar_m1_parity", "B", "X") == {}
        assert s.quarantined("bar_m1_parity", "A", "Y") == {}


# ---- finding 10: a metadata-only difference must not supersede an identical chunk ---------------------------------------
def test_metadata_only_change_is_identical_not_superseded():
    with tempfile.TemporaryDirectory() as d:
        s = Store(Path(d))
        rows = [((H + i) * 1000, 10.0 + i, 1030) for i in range(5)]
        mk_hist_ticks(s, rows)
        import xau_gateway.storage as st
        old = st.DATASET_VERSION
        st.DATASET_VERSION = "ds-other"
        try:
            n = len(rows)
            cols = {"source_id": ["mt5_hist_ticks"] * n, "terminal_ref": [""] * n, "server": ["S"] * n, "symbol": ["X"] * n,
                    "time_msc": [m for m, _, _ in rows], "bid": [b for _, b, _ in rows], "ask": [b + 0.3 for _, b, _ in rows],
                    "last": [0.0] * n, "volume": [0] * n, "flags": [f for _, _, f in rows], "received_at_ns": [0] * n,
                    "quality_flags": [""] * n, "dataset_version": ["ds-other"] * n, "capture_session_id": [""] * n, "provenance": ["HISTORY"] * n}
            r = s.write_chunk("ticks", TICK_SCHEMA, cols, source_id="mt5_hist_ticks", server="S", symbol="X", chunk=f"h{H}",
                              key_col="time_msc", partition="date=x")
        finally:
            st.DATASET_VERSION = old
        assert r["status"] == "identical" and len(s.files("ticks", True)) == 1


def test_real_content_change_still_supersedes():
    with tempfile.TemporaryDirectory() as d:
        s = Store(Path(d))
        rows = [((H + i) * 1000, 10.0 + i, 1030) for i in range(5)]
        mk_hist_ticks(s, rows)
        mk_hist_ticks(s, rows[:4])      # history now has FEWER ticks: must be a visible supersede, not hidden
        assert len(s.files("ticks", True)) == 2 and len(s.files("ticks")) == 1


# ---- finding 5: 'continuous' must mean every active minute has ticks, not just 'some tick in the hour' ---------------
def test_hour_with_one_tick_is_not_continuous():
    with tempfile.TemporaryDirectory() as d:
        s = Store(Path(d))
        mk_hist_ticks(s, [((H + 5) * 1000, 10.0, 1030)], h=H)       # one tick in the whole hour
        mk_bars(s, [(H + m * 60, 1, 1, 1, 1, 1) for m in range(60)])  # MT5 has 60 bars in that hour
        r = coverage_report(s, "S", "X", H, H + 3600)
        assert r["rows"][0]["status"] == "HIST_PARTIAL" and r["rows"][0]["minutes_without_ticks"] == 59
        assert r["continuous"] is False


def test_full_hour_is_continuous():
    with tempfile.TemporaryDirectory() as d:
        s = Store(Path(d))
        mk_hist_ticks(s, [((H + m * 60 + 1) * 1000, 10.0 + m, 1030) for m in range(60)], h=H)
        mk_bars(s, [(H + m * 60, 1, 1, 1, 1, 1) for m in range(60)])
        r = coverage_report(s, "S", "X", H, H + 3600)
        assert r["rows"][0]["status"] == "HIST_ONLY" and r["continuous"] is True
