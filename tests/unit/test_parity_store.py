import sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "gateway"))
from xau_gateway.storage import Store, TICK_SCHEMA, BAR_SCHEMA
from xau_gateway.quality import certified_parity

H = 1_700_002_800  # multiple of 3600


def mk_ticks(store, msc_bid_flags, h=H):
    n = len(msc_bid_flags)
    cols = {"source_id": ["mt5_hist_ticks"] * n, "terminal_ref": [""] * n, "server": ["S"] * n, "symbol": ["X"] * n,
            "time_msc": [m for m, _, _ in msc_bid_flags], "bid": [b for _, b, _ in msc_bid_flags],
            "ask": [b + 0.3 for _, b, _ in msc_bid_flags], "last": [0.0] * n, "volume": [0] * n,
            "flags": [f for _, _, f in msc_bid_flags], "received_at_ns": [0] * n, "quality_flags": [""] * n,
            "dataset_version": ["t"] * n, "capture_session_id": [""] * n, "provenance": ["HISTORY"] * n}
    store.write_chunk("ticks", TICK_SCHEMA, cols, source_id="mt5_hist_ticks", server="S", symbol="X", chunk=f"h{h}", key_col="time_msc", partition="date=x")


def mk_bars(store, bars):
    n = len(bars)
    cols = {"source_id": ["mt5_hist_bars"] * n, "server": ["S"] * n, "symbol": ["X"] * n, "tf": ["M1"] * n, "time": [b[0] for b in bars],
            "open": [b[1] for b in bars], "high": [b[2] for b in bars], "low": [b[3] for b in bars], "close": [b[4] for b in bars],
            "tick_volume": [b[5] for b in bars], "spread": [30] * n, "real_volume": [0] * n, "dataset_version": ["t"] * n}
    store.write_chunk("bars_m1", BAR_SCHEMA, cols, source_id="mt5_hist_bars", server="S", symbol="X", chunk="d0", key_col="time", partition="date=x")


def ticks_for_two_minutes(extra=None):
    t = [((H + 1) * 1000, 10.0, 1030), ((H + 20) * 1000, 12.0, 1030), ((H + 30) * 1000, 12.0, 1028),
         ((H + 60 + 1) * 1000, 11.0, 1030), ((H + 60 + 5) * 1000, 9.0, 1030), ((H + 120 + 1) * 1000, 9.5, 1030)]
    return t + (extra or [])


def test_exact_closed_bars_certify():
    with tempfile.TemporaryDirectory() as d:
        s = Store(Path(d))
        mk_ticks(s, ticks_for_two_minutes())
        mk_bars(s, [(H, 10, 12, 10, 12, 2), (H + 60, 11, 11, 9, 9, 2)])  # ask-only tick not counted in volume
        r = certified_parity(s, symbol="X", server="S")
        assert r["compared"] == 2 and r["exact"] == 2 and r["status"] == "CERTIFIED"


def test_missing_ticks_in_local_data_are_detected_not_hidden():
    # regression for the 16:58 case: MT5 bar has more ticks / a lower low than the tick history can explain
    with tempfile.TemporaryDirectory() as d:
        s = Store(Path(d))
        mk_ticks(s, ticks_for_two_minutes())
        mk_bars(s, [(H, 10, 12, 10, 12, 2), (H + 60, 11, 11, 8.99, 9, 8)])
        r = certified_parity(s, symbol="X", server="S")
        assert r["status"] == "NOT_CERTIFIED" and r["mismatches"][0]["tick_volume_delta"] == 6


def test_quarantine_is_explicit_and_reported():
    with tempfile.TemporaryDirectory() as d:
        s = Store(Path(d))
        mk_ticks(s, ticks_for_two_minutes())
        mk_bars(s, [(H, 10, 12, 10, 12, 2), (H + 60, 11, 11, 8.99, 9, 8)])
        s.quarantine("bar_m1_parity", H + 60, "QUARANTINED_UNEXPLAINED_MT5_TICK_HISTORY_INCOMPLETE", "evidence", server="S", symbol="X")
        r = certified_parity(s, symbol="X", server="S")
        assert r["status"] == "CERTIFIED_WITH_QUARANTINE"
        assert any(x["reason"].startswith("QUARANTINED") for x in r["excluded"])


def test_bars_without_tick_coverage_are_excluded_with_reason():
    with tempfile.TemporaryDirectory() as d:
        s = Store(Path(d))
        mk_ticks(s, ticks_for_two_minutes())
        mk_bars(s, [(H + 7200, 1, 1, 1, 1, 1)])
        r = certified_parity(s, symbol="X", server="S")
        assert r["compared"] == 0 and r["excluded"][0]["reason"] == "NO_TICK_COVERAGE_FOR_MINUTE"


def test_store_idempotent_and_checksum_detects_corruption():
    with tempfile.TemporaryDirectory() as d:
        s = Store(Path(d))
        mk_ticks(s, ticks_for_two_minutes())
        mk_ticks(s, ticks_for_two_minutes())  # same content again
        assert len(s.files("ticks")) == 1 and s.verify() == []
        p = Path(d) / s.files("ticks")[0]["path"]
        p.write_bytes(p.read_bytes()[:-8] + b"corrupt!")
        assert any("CHECKSUM_MISMATCH" in x for x in s.verify())


def test_changed_chunk_supersedes_but_keeps_old_file():
    with tempfile.TemporaryDirectory() as d:
        s = Store(Path(d))
        mk_ticks(s, ticks_for_two_minutes())
        mk_ticks(s, ticks_for_two_minutes([((H + 40) * 1000, 10.5, 1030)]))  # history got a late tick
        assert len(s.files("ticks")) == 1 and len(s.files("ticks", True)) == 2
        assert all((Path(d) / f["path"]).exists() for f in s.files("ticks", True))
