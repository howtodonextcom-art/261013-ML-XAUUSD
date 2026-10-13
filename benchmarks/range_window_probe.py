"""Does copy_ticks_range return the same ticks for a bar regardless of the query window? (read-only)
For each bar, query many (pre, post) margins and count bid-flag ticks inside the bar."""
import sys, MetaTrader5 as mt5, numpy as np, datetime as dt
bars = [int(x) for x in sys.argv[1:]] or [1791910680, 1791918480]
assert mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe"); s = "XAUUSD"
for b0 in bars:
    r = mt5.copy_rates_range(s, mt5.TIMEFRAME_M1, b0, b0 + 59)[0]
    print(f"\nbar {dt.datetime.fromtimestamp(b0, dt.UTC):%H:%M}  MT5 tick_volume={r['tick_volume']} low={r['low']}")
    for pre, post in [(0, 59), (0, 60), (0, 61), (0, 62), (0, 65), (0, 120), (-1, 62), (-2, 61), (-5, 65), (-30, 90), (-60, 120), (-300, 300)]:
        t = mt5.copy_ticks_range(s, b0 + pre, b0 + 60 + post - 60 + 0, mt5.COPY_TICKS_ALL) if False else mt5.copy_ticks_range(s, b0 + pre, b0 + post, mt5.COPY_TICKS_ALL)
        t = t[(t["time_msc"] >= b0 * 1000) & (t["time_msc"] < (b0 + 60) * 1000)]
        print(f"  window=[b0{pre:+d}, b0+{post}]  ticks_in_bar={len(t):4d}  bidflag={int(((t['flags']&2)>0).sum()):4d}  min_bid={t['bid'].min()}")
    for n in (1000, 5000, 50000):
        t = mt5.copy_ticks_from(s, b0 - 30, n, mt5.COPY_TICKS_ALL)
        t = t[(t["time_msc"] >= b0 * 1000) & (t["time_msc"] < (b0 + 60) * 1000)]
        print(f"  copy_ticks_from(b0-30, count={n:5d}) bidflag={int(((t['flags']&2)>0).sum()):4d}")
mt5.shutdown()
