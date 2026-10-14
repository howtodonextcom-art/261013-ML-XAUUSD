import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "intelligence"))
from xau_intel.decision.risk import EXECUTION_AUTHORIZED, RiskPolicy, SymbolSpec, floor_to_step, plan_trade, value_per_unit  # noqa: E402

# the real MetaQuotes-Demo XAUUSD values measured with scripts/windows/probe_symbol_spec.py
XAU = SymbolSpec("XAUUSD", tick_size=0.01, tick_value=0.1, contract_size=100.0, volume_min=0.01, volume_max=100.0, volume_step=0.01,
                 point=0.01, leverage=100.0, stops_level_points=0, value_per_price_unit_per_lot=100.0, margin_per_lot=4159.68,
                 margin_reference_price=4159.68)
POL = RiskPolicy(risk_fraction=0.01, min_net_rr=1.5)


def buy(entry=4100.0, sl=4095.0, tp=4112.0, atr=4.0, spread=0.4, equity=10_000.0, free=9_000.0, spec=XAU, pol=POL, **kw):
    return plan_trade("BUY", entry, sl, tp, atr, spread, spec, equity, free, pol, **kw)


def test_execution_is_never_authorised():
    assert EXECUTION_AUTHORIZED is False
    assert buy().execution_authorized is False


def test_lot_sizing_uses_real_value_per_unit_not_the_inconsistent_tick_value():
    p = buy()
    d = p.plan
    assert p.status == "OK"
    # loss distance = 5.00 stop + 0.4 spread + 0.2 slippage = 5.6; per lot 5.6*100 = 560; budget 100 => 0.178 lot -> 0.17
    assert d["loss_distance_with_costs"] == pytest.approx(5.6) and d["value_per_price_unit_per_lot"] == 100.0
    assert d["lot"] == pytest.approx(0.17) and d["estimated_loss_at_sl"] <= d["risk_budget"] + 1e-9
    assert any("DISAGREE" in w for w in p.warnings)               # tick value (0.1/0.01 = 10) vs 100: reported, larger value used


def test_value_per_unit_conservative_and_flags_missing_mt5_calc():
    v, w = value_per_unit(XAU)
    assert v == 100.0 and any("DISAGREE" in x for x in w)
    nocalc = SymbolSpec("X", 0.01, 1.0, 100.0, 0.01, 100, 0.01)    # tick value consistent with the contract size
    v2, w2 = value_per_unit(nocalc)
    assert v2 == 100.0 and "VALUE_PER_UNIT_NOT_FROM_MT5_CALC" in w2 and not any("DISAGREE" in x for x in w2)
    assert value_per_unit(SymbolSpec("X", 0, 0, 0, 0.01, 1, 0.01))[0] is None


def test_lot_is_rounded_down_to_the_step_never_up():
    assert floor_to_step(0.1799, 0.01, 0.01) == 0.17 and floor_to_step(0.18, 0.01, 0.01) == 0.18 and floor_to_step(0.0099, 0.01, 0.01) == 0.0
    big = buy(equity=10_000_000.0, free=1e12)
    assert big.plan["lot"] == 100.0 and "LOT_CAPPED_AT_VOLUME_MAX" in big.warnings


def test_minimum_lot_above_the_risk_budget_is_blocked():
    p = buy(equity=500.0, free=500.0)                              # budget 5; one min lot would lose 5.6
    assert p.status == "BLOCKED" and any("RISK_MIN_LOT_EXCEEDS_BUDGET" in r for r in p.reasons)


def test_invalid_stop_and_target_are_rejected_before_any_lot_is_computed():
    p = buy(sl=4101.0)                                             # stop above the entry for a BUY
    assert p.status == "BLOCKED" and p.reasons[0].startswith("INVALID_SL") and "lot" not in p.plan
    assert buy(tp=4099.0).reasons[0].startswith("INVALID_TP")
    s = plan_trade("SELL", 4100.0, 4095.0, 4112.0, 4.0, 0.4, XAU, 10_000.0, 9_000.0, POL)    # SELL needs stop above and target below
    assert s.status == "BLOCKED" and s.reasons[0].startswith("INVALID_SL")


def test_insufficient_margin_blocks():
    p = buy(free=100.0)
    assert p.status == "BLOCKED" and any("INSUFFICIENT_MARGIN" in r for r in p.reasons)


def test_missing_data_is_not_evaluable_never_eligible():
    for kw in ({"spec": None}, {"equity": None}, {"free": None}, {"spread": None}, {"atr": None}):
        p = buy(**kw)
        assert p.status == "RISK_NOT_EVALUABLE" and p.plan == {} and p.reasons, kw
    assert buy(equity=0.0).status == "RISK_NOT_EVALUABLE" and buy(equity=-5.0).status == "RISK_NOT_EVALUABLE"


def test_net_rr_includes_spread_slippage_and_commission_and_gates_low_rr():
    p = buy(tp=4106.0)                                             # gross 1.2 < 1.5
    assert p.status == "BLOCKED" and any("RR_TOO_LOW" in r for r in p.reasons)
    good = buy()
    assert good.plan["gross_rr"] == pytest.approx(12.0 / 5.0)                              # 2.4: costs ignored
    assert good.plan["net_rr"] == pytest.approx((12.0 - 0.4 - 0.2) / (5.0 + 0.4 + 0.2))   # 11.4 / 5.6 = 2.036: spread and slippage on both sides of the ratio
    pc = buy(pol=RiskPolicy(risk_fraction=0.01, min_net_rr=0.1, commission_per_lot=7.0))
    assert pc.plan["net_rr"] < buy(pol=RiskPolicy(risk_fraction=0.01, min_net_rr=0.1)).plan["net_rr"]
    assert "COMMISSION_NOT_CONFIGURED(0 assumed)" in good.warnings and "COMMISSION_NOT_CONFIGURED(0 assumed)" not in pc.warnings


def test_sell_is_the_mirror_of_buy_in_distances_and_lot():
    b = buy()
    sm = plan_trade("SELL", 4100.0, 4105.0, 4088.0, 4.0, 0.4, XAU, 10_000.0, 9_000.0, POL)                                      # a real SELL at the mirrored distances
    assert sm.status == "OK" and sm.plan["lot"] == b.plan["lot"]
    assert sm.plan["loss_distance_with_costs"] == pytest.approx(b.plan["loss_distance_with_costs"])
    assert sm.plan["net_rr"] == pytest.approx(b.plan["net_rr"]) and sm.plan["gross_rr"] == pytest.approx(b.plan["gross_rr"])
    assert sm.plan["tp2_reference"] < sm.plan["entry"] and b.plan["tp2_reference"] > b.plan["entry"]


def test_broker_minimum_stop_distance():
    spec = SymbolSpec("XAUUSD", 0.01, 0.1, 100.0, 0.01, 100.0, 0.01, 0.01, 100.0, 600, 100.0, 4159.68, 4159.68)   # stops level 600 points = 6.00
    p = buy(spec=spec)                                            # stop distance 5.00 < 6.00
    assert p.status == "BLOCKED" and any("SL_TOO_CLOSE" in r for r in p.reasons)


def test_margin_estimate_scales_with_price_and_falls_back_with_a_warning():
    p = buy()
    assert p.plan["margin_per_lot_estimate"] == pytest.approx(4159.68 * 4100.0 / 4159.68)
    nomargin = SymbolSpec("XAUUSD", 0.01, 0.1, 100.0, 0.01, 100.0, 0.01, 0.01, 100.0, 0, 100.0)
    q = buy(spec=nomargin)
    assert "MARGIN_ESTIMATED_FROM_CONTRACT_AND_LEVERAGE" in q.warnings and q.plan["margin_per_lot_estimate"] == pytest.approx(100.0 * 4100.0 / 100.0)
