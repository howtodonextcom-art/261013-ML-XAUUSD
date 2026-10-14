# Product vision and requirements (RECONSTRUCTED)

Status: the original PRODUCT_VISION_AND_REQUIREMENTS.md / PRODUCT_ACCEPTANCE_MATRIX.md referred to by Master Prompt Level 5 are not in the repository or on this machine. This file is reconstructed from the "Product north star" of that prompt. Details not present in the prompt are marked UNVERIFIED and must be confirmed by the owner; nothing here claims implementation status (see PRODUCT_ACCEPTANCE_MATRIX.md for that).

## Purpose
A real-time decision-support terminal for XAU/USD (MT5 MetaQuotes-Demo, Windows 11, later MacBook M1). Mode: READ_ONLY + SHADOW + PAPER_SIMULATION. It never sends, modifies or cancels an order.

## Questions the product must answer (R-Q)
- R-Q1 What is XAUUSD doing now on M1, M5, M15, H1, H4?
- R-Q2 Is price trending, pulling back, breaking out, rejecting a zone, or showing possible reversal?
- R-Q3 Which price-action patterns are forming or confirmed?
- R-Q4 Is there a valid BUY/SELL research setup?
- R-Q5 If WAIT: which exact condition is missing?
- R-Q6 If BLOCKED: which risk or data gate failed?
- R-Q7 What are the proposed Entry, SL, TP, R:R and lot (hypothetical)?
- R-Q8 When is the setup INVALIDATED, MISSED or EXPIRED?
- R-Q9 What evidence supports the decision and when did it become knowable?
- R-Q10 Does the strategy show positive out-of-sample expectancy after costs? (answer may be INSUFFICIENT_EVIDENCE / NO_EVIDENCE_OF_EDGE)

## Principles
- M1 is the fast observation and entry-timing timeframe; H1/H4 provide context.
- Never use future bars; never repaint historical signals; never claim certainty about the next candle.
- One authoritative backend decision; the browser only displays it.
- WAIT is a meaningful state (it names the missing condition). BLOCKED never looks actionable. Stale or disconnected data never leaves an apparently actionable signal.
- Status words are honest: VERIFIED PASS / PARTIAL / BLOCKED / FAILED / NOT TESTED / NOT IMPLEMENTED.
- ML predictions (later) stay separate from the rule engine and never authorize execution.

## Functional requirements
- R-F1 Data: live ticks and bars from MT5 (read-only), local verified storage, history M1-H4, integrity/parity checks, recovery after crash.
- R-F2 Live panel (UNVERIFIED exact layout): Bid/Ask/spread; connection and freshness; M1 live candles with M5/M15/H1/H4 context; direction and regime; structure and key zones; setup id/direction/lifecycle stage; supporting and opposing evidence; BUY/SELL/WAIT/BLOCKED with primary reason and the Market/Strategy/Gate layers; next required confirmation; Entry/SL/TP/R:R/lot only when valid and labelled hypothetical; invalidation and expiry; strategy/dataset versions and timestamps; research-only status.
- R-F3 Chart overlays: structure, zones, Entry/SL/TP with preserved price/time coordinates; BLOCKED plans visually distinct and labelled NOT ELIGIBLE.
- R-F4 Drawing tools (later): trendline, horizontal line, zone, select/drag/delete, persistence, undo/redo.
- R-F5 Replay/backtest (P6): deterministic point-in-time replay, no look-ahead, pre-registered candidates, walk-forward, bootstrap, cost sensitivity, one-time holdout.
- R-F6 Mode B (P2): read-only MQL5 bridge, A/B capture benchmark, end-to-end latency (measured, never fabricated).
- R-F7 ML shadow (P7): point-in-time features, training/evaluation/calibration only on trustworthy replay data.
- R-F8 UI completion (P8): accessibility, authentication before any remote access, Windows and Mac compatibility.

## Non-functional requirements
- R-N1 Safety: no order functions; terminal path always explicit; repository identity and push rules per CLAUDE.md.
- R-N2 Privacy: equity and free margin never stored, logged or exposed beyond the documented public plan (see docs/research/RISK_GOVERNANCE.md).
- R-N3 Determinism and reproducibility of research outputs (code SHA, dataset hash, config hash).
- R-N4 Viewports 1440x900, 1152x720, 390x844 usable; browser zoom 100-200% as far as supported.
- R-N5 The unauthenticated API is loopback-only.
