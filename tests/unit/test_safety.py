"""Safety tests: no order-sending path may exist in the shipped sources."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN_PY = re.compile(r"order_send|order_check|OrderSend|positions_get\s*\(.*close|mt5\.Buy|mt5\.Sell|TRADE_ACTION")
FORBIDDEN_MQL = re.compile(r"OrderSend|CTrade|PositionOpen|trade\.Buy|trade\.Sell|TRADE_ACTION")


def test_no_order_functions_in_python():
    for p in (ROOT / "services").rglob("*.py"):
        assert not FORBIDDEN_PY.search(p.read_text(encoding="utf-8")), p


def test_no_order_functions_in_mql5():
    for p in (ROOT / "mt5").rglob("*.mq*"):
        code = re.sub(r"//.*", "", p.read_text(encoding="utf-8", errors="ignore"))
        assert not FORBIDDEN_MQL.search(code), p


def test_default_bind_is_loopback():
    run = ROOT / "scripts" / "windows" / "run_gateway.ps1"
    assert run.exists() and "127.0.0.1" in run.read_text(encoding="utf-8")
    assert "0.0.0.0" not in run.read_text(encoding="utf-8")


def test_no_secrets_in_repo():
    for p in list((ROOT / "services").rglob("*.py")) + list((ROOT / "scripts").rglob("*")):
        if p.is_file():
            assert not re.search(r"password\s*=\s*['\"]\w+", p.read_text(encoding="utf-8", errors="ignore"), re.I), p
