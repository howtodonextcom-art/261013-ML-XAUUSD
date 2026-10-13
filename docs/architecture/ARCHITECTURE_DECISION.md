# ARCHITECTURE DECISION (slice 1)

```
MT5 terminal (MetaQuotes-Demo)
   └─ MetaTrader5 Python (Mode A, copy_ticks_from cursor) ── thread: mt5-source
          └─ bounded queue (50k) ── thread: pipeline (validate → CandleEngine → publish)
                 └─ FastAPI WebSocket /ws + GET /api/health, /api/candles/{tf}  (127.0.0.1)
                        └─ static dashboard (Lightweight Charts, vendored, Apache-2.0 + attribution)
```

Decisions and rationale

1. **Mode A first.** It works on this host today, so the vertical slice was proven on real data. Mode B (EA) is not chosen or rejected: it needs an A/B benchmark.
2. **Tick identity.** MT5 ticks carry no unique id. Cursor = last `time_msc` plus the count already consumed at that ms (positional dedupe). Residual risk: ticks inserted late into a ms already consumed would be missed.
3. **Candle basis = Bid.** Measured parity vs MT5 M1 bars over 240 bars: OHLC matches; `tick_volume` equals the number of ticks with `TICK_FLAG_BID` (flags & 2). See `benchmarks/candle_parity.py`. 238/240 bars match exactly.
4. **Time base.** Bars are bucketed in MT5 server time, the same as MT5 charts. Chart labels are server time, not UTC.
5. **Safety.** The source module calls only read APIs; `tests/unit/test_safety.py` rejects order functions in Python and MQL5 sources. API exposes GET/WS only. Bind is loopback.
6. **Staleness.** A connected terminal with no tick for more than 5 s reports `STALE`, never `CONNECTED`.
7. **Stack deviation.** The prompt suggests Next.js. Slice 1 uses a static page to prove data first; migration is deferred and listed in limitations.
