"""Candle parity: rebuild M1 bars from MT5 ticks with CandleEngine and compare to MT5 copy_rates (read-only).
Usage: candle_parity.py [minutes=60] [terminal_path] [price=bid|ask|mid]"""
import sys
import time
from pathlib import Path

import MetaTrader5 as mt5

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "gateway"))
from xau_gateway.candles import CandleEngine  # noqa: E402

minutes = int(sys.argv[1]) if len(sys.argv) > 1 else 60
path = sys.argv[2] if len(sys.argv) > 2 else r"C:\Program Files\MetaTrader 5\terminal64.exe"
price = sys.argv[3] if len(sys.argv) > 3 else "bid"
assert mt5.initialize(path=path), mt5.last_error()
sym = "XAUUSD"
mt5.symbol_select(sym, True)
tk = mt5.symbol_info_tick(sym)
srv_now = tk.time  # server-time epoch seconds
start = (srv_now // 60 - minutes) * 60
ticks = mt5.copy_ticks_range(sym, start, srv_now, mt5.COPY_TICKS_ALL)  # ints are interpreted as server-time epoch
rates = mt5.copy_rates_range(sym, mt5.TIMEFRAME_M1, start, srv_now)
print(f"ticks={len(ticks)} mt5_bars={len(rates)} basis={price}")
eng = CandleEngine(("M1",), price=price, max_closed=100000)
for t in ticks:
    if t["bid"] > 0 and t["ask"] > 0:
        eng.on_tick(int(t["time_msc"]), float(t["bid"]), float(t["ask"]), int(t["flags"]))
mine = {c.t: c for c in eng.closed["M1"]}
tot = ok = 0
mism = []
for r in rates[:-1]:  # last bar is still forming
    tot += 1
    c = mine.get(int(r["time"]))
    if c is None:
        mism.append((int(r["time"]), "MISSING_IN_ENGINE"))
        continue
    same_px = all(abs(a - b) < 1e-6 for a, b in ((c.o, r["open"]), (c.h, r["high"]), (c.l, r["low"]), (c.c, r["close"])))
    same_v = c.tick_volume == int(r["tick_volume"])
    if same_px and same_v:
        ok += 1
    else:
        mism.append((int(r["time"]), (c.o, c.h, c.l, c.c, c.tick_volume), tuple(r)[1:6]))
print(f"closed bars compared={tot} exact_match(OHLC+tick_volume)={ok} mismatches={len(mism)}")
for m in mism[:10]:
    print("  ", m)
mt5.shutdown()
