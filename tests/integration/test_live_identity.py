"""Integration tests against the real MetaQuotes-Demo terminal. Skipped automatically when MT5 is unavailable. Read-only."""
import json, sys, time, queue
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "gateway"))
CFG = ROOT / "configs" / "source.json"
pytestmark = pytest.mark.skipif(not CFG.exists(), reason="configs/source.json missing")


def run_source(expected, seconds=6):
    from xau_gateway.mt5_source import MT5TickSource
    cfg = json.loads(CFG.read_text())
    src = MT5TickSource(cfg["terminal_path"], "XAUUSD", expected)
    src.start(); time.sleep(seconds); src.stop_ev.set(); src.join(5)
    return src


def test_wrong_server_gives_source_mismatch_and_collects_nothing():
    src = run_source({"server": "FTMO-Server-NOT-THIS-ONE"})
    assert src.status["state"] == "SOURCE_MISMATCH" and src.q.qsize() == 0 and src.seq == 0


def test_wrong_account_ref_gives_source_mismatch():
    cfg = json.loads(CFG.read_text())
    src = run_source({"server": cfg["expected"]["server"], "account_ref": "deadbeef"})
    assert src.status["state"] == "SOURCE_MISMATCH" and src.seq == 0


def test_correct_identity_connects_and_receives_ticks_without_logging_account():
    cfg = json.loads(CFG.read_text())
    src = run_source(cfg["expected"], 8)
    assert src.status["identity_verified"] and src.status["server"] == cfg["expected"]["server"]
    assert src.seq > 0
    assert "login" not in json.dumps(src.status).lower()


def test_mt5_module_never_exposes_order_calls_to_source():
    import xau_gateway.mt5_source as m
    src = Path(m.__file__).read_text()
    assert "order_" not in src
