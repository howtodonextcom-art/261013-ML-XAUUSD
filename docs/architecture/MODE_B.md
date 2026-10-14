# Mode B capture (P2): read-only MQL5 EA writing a file

Status: EA compiled (0 errors, 0 warnings); reader and the EA's dedupe algorithm unit-tested (tests/unit/test_modeb_reader.py, 9 tests); **A/B benchmark NOT TESTED**: it needs the EA attached to a chart by the user (manual step), so there are no latency or completeness numbers and none are claimed.

## Why a file and not HTTP/WebSocket
`WebRequest` needs the URL on the terminal's allow-list and opens a network path from the terminal to a local server; MQL5 has no WebSocket. A file in the COMMON folder needs no permission, adds no listening endpoint and keeps the "terminal never talks to anything" property. The price is an extra read hop (the reader polls the file).

## Components
- `mt5/experts/XauTickLoggerModeB.mq5`: on each OnTick copies every tick since the last written one (CopyTicks, 2 s overlap, occurrence counting like the Python Mode A cursor) to `<Common>\Files\xau_modeb_<symbol>.csv`, flushing after each call. Header line per EA session: schema, symbol, server, `account_ref` (first 8 hex of SHA-256 of the login; the number itself is never written), digits. No trading, order, position, network or file-delete call: enforced for every `.mq5/.mqh` in the repository by `test_mql5_sources_are_read_only` (mutation-checked).
- `services/gateway/xau_gateway/modeb_reader.py`: tails the file (partial lines kept, truncation restarts and is counted, malformed lines counted not repaired, EA restarts counted as sessions) and `identity_mismatch()` (server / account_ref / symbol pinned like Mode A: SOURCE_MISMATCH on difference).
- `benchmarks/ab_capture.py`: runs the product's Mode A source and the Mode B reader at the same time on the same terminal and reports tick completeness (A only / B only / both, occurrence-counted) and latency (reader wall clock minus tick server stamp; B minus A on the same tick is the clock-skew-free number). Exit code 3 = NOT TESTED (file missing or one side empty).

## How to run the benchmark
1. MetaTrader 5 (MetaQuotes-Demo terminal): Navigator > Expert Advisors > xau_tmp_compile > `XauTickLoggerModeB`, drag onto ONE XAUUSD chart.
2. Enable algorithmic trading for it (the EA has no trading code; note that this toggle is terminal-wide, so only attach EAs you trust).
3. `.\.venv\Scripts\python.exe benchmarks\ab_capture.py --minutes 30` (the gateway may keep running). Result: `results/p2/ab_capture.json`.

## Not done
- Gateway integration of Mode B as a live source (a second TickSource feeding the same cursor/pipeline) is NOT implemented: it should only be added if the A/B numbers show a benefit.
- End-to-end latency (terminal tick -> browser pixel) is not measured; the only measured figure is the gateway-internal receipt-to-publish time (p50 about 1.1-1.4 ms, p95 about 4-6 ms, p99 about 5.5-6.5 ms in recent samples; GIL contention under sustained heavy compute not measured systematically).
