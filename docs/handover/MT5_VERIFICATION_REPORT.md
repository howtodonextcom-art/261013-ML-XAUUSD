# MT5 live verification report

**Status: LIVE_AB_NOT_TESTED. PARITY_NOT_TESTED.** Both need two manual actions inside the MetaQuotes-Demo terminal. Nothing below the "Results" heading has been measured; the fields stay empty until it has.

## What exists
`XauTickLoggerModeB.mq5` v1.1 (compiled, 0 errors / 0 warnings; paginated CopyTicks, account_ref in the file name, gap markers, write-failure handling), `DumpIndicators.mq5` (compiled), `modeb_reader.py`, `benchmarks/ab_capture.py` (identity gate: wrong server / account / symbol, missing header, a header change mid-run, unverified Mode A, unrelated streams or an EA that died early all FAIL; exit codes 0 report, 1 not comparable, 2 refused, 3 NOT TESTED, 4 identity mismatch, 5 internal error), `benchmarks/mt5_indicator_parity.py` (provenance gate), `scripts\windows\verify_live_session.ps1` (honest status words per script), 11 + 9 offline tests including a Python model of the EA algorithm and end-to-end fake-feed tests.

## The one checklist (about 40 minutes)
1. MetaTrader 5, **MetaQuotes-Demo** account (title bar), the pinned terminal.
2. Navigator > Scripts > `xau_tmp_compile` > `DumpIndicators` onto an XAUUSD chart (it writes the CSV files and stops).
3. Navigator > Expert Advisors > `xau_tmp_compile` > `XauTickLoggerModeB` onto ONE XAUUSD chart; allow algorithmic trading for it (terminal-wide switch: the EA contains no trading code; remove it from the chart afterwards if Mode B is not adopted).
4. `.\scripts\windows\verify_live_session.ps1 -Minutes 30` (the gateway may keep running). For the burst case repeat around a news release.
5. Fill in the Results below from `results\p2\ab_capture.json` and the parity output, then decide with the rule in docs/qa/MT5_LIVE_VERIFICATION.md.

## Decision rule (registered before measuring)
Mode B enters the gateway only if: zero ticks seen only by A over the run; B-minus-A receipt time on the same tick has p50 below zero by more than the noise and p99 not worse than +50 ms; identity gate passes and the file survives an EA restart and a reader restart without duplicates or unexplained gaps; and a second independent review of the integration passes. Otherwise Mode A stays the only source.

## Results (to be filled after the live session)
| Item | Result |
|---|---|
| Source identity (server, account_ref, symbol) | NOT TESTED |
| EMA / RSI / ATR / MACD parity vs MT5 (M15, H1, H4) | NOT TESTED |
| Ticks both / only A / only B | NOT TESTED |
| B minus A receipt time on the same tick (p50 / p95 / p99) | NOT TESTED |
| Pagination under a real burst, EA restart, file recovery | NOT TESTED |
| Decision: Mode A / Mode B / hybrid | Mode A (default, no evidence for a change) |
