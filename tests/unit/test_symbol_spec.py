import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "gateway"))
sys.path.insert(0, str(ROOT / "services" / "intelligence"))
from xau_gateway.storage import Store  # noqa: E402
from xau_gateway.symbol_spec import account_snapshot, load_spec, save_spec, spec_from_mt5, to_symbol_spec  # noqa: E402
from xau_intel.decision.risk import plan_trade, value_per_unit  # noqa: E402


class FakeMt5:
    ORDER_TYPE_BUY = 0

    def __init__(self, calc=100.0, margin=4159.68, info=True):
        self._calc, self._margin, self._info = calc, margin, info

    def symbol_info(self, s):
        return SimpleNamespace(trade_tick_size=0.01, trade_tick_value=0.1, trade_contract_size=100.0, volume_min=0.01, volume_max=100.0,
                               volume_step=0.01, point=0.01, trade_stops_level=0) if self._info else None

    def symbol_info_tick(self, s):
        return SimpleNamespace(ask=4159.68, bid=4159.30)

    def account_info(self):
        return SimpleNamespace(leverage=100, currency="USD", equity=12_345.0, margin_free=9_999.0, login=123456)

    def order_calc_profit(self, *a):
        return self._calc

    def order_calc_margin(self, *a):
        return self._margin


def test_spec_uses_mt5_own_calculation_and_roundtrips_through_the_store():
    d = spec_from_mt5(FakeMt5(), "XAUUSD")
    assert d["value_per_price_unit_per_lot"] == 100.0 and d["margin_per_lot"] == 4159.68 and d["tick_value"] == 0.1 and d["leverage"] == 100.0
    with tempfile.TemporaryDirectory() as tmp:
        s = Store(Path(tmp))
        save_spec(s, d)
        again = load_spec(s, "XAUUSD")
    assert again == d
    spec = to_symbol_spec(again)
    v, warnings = value_per_unit(spec)
    assert v == 100.0 and any("DISAGREE" in w for w in warnings)               # the inconsistent broker tick value is detected from the snapshot
    p = plan_trade("BUY", 4100.0, 4095.0, 4112.0, 4.0, 0.4, spec, 10_000.0, 9_000.0)
    assert p.status == "OK" and p.plan["value_per_price_unit_per_lot"] == 100.0


def test_missing_symbol_info_returns_none_and_account_data_is_not_persisted():
    assert spec_from_mt5(FakeMt5(info=False), "XAUUSD") is None
    acc = account_snapshot(FakeMt5())
    assert acc == {"equity": 12_345.0, "free_margin": 9_999.0}
    d = spec_from_mt5(FakeMt5(), "XAUUSD")
    assert "equity" not in d and "login" not in d and "free_margin" not in d and "balance" not in d


def test_zero_calc_results_become_none_not_zero():
    d = spec_from_mt5(FakeMt5(calc=0.0, margin=0.0), "XAUUSD")
    assert d["value_per_price_unit_per_lot"] is None and d["margin_per_lot"] is None
