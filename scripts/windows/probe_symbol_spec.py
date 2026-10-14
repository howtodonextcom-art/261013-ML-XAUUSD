"""Read-only: broker symbol specification and MT5's own profit/margin calculations (order_calc_profit / order_calc_margin only
CALCULATE; no order is sent or checked). Prints no account number; account balance figures are not printed.
Usage: probe_symbol_spec.py [symbol]"""
import json
import sys
from pathlib import Path

import MetaTrader5 as mt5

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "gateway"))
from xau_gateway.identity import load_source_config, verify_identity

cfg = load_source_config()
sym = sys.argv[1] if len(sys.argv) > 1 else cfg.get("symbol_hint", "XAUUSD")
assert mt5.initialize(path=cfg["terminal_path"]), mt5.last_error()
bad = verify_identity(mt5.terminal_info(), mt5.account_info(), cfg["terminal_path"], cfg.get("expected"))
if bad:
    mt5.shutdown()
    sys.exit(f"SOURCE_MISMATCH: {bad}")
mt5.symbol_select(sym, True)
si = mt5.symbol_info(sym)
tk = mt5.symbol_info_tick(sym)
spec = {f: getattr(si, f) for f in ("digits", "point", "trade_tick_size", "trade_tick_value", "trade_tick_value_profit", "trade_tick_value_loss",
                                    "trade_contract_size", "volume_min", "volume_max", "volume_step", "trade_calc_mode", "trade_stops_level",
                                    "trade_freeze_level", "currency_base", "currency_profit", "currency_margin", "margin_initial", "margin_maintenance",
                                    "swap_long", "swap_short", "spread", "spread_float")}
ai = mt5.account_info()
spec["account_currency"], spec["leverage"] = ai.currency, ai.leverage
print(json.dumps(spec, indent=1))
price = tk.ask
print("--- MT5's own calculation for 1.00 lot, a 1.00 price move up from the ask", price)
p = mt5.order_calc_profit(mt5.ORDER_TYPE_BUY, sym, 1.0, price, price + 1.0)
print("order_calc_profit(BUY, 1 lot, +1.00) =", p, "(account currency)")
p2 = mt5.order_calc_profit(mt5.ORDER_TYPE_SELL, sym, 1.0, tk.bid, tk.bid - 1.0)
print("order_calc_profit(SELL, 1 lot, -1.00) =", p2)
m = mt5.order_calc_margin(mt5.ORDER_TYPE_BUY, sym, 1.0, price)
print("order_calc_margin(BUY, 1 lot) =", m)
print("implied by contract size: contract * 1.00 =", si.trade_contract_size * 1.0, "| implied by tick value: (1.00/tick_size)*tick_value =", (1.0 / si.trade_tick_size) * si.trade_tick_value)
mt5.shutdown()
