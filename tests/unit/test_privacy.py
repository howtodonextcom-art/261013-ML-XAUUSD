"""Review finding (critical): equity / free margin / budget / margin amounts must not be recoverable from the PUBLIC decision."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in ("services/gateway", "services/intelligence", "tests/unit"):
    sys.path.insert(0, str(ROOT / p))
from xau_gateway.intel_logic import make_decision, overlays  # noqa: E402
from xau_intel.decision.decide import GatePolicy  # noqa: E402
from xau_intel.decision.risk import RiskPolicy, plan_trade  # noqa: E402
from test_intel_logic import eligible_heavy  # noqa: E402
from test_risk import XAU  # noqa: E402


def numbers(o):
    if isinstance(o, bool) or o is None:
        return
    if isinstance(o, (int, float)):
        yield float(o)
    elif isinstance(o, dict):
        for v in o.values():
            yield from numbers(v)
    elif isinstance(o, (list, tuple)):
        for v in o:
            yield from numbers(v)


def strings(o):
    if isinstance(o, str):
        yield o
    elif isinstance(o, dict):
        for v in o.values():
            yield from strings(v)
    elif isinstance(o, (list, tuple)):
        for v in o:
            yield from strings(v)


# (equity, free margin, spread, target): clean BUY, tiny account (min lot > budget), margin shortage, wide spread, poor R:R
SCENARIOS = [(12345.678, 9876.543, 0.4, 112.0), (52.34, 51.0, 0.4, 112.0), (987654.321, 5.07, 0.4, 112.0),
             (23456.789, 22222.222, 2.0, 112.0), (31415.926, 27182.818, 0.4, 103.0)]
RPOL = RiskPolicy(risk_fraction=0.01, min_net_rr=1.5)


@pytest.mark.parametrize("equity,free,spread,target", SCENARIOS)
def test_no_private_number_appears_in_the_public_decision(equity, free, spread, target):
    h = eligible_heavy()
    h["status"]["active"]["BUY"]["impulse"]["high_price"] = target
    dec = make_decision(h, spread=spread, bid=100.0, data_age_s=1.0, spec=XAU, equity=equity, free_margin=free, risk_policy=RPOL,
                        gate_policy=GatePolicy(max_spread_atr=0.3))
    out = {"decision": dec, "overlays": overlays(dec)}
    rp = plan_trade("BUY", 100.0, 95.0, target, 4.0, spread, XAU, equity, free, RPOL)
    private = {equity, free, equity * RPOL.risk_fraction}
    # only quantities that depend on the ACCOUNT (broker constants such as value per unit or margin per lot are not secrets and may equal a price)
    private |= {float(rp.private[k]) for k in ("lot_raw", "risk_budget", "estimated_loss_at_sl", "margin_estimate") if k in rp.private}
    private = {x for x in private if x > 1.5}                    # tiny values (a lot step, 1.0) are not secrets
    nums = list(numbers(out))
    for x in private:
        for y in nums:
            assert abs(y - x) > 1e-6 * max(1.0, abs(x)), f"public number {y} equals private quantity {x}"
        for s in strings(out):
            assert f"{x:.2f}" not in s and f"{x:g}" not in s, f"private {x} in text {s!r}"
    plan = dec.get("plan") or {}
    for k in ("lot_raw", "risk_budget", "loss_per_lot", "estimated_loss_at_sl", "margin_estimate", "margin_per_lot_estimate", "value_per_price_unit_per_lot"):
        assert k not in plan, k


def test_equity_cannot_be_reconstructed_from_the_fields_the_review_used():
    """The review reconstructed equity as lot_raw * loss_distance * value_per_unit / risk_fraction: lot_raw, value_per_unit and the money keys
    are no longer public. (The rounded lot still bounds the account size approximately: documented in RISK_GOVERNANCE.md.)"""
    h = eligible_heavy()
    dec = make_decision(h, spread=0.4, bid=100.0, data_age_s=1.0, spec=XAU, equity=123456.0, free_margin=99999.0,
                        risk_policy=RiskPolicy(risk_fraction=0.01, min_net_rr=1.0), gate_policy=GatePolicy())
    p = dec["plan"]
    assert "lot_raw" not in p and "value_per_price_unit_per_lot" not in p and "loss_per_lot" not in p
    assert p["risk_fraction"] == 0.01 and "lot" not in p and p["size_hidden"] is True          # privacy mode is the default


def test_risk_reasons_are_constant_strings_independent_of_the_account():
    """Round 6: ratios in reason strings were still invertible (equity = risk_fraction-based formula). The reasons must carry NO account-derived number."""
    seen_budget, seen_margin = set(), set()
    for eq in (52.34, 100.0, 1_000.0):
        t = plan_trade("BUY", 100.0, 95.0, 112.0, 4.0, 0.4, XAU, eq, 1e9, RiskPolicy(risk_fraction=0.01, min_net_rr=1.0))
        if t.status == "BLOCKED":
            seen_budget.add(tuple(t.reasons))
    for fm in (5.07, 50.0, 500.0):
        t = plan_trade("BUY", 100.0, 95.0, 112.0, 4.0, 0.4, XAU, 987654.321, fm, RiskPolicy(risk_fraction=0.01, min_net_rr=1.0))
        if t.status == "BLOCKED":
            seen_margin.add(tuple(t.reasons))
    assert seen_budget == {("RISK_MIN_LOT_EXCEEDS_BUDGET",)} and seen_margin == {("INSUFFICIENT_MARGIN",)}


def test_a_blocked_decision_publishes_levels_but_no_lot():
    """Round 6: sweeping the spread while BLOCKED made `lot` flip at known loss distances and pinned equity; a non-eligible plan carries no size."""
    from test_intel_logic import eligible_heavy
    from xau_intel.decision.decide import GatePolicy, decide
    h = eligible_heavy()
    d = decide(h["status"], atr=h["atr"], spread=0.4, spec=XAU, equity=1e4, free_margin=1e-3, data_age_s=1.0, market_open=True, price_now_bid=100.0,
               risk_policy=RiskPolicy(risk_fraction=0.01, min_net_rr=1.0), gate_policy=GatePolicy())
    assert d["action"] == "BLOCKED" and d["plan"] and "lot" not in d["plan"] and d["plan"]["entry"] is not None
    ok = decide(h["status"], atr=h["atr"], spread=0.4, spec=XAU, equity=1e4, free_margin=9e3, data_age_s=1.0, market_open=True, price_now_bid=100.0,
                risk_policy=RiskPolicy(risk_fraction=0.01, min_net_rr=1.0), gate_policy=GatePolicy())
    assert ok["action"] in ("BUY", "SELL") and "lot" in ok["plan"]


def test_a_stale_decision_has_no_setup_levels_and_no_plan():
    from test_intel_logic import eligible_heavy
    from xau_intel.decision.decide import GatePolicy, decide
    h = eligible_heavy()
    d = decide(h["status"], atr=h["atr"], spread=0.4, spec=XAU, equity=1e4, free_margin=9e3, data_age_s=999.0, market_open=True, price_now_bid=100.0,
               risk_policy=RiskPolicy(), gate_policy=GatePolicy())
    assert d["action"] == "WAIT" and d["primary_reason"] == "DATA_STALE" and d["setup"] is None and d["plan"] is None
    assert d["next_required"]


def test_non_finite_inputs_are_not_evaluable_not_an_exception():
    for kw in ({"spread": float("nan")}, {"atr": float("nan")}, {"equity": float("nan")}, {"free": float("inf")}):
        a = dict(entry=100.0, sl=95.0, tp=112.0, atr=4.0, spread=0.4, equity=1e4, free=9e3)
        a.update(kw)
        p = plan_trade("BUY", a["entry"], a["sl"], a["tp"], a["atr"], a["spread"], XAU, a["equity"], a["free"], RiskPolicy())
        assert p.status == "RISK_NOT_EVALUABLE" and "NON_FINITE_INPUT" in p.reasons[0], kw


# ---------------------------------------------------------------- privacy mode (size hidden by default) and inference over state sequences
def _public(equity, free, spread, bid, target=112.0, reveal=False, monkeypatch=None):
    h = eligible_heavy()
    h["status"]["active"]["BUY"]["impulse"]["high_price"] = target
    d = make_decision(h, spread=spread, bid=bid, data_age_s=1.0, spec=XAU, equity=equity, free_margin=free, risk_policy=RPOL, gate_policy=GatePolicy(max_spread_atr=0.3))
    return json.dumps({"decision": d, "overlays": overlays(d)}, sort_keys=True, allow_nan=False)


def test_in_privacy_mode_the_public_decision_is_identical_for_every_affordable_account_over_a_whole_price_path():
    """The inference test the review asked for: sweep price and spread (the 'many updates' an observer sees) for accounts from 2 000 to 5 000 000 and require the
    PUBLIC output to be byte-identical. If it is, no function of it can reveal anything about the account (beyond the coarse 'affordable' fact)."""
    for i in range(60):
        bid = 100.0 + 0.07 * i                                                    # the live price drifts: every update changes the loss distance
        spread = 0.2 + 0.01 * (i % 9)
        outs = {_public(e, 0.9 * e, spread, bid) for e in (2_000.0, 7_500.0, 25_000.0, 123_456.0, 1_000_000.0, 5_000_000.0)}
        assert len(outs) == 1, f"the public decision depends on the account at update {i}"


def test_in_reveal_mode_the_lot_leaks_the_account_and_the_test_can_see_it(monkeypatch):
    """Mutation check for the test above: with XAU_REVEAL_SIZE=1 the same sweep must show account-dependent output (otherwise the invariance test is blind)."""
    monkeypatch.setenv("XAU_REVEAL_SIZE", "1")
    outs = {_public(e, 0.9 * e, 0.4, 100.0) for e in (2_000.0, 7_500.0, 25_000.0, 123_456.0)}
    assert len(outs) > 1
    d = json.loads(_public(25_000.0, 22_000.0, 0.4, 100.0))
    assert d["decision"]["plan"]["lot"] > 0 and d["decision"]["plan"]["size_hidden"] is False


def test_equity_recovered_from_exact_lots_is_precise_but_not_from_the_hidden_mode(monkeypatch):
    """Quantified: an observer intersecting [lot*L*v/rf, (lot+step)*L*v/rf) over price moves pins equity to well under 1% in reveal mode; in privacy mode it has no lot."""
    monkeypatch.setenv("XAU_REVEAL_SIZE", "1")
    E, rf, v, step = 31_415.9, 0.01, 100.0, 0.01
    lo, hi = 0.0, float("inf")
    for i in range(80):
        bid = 100.0 + 0.11 * i
        spread = 0.3
        d = json.loads(_public(E, 0.9 * E, spread, bid))["decision"]
        if d["plan"] and "lot" in d["plan"]:
            L = d["plan"]["loss_distance_with_costs"]
            lo, hi = max(lo, d["plan"]["lot"] * L * v / rf), min(hi, (d["plan"]["lot"] + step) * L * v / rf)
    assert lo <= E < hi and (hi - lo) / E < 0.01                                  # reveal mode: equity known to <1% after 80 updates
    monkeypatch.delenv("XAU_REVEAL_SIZE")
    d = json.loads(_public(E, 0.9 * E, 0.3, 100.0))["decision"]
    assert "lot" not in d["plan"]


def test_a_capped_lot_warning_does_not_leak_a_huge_account_in_privacy_mode():
    d = json.loads(_public(50_000_000.0, 45_000_000.0, 0.4, 100.0))["decision"]
    assert all(not str(w).startswith("LOT_") for w in (d.get("risk") or {}).get("warnings", []))
