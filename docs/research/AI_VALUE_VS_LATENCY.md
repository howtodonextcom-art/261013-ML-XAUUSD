# AI value versus latency (Level 6.4, 2026-10-15)

Question: should AI be integrated into the XAU/USD terminal, and where? Hard constraints: AI never creates a signal or a price, never sits in the tick path, the Risk Gate or the V1 decision, and a slow, failing or missing AI must leave the dashboard unchanged. No AI accuracy claim is made here: nothing below shows that AI makes any decision more accurate.

## Measured stage costs (this PC, 2026-10-15; `benchmarks/stage_latency.py` -> `results/p3/stage_latency.json`, `results/p3/e2e_latency*.json`)
| Stage | Where it runs | p50 / p95 / p99 | Note |
|---|---|---|---|
| MT5 tick acquisition + gateway processing | gateway (tick thread) | gateway 1.3 / 2.3 / 3.2 ms | real Chrome, foreground, 124 frames (LATENCY_REPORT) |
| WebSocket delivery | gateway -> browser | 1.1 / 3.6 / 5.4 ms | same run; broker-to-PC latency is NOT measurable (clock skew) |
| browser render (receipt -> next paint) | browser | 9 / 15 / 16 ms | same run |
| heavy analysis (setup-1, H1/H4 context, 2000-bar window) | worker process | wall 101 / 111 / 115 ms; CPU 94 / 109 / 125 ms | recomputed on each M15/H1/H4 bar close, at the latest every 120 s |
| decision re-evaluation (`make_decision`) | intel thread | 0.004 / 0.006 / 0.008 ms | every 2 s with the current bid, spread, risk |
| V1 event builder | intel thread | below 0.01 ms | first publication only |
| ML shadow: feature build for the window | would run in a worker | wall 51 / 55 / 55 ms | research only, feeds no decision |
| ML shadow: logistic score of one row | any | 0.003 / 0.004 / 0.005 ms | the model is a 14-feature logistic regression |
| setup history replay (all stored bars) | worker, cached | 709 / 732 ms | per store change |
| LLM explanation | external service | NOT MEASURED | no API call was made; depends on provider and network |
Decision eligibility to visible alert: the closed M15 bar makes the setup knowable (`known_at`); the heavy analysis (about 0.1 to 0.2 s) and the intel loop publish immediately (the loop wakes on the bar-close event, it does not wait for its 2 s tick); delivery plus render add about 20 ms. So the dominant delays are the wait for the bar close (inherent to a closed-bar rule) and about a quarter of a second of computation, not paint. Each recorded event stores `publish_latency_s` (1 s resolution). No live BUY/SELL has been observed yet, so this chain is measured per stage, not end to end on a live signal.

## The three options
| Option | What it is | Evidence needed | Latency / risk | Decision |
|---|---|---|---|---|
| **A. Rule engine only** | the deterministic V1 decision as is | exists | no added risk; fully explainable and reproducible; the weakness is not the engine but the missing out-of-sample evidence (INSUFFICIENT_EVIDENCE) | **KEEP** (the only path that may produce BUY/SELL) |
| **B. Asynchronous AI explanation** | an LLM turns the structured backend state (bias, setup state, reasons, next required, funnel facts) into two sentences | acceptance test: every number and state in the text must appear in the structured input; refuse otherwise | adds an external call (seconds, cost, privacy: only market data and setup state may leave the machine, never account data); must run in a separate thread/process with a timeout, off by default, and the card must work without it; the deterministic "plain-words" line already covers 90% of the need at zero latency | **PROTOTYPE later, off by default**, only as a user-requested "explain" button; not built now (no measurement possible without an API, and the template already answers the question) |
| **C. ML shadow intelligence** | a model scores setup quality, failure risk or expected net outcome | dataset integrity, causal features, walk-forward, calibration, cost-adjusted evaluation, ablation against V1, independent review | the existing P7 study: validation AUC 0.499 [0.474, 0.525]: **NO_EVIDENCE_OF_PREDICTIVE_SKILL**; inference cost is negligible, so latency is not the issue, evidence is | **REJECT for any decision use now**; keep as shadow research only (it already feeds nothing); a new pre-registered study is the only way back |

## Design rules if B is ever built
Input = a JSON object produced by the backend (never raw prices typed by the model); output is text only, shown under an "AI explanation, may be wrong" label, with the structured fields displayed next to it; a timeout of a few seconds; failure shows nothing; no caching of anything that identifies the account; the call lives outside the tick path, the heavy worker, the Risk Gate and the V1 decision, so its absence changes no behaviour; every explanation stores the input hash so a human can audit it.

## Conclusion
AI adds no demonstrated accuracy, adds latency and privacy surface in B, and has no evidence in C. The valuable work is already deterministic: clearer states, history, alerts and honest research status.
