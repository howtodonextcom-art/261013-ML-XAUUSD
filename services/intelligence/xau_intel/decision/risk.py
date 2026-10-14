"""Risk planning for a PAPER decision (policy `risk-1`). Pure arithmetic, no MT5, no orders. `execution_authorized` is ALWAYS False.

Price convention: every level is on the BID chart (the bars are Bid). Executions pay the spread:
  loss distance   = |entry - invalidation| + spread + slippage (+ commission converted to price distance)
  reward distance = |target - entry| - spread - slippage (- commission distance)
for BUY and SELL alike (a stop/target is a structural event on the bid chart; the ask side adds the spread). Gross R:R ignores costs.

Value per price unit per lot comes from MT5's own calculation (order_calc_profit for 1 lot and a 1.00 move) when available, else from
the contract size. The broker's tick value is only a cross-check: on MetaQuotes-Demo XAUUSD it says 10 USD per 1.00 per lot while
MT5's own calculation and the contract size say 100. When sources disagree the LARGER loss per lot is used for sizing (smaller lot,
conservative) and a warning is recorded.

Missing data never produces an eligible plan: no spec / equity / free margin / valid stop => RISK_NOT_EVALUABLE.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

RISK_VERSION = "risk-1"
EXECUTION_AUTHORIZED = False     # constant by design: this release cannot authorise execution


@dataclass(frozen=True)
class SymbolSpec:
    symbol: str
    tick_size: float
    tick_value: float                         # broker-reported; cross-check only
    contract_size: float
    volume_min: float
    volume_max: float
    volume_step: float
    point: float = 0.01
    leverage: float = 100.0
    stops_level_points: int = 0
    value_per_price_unit_per_lot: float | None = None   # MT5 order_calc_profit(1 lot, +1.00): authoritative when present
    margin_per_lot: float | None = None                 # MT5 order_calc_margin(1 lot) at margin_reference_price
    margin_reference_price: float | None = None
    currency: str = "USD"


@dataclass(frozen=True)
class RiskPolicy:
    version: str = RISK_VERSION
    risk_fraction: float = 0.005          # fraction of equity risked per paper trade (research default, configurable)
    min_net_rr: float = 1.5               # net of spread/slippage/commission
    slippage_spread_mult: float = 0.5     # slippage allowance per side = this x spread
    commission_per_lot: float = 0.0       # round-turn, account currency; 0 means "none known" (reported)
    tp2_rr_reference: float = 2.0         # reference target only (never an exit rule)


PRIVATE_KEYS = ("lot_raw", "risk_budget", "loss_per_lot", "estimated_loss_at_sl", "margin_estimate", "margin_per_lot_estimate",
                "value_per_price_unit_per_lot")


@dataclass
class RiskPlan:
    status: str                           # OK | BLOCKED | RISK_NOT_EVALUABLE
    reasons: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    plan: dict = field(default_factory=dict)      # FULL plan: internal use only (shadow / backtest)
    execution_authorized: bool = False

    @property
    def private(self) -> dict:
        """The quantities that reveal the account size (never published)."""
        return {k: self.plan[k] for k in PRIVATE_KEYS if k in self.plan}

    def public_plan(self) -> dict:
        """What may leave the process: no budget, no loss/margin amounts, no unrounded lot, no value per unit. NOTE: the rounded `lot` together
        with `risk_fraction` and the public contract size still bounds the account size to within the lot-step rounding (documented)."""
        return {k: v for k, v in self.plan.items() if k not in PRIVATE_KEYS}


def value_per_unit(spec: SymbolSpec) -> tuple[float | None, list[str]]:
    """(value per 1.00 price move per lot, warnings). Conservative when sources disagree."""
    w = []
    cands = {}
    if spec.value_per_price_unit_per_lot:
        cands["order_calc_profit"] = float(spec.value_per_price_unit_per_lot)
    if spec.contract_size:
        cands["contract_size"] = float(spec.contract_size)
    if spec.tick_size and spec.tick_value:
        cands["tick_value"] = float(spec.tick_value) / float(spec.tick_size)
    if not cands:
        return None, ["NO_VALUE_PER_UNIT_SOURCE"]
    hi, lo = max(cands.values()), min(cands.values())
    if lo > 0 and hi / lo > 1.01:
        w.append("VALUE_PER_UNIT_SOURCES_DISAGREE " + ", ".join(f"{k}={v:g}" for k, v in sorted(cands.items())) + f": using the larger ({hi:g}) for sizing")
    if "order_calc_profit" not in cands:
        w.append("VALUE_PER_UNIT_NOT_FROM_MT5_CALC")
    return hi, w


def floor_to_step(x: float, step: float, lo: float) -> float:
    """Round DOWN to the volume step (never up: that would exceed the risk budget), tolerant of float noise."""
    if step <= 0:
        return x
    k = math.floor(x / step + 1e-9)
    return round(max(k, 0) * step, 8)


def plan_trade(direction: str, entry: float, invalidation: float, target: float, atr: float | None, spread: float | None,
               spec: SymbolSpec | None, equity: float | None, free_margin: float | None, policy: RiskPolicy = RiskPolicy(),
               entry_price_for_margin: float | None = None) -> RiskPlan:
    """All prices on the bid chart. direction BUY/SELL. Returns a RiskPlan; only status OK may feed an eligible decision."""
    p = RiskPlan("OK")
    nums = {"entry": entry, "invalidation": invalidation, "target": target, "atr": atr, "spread": spread, "equity": equity, "free_margin": free_margin}
    bad = [k for k, v in nums.items() if v is not None and not (isinstance(v, (int, float)) and math.isfinite(v))]
    if bad:
        p.status, p.reasons = "RISK_NOT_EVALUABLE", ["NON_FINITE_INPUT:" + ",".join(sorted(bad))]
        return p
    missing = [n for n, v in (("symbol_spec", spec), ("equity", equity), ("free_margin", free_margin), ("spread", spread), ("atr", atr)) if v is None]
    if missing or (equity is not None and equity <= 0):
        p.status, p.reasons = "RISK_NOT_EVALUABLE", [f"MISSING:{m}" for m in missing] + (["EQUITY_NOT_POSITIVE"] if equity is not None and equity <= 0 else [])
        return p
    if direction not in ("BUY", "SELL"):
        p.status, p.reasons = "RISK_NOT_EVALUABLE", ["BAD_DIRECTION"]
        return p
    sign = 1 if direction == "BUY" else -1
    # structural validity: the invalidation must be on the losing side of the entry, the target on the winning side
    if sign * (entry - invalidation) <= 0:
        p.status, p.reasons = "BLOCKED", ["INVALID_SL: invalidation level is not beyond the entry on the losing side"]
        return p
    if sign * (target - entry) <= 0:
        p.status, p.reasons = "BLOCKED", ["INVALID_TP: target is not beyond the entry on the winning side"]
        return p
    vpu, w = value_per_unit(spec)
    p.warnings += w
    if vpu is None or vpu <= 0:
        p.status, p.reasons = "RISK_NOT_EVALUABLE", ["NO_VALUE_PER_UNIT"]
        return p
    slip = policy.slippage_spread_mult * spread
    comm_d = policy.commission_per_lot / vpu if policy.commission_per_lot else 0.0
    if not policy.commission_per_lot:
        p.warnings.append("COMMISSION_NOT_CONFIGURED(0 assumed)")
    stop_d, tgt_d = abs(entry - invalidation), abs(target - entry)
    loss_d = stop_d + spread + slip + comm_d
    reward_d = tgt_d - spread - slip - comm_d
    min_stop = spec.stops_level_points * spec.point
    if min_stop and stop_d < min_stop:
        p.status, p.reasons = "BLOCKED", [f"SL_TOO_CLOSE: {stop_d:.2f} < broker stops level {min_stop:.2f}"]
        return p
    gross_rr, net_rr = tgt_d / stop_d, (reward_d / loss_d if reward_d > 0 else 0.0)
    risk_money = equity * policy.risk_fraction
    loss_per_lot = loss_d * vpu
    lot_raw = risk_money / loss_per_lot
    lot = min(floor_to_step(lot_raw, spec.volume_step, spec.volume_min), spec.volume_max)
    px_margin = entry_price_for_margin if entry_price_for_margin is not None else entry
    if spec.margin_per_lot is not None and spec.margin_reference_price:
        margin_lot = spec.margin_per_lot * px_margin / spec.margin_reference_price
    else:
        margin_lot = spec.contract_size * px_margin / spec.leverage
        p.warnings.append("MARGIN_ESTIMATED_FROM_CONTRACT_AND_LEVERAGE")
    fill = entry + sign * (spread + slip)                       # bid-chart coordinates of the filled price (cost included)
    p.plan = {"direction": direction, "entry": entry, "fill_estimate": fill, "stop_loss": invalidation, "take_profit": target,
              "tp2_reference": entry + sign * policy.tp2_rr_reference * stop_d, "stop_distance": stop_d, "target_distance": tgt_d,
              "loss_distance_with_costs": loss_d, "reward_distance_net": reward_d, "gross_rr": gross_rr, "net_rr": net_rr,
              "spread": spread, "slippage_allowance": slip, "value_per_price_unit_per_lot": vpu, "risk_budget": risk_money,
              "loss_per_lot": loss_per_lot, "lot_raw": lot_raw, "lot": lot, "estimated_loss_at_sl": lot * loss_per_lot,
              "margin_per_lot_estimate": margin_lot, "margin_estimate": lot * margin_lot, "atr": atr,
              "stop_distance_atr": stop_d / atr if atr else None, "policy_version": policy.version}
    if lot < spec.volume_min - 1e-12:
        p.status = "BLOCKED"
        p.reasons.append(f"RISK_MIN_LOT_EXCEEDS_BUDGET: the minimum lot would risk {spec.volume_min * loss_per_lot / risk_money:.2f} x the budget")
        return p
    if lot * margin_lot > free_margin:
        p.status = "BLOCKED"
        p.reasons.append(f"INSUFFICIENT_MARGIN: the margin needed is {lot * margin_lot / free_margin:.2f} x the free margin" if free_margin > 0 else "INSUFFICIENT_MARGIN: no free margin")
        return p
    if net_rr < policy.min_net_rr:
        p.status = "BLOCKED"
        p.reasons.append(f"RR_TOO_LOW: net {net_rr:.2f} < {policy.min_net_rr} (gross {gross_rr:.2f})")
        return p
    if lot_raw > spec.volume_max:
        p.warnings.append("LOT_CAPPED_AT_VOLUME_MAX")
    return p
