"""Measures how long after a bar closes MT5's tick history + bar tick_volume settle (read-only).
For each of the last N just-closed M1 bars, samples (bidflag tick count in history, bar tick_volume) every 5 s."""
import sys, time, datetime as dt
import MetaTrader5 as mt5
import numpy as np
dur = int(sys.argv[1]) if len(sys.argv) > 1 else 240
assert mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe"); s = "XAUUSD"
log = {}
t_end = time.monotonic() + dur
while time.monotonic() < t_end:
    now = mt5.symbol_info_tick(s).time; cur = now // 60 * 60
    for b0 in (cur - 60, cur - 120):
        t = mt5.copy_ticks_range(s, b0 - 1, b0 + 62, mt5.COPY_TICKS_ALL)
        t = t[(t["time_msc"] >= b0 * 1000) & (t["time_msc"] < (b0 + 60) * 1000)]
        r = mt5.copy_rates_range(s, mt5.TIMEFRAME_M1, b0, b0 + 59)
        if r is None or len(r) == 0: continue
        log.setdefault(b0, []).append((now - b0 - 60, int(((t["flags"] & 2) > 0).sum()), int(r[0]["tick_volume"])))
    time.sleep(5)
for b0, v in sorted(log.items()):
    print(dt.datetime.fromtimestamp(b0, dt.UTC).strftime("%H:%M"), "age_s,hist_bidticks,bar_tv:", v[0], "...", v[-1],
          "| first_match_age_s:", next((a for a, h, tv in v if h == tv), None), "| ever_mismatch:", any(h != tv for _, h, tv in v))
mt5.shutdown()
