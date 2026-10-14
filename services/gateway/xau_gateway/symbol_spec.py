"""Broker symbol specification snapshot for the risk engine. READ-ONLY: it uses symbol_info, symbol_info_tick, account_info (currency and
leverage only) and MT5's pure CALCULATION helpers order_calc_profit / order_calc_margin, which compute numbers and send nothing.
The snapshot is stored in the data store (`Store.set_meta`) so an offline replay uses the exact specification that was live; account
equity and free margin are NEVER stored or logged (they live in memory only, see account_snapshot).
"""
from __future__ import annotations

import json
import time


def spec_from_mt5(mt5mod, symbol: str) -> dict | None:
    si = mt5mod.symbol_info(symbol)
    tk = mt5mod.symbol_info_tick(symbol)
    if si is None or tk is None:
        return None
    ai = mt5mod.account_info()
    ref = float(tk.ask)
    vpu = mt5mod.order_calc_profit(mt5mod.ORDER_TYPE_BUY, symbol, 1.0, ref, ref + 1.0)      # value of a 1.00 move for 1 lot, by MT5 itself
    mg = mt5mod.order_calc_margin(mt5mod.ORDER_TYPE_BUY, symbol, 1.0, ref)
    return {"symbol": symbol, "tick_size": float(si.trade_tick_size), "tick_value": float(si.trade_tick_value),
            "contract_size": float(si.trade_contract_size), "volume_min": float(si.volume_min), "volume_max": float(si.volume_max),
            "volume_step": float(si.volume_step), "point": float(si.point), "leverage": float(ai.leverage) if ai else 100.0,
            "stops_level_points": int(si.trade_stops_level), "value_per_price_unit_per_lot": float(vpu) if vpu else None,
            "margin_per_lot": float(mg) if mg else None, "margin_reference_price": ref, "currency": ai.currency if ai else "USD",
            "captured_at_unix": int(time.time())}


def account_snapshot(mt5mod) -> dict | None:
    """In-memory only. equity / free margin in account currency. Never persisted, never exposed through the API."""
    ai = mt5mod.account_info()
    if ai is None:
        return None
    return {"equity": float(ai.equity), "free_margin": float(ai.margin_free)}


def save_spec(store, spec: dict) -> None:
    store.set_meta(f"symbol:{spec['symbol']}:spec", json.dumps(spec, sort_keys=True))


def load_spec(store, symbol: str) -> dict | None:
    raw = store.get_meta(f"symbol:{symbol}:spec")
    return json.loads(raw) if raw else None


def to_symbol_spec(d: dict):
    """dict -> xau_intel.decision.risk.SymbolSpec (imported lazily: the intelligence package does not depend on the gateway)."""
    from xau_intel.decision.risk import SymbolSpec
    keys = ("symbol", "tick_size", "tick_value", "contract_size", "volume_min", "volume_max", "volume_step", "point", "leverage",
            "stops_level_points", "value_per_price_unit_per_lot", "margin_per_lot", "margin_reference_price", "currency")
    return SymbolSpec(**{k: d[k] for k in keys if k in d})
