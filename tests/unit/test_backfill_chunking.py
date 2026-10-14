import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "gateway"))
sys.path.insert(0, str(Path(__file__).parent))
from xau_gateway.chunking import CELL_S, grid_cells  # noqa: E402
from xau_gateway.integrity import duplicate_times, supersede_where  # noqa: E402
from xau_gateway.storage import BAR_SCHEMA, Store  # noqa: E402


def test_cell_ids_do_not_depend_on_the_run_start():
    end = 1_800_000_000
    a = grid_cells(end - 60 * 86400, end)
    b = grid_cells(end - 365 * 86400, end)
    ids_a, ids_b = {c for c, _, _ in a}, {c for c, _, _ in b}
    assert ids_a <= ids_b                                          # the same cell always gets the same id
    assert all(c % CELL_S == 0 for c in ids_b)
    c2 = grid_cells(end - 61 * 86400 - 12345, end - 777)           # another moment, another start
    assert {c for c, _, _ in c2} <= ids_b | {max(ids_b) + CELL_S}


def test_cells_cover_the_request_exactly_without_overlap():
    for start, end in ((1_700_000_001, 1_790_000_000), (CELL_S * 7, CELL_S * 9), (CELL_S * 7 + 5, CELL_S * 7 + 9)):
        cells = grid_cells(start, end)
        assert cells[0][1] == start and cells[-1][2] == end
        for (c1, a1, b1), (c2, a2, b2) in zip(cells, cells[1:]):
            assert b1 == a2 and c2 == c1 + CELL_S
    assert grid_cells(100, 100) == []


def mk(store, times, chunk):
    n = len(times)
    cols = {"source_id": ["mt5_hist_bars"] * n, "server": ["S"] * n, "symbol": ["X"] * n, "tf": ["M5"] * n, "time": list(times),
            "open": [1.0] * n, "high": [2.0] * n, "low": [0.5] * n, "close": [1.5] * n, "tick_volume": [1] * n, "spread": [10] * n,
            "real_volume": [0] * n, "dataset_version": ["t"] * n}
    return store.write_chunk("bars_m5", BAR_SCHEMA, cols, source_id="mt5_hist_bars", server="S", symbol="X", chunk=chunk, key_col="time", partition="date=x")


def test_overlapping_chunks_with_different_ids_are_detected_as_duplicates_and_can_be_superseded_not_deleted():
    with tempfile.TemporaryDirectory() as d:
        s = Store(Path(d))
        mk(s, range(0, 3000, 300), "M5-d0")
        mk(s, range(1500, 4500, 300), "M5-d1500")                  # a run anchored on a different start: overlaps 1500..2700
        flt = dict(source_id="mt5_hist_bars", server="S", symbol="X")
        r = duplicate_times(s, "bars_m5", **flt)
        assert r["duplicates"] == 5 and r["examples"][:2] == [1500, 1800]
        n = supersede_where(s, "bars_m5", chunk_prefix="M5-d1500", quality="TEST_MISALIGNED", **flt)
        assert n == 1 and duplicate_times(s, "bars_m5", **flt)["duplicates"] == 0
        assert len(s.files("bars_m5", True)) == 2 and all((Path(d) / f["path"]).exists() for f in s.files("bars_m5", True))   # nothing deleted
        assert s.verify() == []


def test_same_cell_id_with_more_data_supersedes_instead_of_duplicating():
    with tempfile.TemporaryDirectory() as d:
        s = Store(Path(d))
        mk(s, range(0, 1500, 300), "M5-g0")
        r = mk(s, range(0, 3000, 300), "M5-g0")                    # same cell, now longer
        assert r["status"] == "superseded_old"
        assert duplicate_times(s, "bars_m5", source_id="mt5_hist_bars", server="S", symbol="X")["duplicates"] == 0
