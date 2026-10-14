# Product acceptance matrix (status is evidence-based; updated 2026-10-14)

Words: VERIFIED PASS (evidence cited) / PARTIAL / BLOCKED / FAILED / NOT TESTED / NOT IMPLEMENTED. Requirement ids: PRODUCT_VISION_AND_REQUIREMENTS.md (reconstructed).

| Req | Status | Evidence / gap |
|---|---|---|
| R-Q1 state on M1-H4 | PARTIAL | Live chart M1-H4 + per-timeframe regime/structure (tests/e2e, intel_demo). Pattern/trend wording is by design thresholds, not validated. |
| R-Q2 trending/pullback/breakout/rejection/reversal | PARTIAL | Regime classifier, BOS/CHoCH, sweeps/false breakouts exist (docs/research/FEATURE_SPEC.md); no outcome validation. |
| R-Q3 price-action patterns | PARTIAL | Quantified candle patterns pa-1 (pin bar, engulfing, strong close); other patterns NOT IMPLEMENTED. |
| R-Q4 valid BUY/SELL research setup | PARTIAL | setup-1 lifecycle + decide(); UI fixtures prove display; live ENTRY_ELIGIBLE not yet observed in a live session (NOT TESTED live). |
| R-Q5 WAIT names the missing condition | VERIFIED PASS (fixtures + live WAIT) | tests/unit/test_decide.py, tests/e2e/decision.spec.ts |
| R-Q6 BLOCKED names failed gate | VERIFIED PASS (fixtures) | same |
| R-Q7 Entry/SL/TP/R:R/lot | PARTIAL | risk-1 with MT5-measured value per lot; lot publicly bounds equity approximately (documented limit). |
| R-Q8 INVALIDATED/MISSED/EXPIRED | PARTIAL | State machine + tests; UI display of terminal states: see BROWSER_TEST_MATRIX. |
| R-Q9 evidence + known_at | PARTIAL | Evidence list and known_at in the decision record; UI shows evidence. |
| R-Q10 out-of-sample expectancy | INSUFFICIENT_EVIDENCE | P6: 7 validation trades (< 20), holdout sealed; docs/research/BACKTEST_REPORT_DEVVAL.md |
| R-F1 data layer | VERIFIED PASS (with documented holes) | docs/qa/DATA_QUALITY_REPORT.md; M1 history holes reported, not filled |
| R-F2 live panel | PARTIAL | Decision card with the three reason layers, next required confirmation, invalidation and expiry, versions, STALE handling; fixture PASS in Chrome (47 Playwright); live ENTRY_ELIGIBLE not observed |
| R-F3 overlays + NOT ELIGIBLE label | PARTIAL | BLOCKED levels are dashed grey and titled NOT ELIGIBLE (fixture PASS); structure overlays beyond zone/levels NOT IMPLEMENTED |
| R-F4 drawing tools | NOT IMPLEMENTED | P8 |
| R-F5 replay/backtest | PARTIAL | Engine + tests + dev/val run; independent review done (docs/research/BACKTEST_AMENDMENTS.md), fixes not re-reviewed; holdout sealed and unopened |
| R-F6 Mode B + latency | NOT IMPLEMENTED | P2; gateway-internal latency only (p50 1.1 / p95 4.3 / p99 5.5 ms receipt-to-publish, not end-to-end MT5 latency) |
| R-F7 ML shadow | NOT IMPLEMENTED | P7 |
| R-F8 accessibility/auth/Mac | NOT IMPLEMENTED | P8 |
| R-N1 safety | VERIFIED PASS | tests/unit/test_safety.py (no order functions; allow-list of calculators) |
| R-N2 privacy | PARTIAL | public plan only; approximate equity inference via lot remains (limit documented) |
| R-N3 reproducibility | VERIFIED PASS (P6) | determinism + prefix-invariance tests, dataset/config hash in results |
| R-N4 viewports/zoom | PARTIAL | Playwright viewports yes; native Chrome zoom NOT TESTED |
| R-N5 loopback-only | PARTIAL | binds 127.0.0.1 only; Host/Origin allow-list added after review round 6 (cross-site WebSocket read refused, tested). Still no authentication: any local process can read the API |
