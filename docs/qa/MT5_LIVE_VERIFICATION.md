# MT5 live verification session (Mode A/B capture and indicator parity)

Status on 2026-10-14: **LIVE_AB_NOT_TESTED**, **indicator parity NOT TESTED**. Both need two manual actions inside the MetaTrader 5 terminal that this software is not allowed to perform itself (no chart or EA control from Python, by design). Everything else is prepared and tested offline; no result below is invented.

## What is prepared
| Item | State |
|---|---|
| `mt5/experts/XauTickLoggerModeB.mq5` v1.1 | compiled 0 errors / 0 warnings into the terminal's `MQL5\Experts\xau_tmp_compile`; paginated CopyTicks (5000-tick limit), `account_ref` in the file name, `#gap` markers; no trading, network or delete call (enforced by a test over every `.mq5`) |
| `services/gateway/xau_gateway/modeb_reader.py` | partial lines, truncation, malformed lines, EA restarts, gap markers, identity header; 11 unit tests incl. a Python model of the EA algorithm that found and fixed a pagination stall (many ticks in one millisecond) |
| `benchmarks/ab_capture.py` | identity gate: any mismatch, missing header, unpinned account, unverified Mode A or symbol difference exits 4 (FAILED) and writes no result; exit 3 = NOT TESTED; 4 unit tests |
| `mt5/scripts/DumpIndicators.mq5` + `benchmarks/mt5_indicator_parity.py` | compiled earlier; the comparison refuses any dump that is not provably from the pinned, fresh MetaQuotes-Demo feed (provenance); exit 3 = NOT TESTED while the CSV files are missing (confirmed today) |
| `scripts\windows\verify_live_session.ps1` | runs both and prints the honest status word of each |

## Your steps (about 40 minutes, once)
1. Open the **MetaQuotes-Demo** terminal (not FTMO). Check the account in the title bar.
2. Indicator parity: Navigator > Scripts > `xau_tmp_compile` > `DumpIndicators`; drag it onto an XAUUSD chart. It writes `xau_ind_XAUUSD_{M15,H1,H4}.csv/.meta` into the Common files folder and stops by itself.
3. Mode B: Navigator > Expert Advisors > `xau_tmp_compile` > `XauTickLoggerModeB`; drag it onto ONE XAUUSD chart. Enable "Algo Trading" for it (a terminal-wide switch: attach only EAs you trust; this EA has no trading code). The file `xau_modeb_XAUUSD_<account_ref>.csv` appears in the Common files folder.
4. `powershell -File scripts\windows\verify_live_session.ps1 -Minutes 30` (the gateway may keep running). Prefer a normal market window; for a burst test run it again around a news release (the EA's pagination is designed for it but is untested live).
5. Read `results/p2/ab_capture.json`. The choice between Mode A, Mode B or a hybrid is made from it: completeness (only A / only B / both), the B-minus-A receipt time on the same tick (clock-skew free), reconnect and file-recovery behaviour. Do NOT assume the EA is faster.
6. Remove the EA from the chart afterwards if Mode B is not adopted.

## Decision rule (stated before measuring)
Mode B enters the gateway only if (a) zero ticks seen only by A over the whole run (completeness at least equal), (b) the B-minus-A receipt time on the same tick has p50 below zero by more than the measurement noise and p99 not worse than +50 ms, (c) the identity gate passes and the file survives an EA restart and a reader restart without duplicates or gaps (`modeb_reader.gaps` empty or explained), and (d) a second independent review of the integration. Otherwise Mode A stays the only source and Mode B remains an experiment.

## Not covered
Running both modes through the full gateway pipeline; behaviour with two terminals running (the account_ref in the file name prevents a collision, but it is not tested live); MT5 builds other than 6259.
