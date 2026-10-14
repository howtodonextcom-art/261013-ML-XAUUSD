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


def test_run_exits_with_failure_code_4_on_mismatch_and_writes_no_result(tmp_path, monkeypatch):
    """End to end through run(): a fake Mode A source and a CSV whose header names ANOTHER account must give exit code 4 and no output file."""
    import queue
    import types
    f = tmp_path / "xau_modeb_XAUUSD_abcd1234.csv"
    f.write_text("#schema=1;symbol=XAUUSD;server=MetaQuotes-Demo;account_ref=deadbeef;digits=2;started_msc=1\n", encoding="ascii")
    monkeypatch.setattr(AB, "COMMON", tmp_path)
    monkeypatch.setattr(AB, "load_source_config", lambda: {"terminal_path": "C:/x/terminal64.exe", "expected": EXP})

    class FakeSrc:
        def __init__(self, *a, **k):
            self.q, self.stop_ev, self.status = queue.Queue(), types.SimpleNamespace(set=lambda: None), {"identity_verified": True, "state": "CONNECTED", "symbol": "XAUUSD", "server_utc_offset_s": 10800}

        def start(self):
            pass
    import xau_gateway.mt5_source as ms
    monkeypatch.setattr(ms, "MT5TickSource", FakeSrc)
    out = tmp_path / "res.json"
    assert AB.run(0.005, "XAUUSD", out) == 4
    assert not out.exists()


def test_missing_ea_file_is_not_tested_and_missing_account_pin_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(AB, "COMMON", tmp_path)
    monkeypatch.setattr(AB, "load_source_config", lambda: {"terminal_path": "C:/x/terminal64.exe", "expected": EXP})
    assert AB.run(0.005, "XAUUSD", tmp_path / "r.json") == 3
    monkeypatch.setattr(AB, "load_source_config", lambda: {"terminal_path": "C:/x/terminal64.exe", "expected": {"server": "MetaQuotes-Demo"}})
    assert AB.run(0.005, "XAUUSD", tmp_path / "r.json") == 2
