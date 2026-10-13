"""Read-only MT5 probe. Never prints login/password. Usage: probe_mt5.py [terminal_path]"""
import sys, time, statistics
import MetaTrader5 as mt5

path = sys.argv[1] if len(sys.argv) > 1 else r"C:\Program Files\MetaTrader 5\terminal64.exe"
if not mt5.initialize(path=path):
    print("INIT_FAILED", mt5.last_error()); sys.exit(1)

ti = mt5.terminal_info()
print("terminal:", ti.name, "build", ti.build, "connected", ti.connected,
      "trade_allowed", ti.trade_allowed, "tradeapi_disabled", ti.tradeapi_disabled, "ping_us", ti.ping_last)
print("path:", ti.path); print("data_path:", ti.data_path)
ai = mt5.account_info()
print("server:", ai.server, "| trade_mode:", ai.trade_mode, "(0=demo) | currency:", ai.currency, "| leverage:", ai.leverage)

cands = [s.name for s in (mt5.symbols_get("*XAU*") or [])]
print("XAU symbols:", cands)
sym = next((c for c in cands if c.upper().startswith("XAUUSD")), None)
if not sym: print("NO_XAUUSD"); mt5.shutdown(); sys.exit(2)
mt5.symbol_select(sym, True)
si = mt5.symbol_info(sym)
for f in ("digits","point","trade_tick_size","trade_tick_value","trade_contract_size","volume_min","volume_max","volume_step","spread","trade_mode","currency_base","currency_profit","path"):
    print(f"  {f}: {getattr(si,f)}")

# tick polling sample for ~20s
last=None; n=0; changes=0; dts=[]; t_end=time.monotonic()+20
while time.monotonic()<t_end:
    t0=time.perf_counter_ns(); tk=mt5.symbol_info_tick(sym); dts.append((time.perf_counter_ns()-t0)/1e6); n+=1
    if tk and (last is None or tk.time_msc!=last.time_msc or tk.bid!=last.bid or tk.ask!=last.ask):
        changes+=1; last=tk
    time.sleep(0.005)
print(f"poll calls={n} unique_ticks={changes} call_ms p50={statistics.median(dts):.3f} max={max(dts):.3f}")
print("last tick:", last)
now_ms=int(time.time()*1000); print("tick age vs local clock ms:", now_ms-last.time_msc, "(broker-time offset likely included)")
rates=mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 0, 3); print("M1 last 3:", rates)
t=mt5.copy_ticks_from(sym, int(time.time())-60, 1000, mt5.COPY_TICKS_ALL); print("copy_ticks_from last 60s:", None if t is None else len(t))
mt5.shutdown()
