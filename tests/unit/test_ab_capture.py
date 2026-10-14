"""The A/B benchmark must FAIL (never pass) when the two streams are not provably the same server/account/symbol."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "benchmarks"))
sys.path.insert(0, str(ROOT / "services/gateway"))
import ab_capture as AB  # noqa: E402

EXP = {"server": "MetaQuotes-Demo", "account_ref": "abcd1234"}
H = {"symbol": "XAUUSD", "server": "MetaQuotes-Demo", "account_ref": "abcd1234"}
A_OK = {"identity_verified": True, "state": "CONNECTED", "symbol": "XAUUSD"}


def test_identity_gate_accepts_only_a_fully_verified_pair():
    assert AB.identity_gate(H, EXP, "XAUUSD", A_OK) is None


def test_identity_gate_rejects_every_kind_of_mismatch_or_missing_evidence():
    assert "pinned" in AB.identity_gate(H, {}, "XAUUSD", A_OK)
    assert "pinned" in AB.identity_gate(H, {"server": "MetaQuotes-Demo"}, "XAUUSD", A_OK)
    assert "no header" in AB.identity_gate({}, EXP, "XAUUSD", A_OK)
    assert "server" in AB.identity_gate({**H, "server": "FTMO-Demo"}, EXP, "XAUUSD", A_OK)
    assert "account" in AB.identity_gate({**H, "account_ref": "deadbeef"}, EXP, "XAUUSD", A_OK)
    assert "symbol" in AB.identity_gate({**H, "symbol": "EURUSD"}, EXP, "XAUUSD", A_OK)
    assert "Mode A did not verify" in AB.identity_gate(H, EXP, "XAUUSD", {"identity_verified": False, "state": "SOURCE_MISMATCH"})
    assert "Mode A symbol" in AB.identity_gate(H, EXP, "XAUUSD", {**A_OK, "symbol": "XAUUSD.r"})


class FakeSrc:
    """Stands in for MT5TickSource: start() launches a thread that feeds N ticks to the Mode A queue AND appends the same ticks to the EA CSV (like the real
    terminal would deliver them to both). `mode_b_ticks` lets a test make the CSV carry different ticks (an unrelated stream)."""
    csv: Path = None
    csv_ticks = None
    n = 60

    def __init__(self, *a, **k):
        import queue
        import types
        self.q = queue.Queue()
        self.stop_ev = types.SimpleNamespace(set=lambda: None)
        self.status = {"identity_verified": True, "state": "CONNECTED", "symbol": "XAUUSD", "server_utc_offset_s": 10800}

    def start(self):
        import threading
        import time
        import types

        def feed():
            time.sleep(0.4)                                                   # the benchmark has consumed the backlog by now
            base = 1_791_925_000_000
            for i in range(FakeSrc.n):
                a = types.SimpleNamespace(time_msc=base + i * 40, bid=4100.0 + i * 0.01, ask=4100.4 + i * 0.01, flags=134)
                self.q.put(a)
                b = FakeSrc.csv_ticks[i] if FakeSrc.csv_ticks else (a.time_msc, a.bid, a.ask)
                with open(FakeSrc.csv, "a", encoding="ascii") as f:
                    f.write(f"{b[0]},{b[1]:.2f},{b[2]:.2f},0.00,0,134\n")
                time.sleep(0.02)
        threading.Thread(target=feed, daemon=True).start()


def _setup(tmp_path, monkeypatch, header_ref="abcd1234", csv_ticks=None):
    import xau_gateway.mt5_source as ms
    f = tmp_path / "xau_modeb_XAUUSD_abcd1234.csv"
    f.write_text(f"#schema=1;symbol=XAUUSD;server=MetaQuotes-Demo;account_ref={header_ref};digits=2;started_msc=1\n1791924000000,4000.00,4000.40,0.00,0,134\n", encoding="ascii")
    monkeypatch.setattr(AB, "COMMON", tmp_path)
    monkeypatch.setattr(AB, "load_source_config", lambda: {"terminal_path": "C:/x/terminal64.exe", "expected": EXP})
    FakeSrc.csv, FakeSrc.csv_ticks = f, csv_ticks
    monkeypatch.setattr(ms, "MT5TickSource", FakeSrc)
    return tmp_path / "res.json"


def test_a_header_that_exists_BEFORE_the_run_is_read_and_a_wrong_account_exits_4_without_a_result(tmp_path, monkeypatch):
    """Review Level 5.1: the old code skipped the header (offset = file size), so this scenario failed for the wrong reason and a matching header could never pass."""
    out = _setup(tmp_path, monkeypatch, header_ref="deadbeef")
    assert AB.run(0.06, "XAUUSD", out) == 4
    assert not out.exists()


def test_a_matching_identical_pair_of_streams_exits_0_with_a_result_that_counts_both(tmp_path, monkeypatch):
    out = _setup(tmp_path, monkeypatch)
    assert AB.run(0.06, "XAUUSD", out) == 0
    import json
    r = json.loads(out.read_text())
    assert r["ticks"]["A"] == FakeSrc.n and r["ticks"]["B"] == FakeSrc.n and r["ticks"]["both"] == FakeSrc.n and r["ticks"]["only_A"] == 0 and r["ticks"]["only_B"] == 0
    assert r["completeness_both_over_min_stream"] == 1.0 and r["identity_mismatch_modeb"] is None and r["modeb_reader"]["gaps"] == []
    assert r["B_minus_A_receipt_ms_same_tick"]["n"] == FakeSrc.n


def test_two_unrelated_streams_are_not_comparable_and_exit_1_without_a_result(tmp_path, monkeypatch):
    unrelated = [(1_791_700_000_000 + i * 7, 3000.0 + i, 3000.4 + i) for i in range(FakeSrc.n)]       # same identity, different ticks: NOT the same market feed
    out = _setup(tmp_path, monkeypatch, csv_ticks=unrelated)
    assert AB.run(0.06, "XAUUSD", out) == 1
    assert not out.exists()


def test_missing_ea_file_is_not_tested_and_missing_account_pin_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(AB, "COMMON", tmp_path)
    monkeypatch.setattr(AB, "load_source_config", lambda: {"terminal_path": "C:/x/terminal64.exe", "expected": EXP})
    assert AB.run(0.005, "XAUUSD", tmp_path / "r.json") == 3
    monkeypatch.setattr(AB, "load_source_config", lambda: {"terminal_path": "C:/x/terminal64.exe", "expected": {"server": "MetaQuotes-Demo"}})
    assert AB.run(0.005, "XAUUSD", tmp_path / "r.json") == 2
