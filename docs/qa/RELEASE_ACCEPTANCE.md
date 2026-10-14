# RELEASE ACCEPTANCE (2026-10-14, Level 5.2)

Status words: VERIFIED PASS, PARTIAL, FAILED, BLOCKED, NOT TESTED, NOT IMPLEMENTED. "Verified" is a statement about software behaviour, never about profitability.

## Release classification: **RESEARCH BETA**
The software is accepted as a research-grade decision-support terminal. It is **not** a profitable trading system (no edge is demonstrated) and it has **no** live-order capability. Three separate acceptances:

### 1. SOFTWARE ACCEPTANCE (app, data, backend decision, Chrome UI, auth, QA)
| Area | Status | Evidence / gap |
|---|---|---|
| Data integrity | PARTIAL | crash/restart recovery, seam coverage, isolation, M1/HTF parity, quarantine, fixed chunk grid, M1-hole detection tested. Gaps: parity covers about 20% of M1 bars, one unexplained quarantined bar, crash experiment n=1 |
| Backend decision (V1) | VERIFIED PASS (software) | state machine, WAIT taxonomy, mirrored SELL, risk-1/gate-1, privacy mode, stale handling; live ENTRY_ELIGIBLE NOT OBSERVED |
| M1 entry V2 (shadow) | VERIFIED PASS (software, shadow only) | causal events (prefix invariance and future corruption, mutation-checked), mirror, wick-without-confirmation case, forward-only log, separation from V1; NO performance claim |
| Chrome UI | VERIFIED PASS (fixtures) / PARTIAL (live) | Playwright suite in real Chrome (incl. visual regression, accessibility, layers, drawing); interactive MCP sessions; BUY/SELL on live data not observed; native browser zoom NOT TESTED (emulated) |
| Authentication / access control | VERIFIED PASS (software) | token + cookie + WebSocket handshake, Host/Origin, limiter, fail-closed peer guard with a real-process test; plain HTTP, no TLS |
| Privacy | VERIFIED PASS (privacy mode) | public output independent of the real account (tests); reveal mode is an explicit choice |
| Safety (no order path) | VERIFIED PASS (static) | no execution call in any Python or MQL5 source |
| Independent review | PARTIAL | independent reviewers found real defects in every round (5, 6, 6b, 7, 8, and the Level 5.2 pass); fixes made after the last pass are covered by their own tests only |
| Windows / Mac | Windows VERIFIED (this PC); Mac NOT TESTED | docs/handover/WINDOWS_RUNBOOK.md, MAC_ACCESS_GUIDE.md |

### 2. LIVE CONNECTIVITY ACCEPTANCE (MT5 source, Mode A/B, indicator parity, latency)
| Area | Status | Evidence / gap |
|---|---|---|
| Mode A source (live ticks, identity pinned) | VERIFIED PASS (this PC, MetaQuotes-Demo) | live sessions, reconnect, restart recovery |
| Mode B (EA) and A/B benchmark | LIVE_AB_NOT_TESTED | EA v1.1 compiled; reader, EA-algorithm model, identity gate and fake-feed tests pass; needs the manual MT5 steps (docs/handover/MT5_VERIFICATION_REPORT.md) |
| MT5 indicator parity | PARITY_NOT_TESTED | needs the DumpIndicators run |
| Latency | PARTIAL | measured in real Chrome: gateway p99 about 7 ms, delivery p99 about 7 ms, render p99 about 17 ms (foreground); heavy analysis in a worker process (in-process it delayed ticks to p99 20 ms); broker-to-PC leg not measurable (0.3 s clock difference); no series across many bar closes |
| Real DST switch | NOT TESTED | synthetic DST tested (mixed window = LOW, never a confident wrong offset); real dates 2026-10-25 and 2026-11-01 |

### 3. RESEARCH VALIDATION (strategy and ML evidence)
| Study | Status |
|---|---|
| V1 strategy out of sample | INSUFFICIENT_EVIDENCE (7 validation trades; holdout sealed and unopened) |
| ML shadow | NO_EVIDENCE_OF_PREDICTIVE_SKILL (AUC 0.499) |
| M1 entry V2 | FORWARD_SHADOW_COLLECTING (evaluation needs 100 triggers and 30 days; no historical evidence is possible: all M1 history is inside the sealed holdout period) |

Details: docs/handover/RESEARCH_STATUS.md. Test totals: docs/qa/IMPLEMENTATION_STATE.md (checkpoint).
Rollback: docs/handover/SECURITY_AND_ROLLBACK.md.
