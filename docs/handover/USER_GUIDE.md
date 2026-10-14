# User guide: reading the XAU/USD Trading Intelligence Terminal

This is a research and decision-support tool. **Nothing on screen is an order and the software cannot place, change or cancel one.** BUY and SELL here mean "the research rules say a hypothetical entry is justified"; they are not advice and not a promise of profit (no edge has been demonstrated, see RESEARCH_STATUS.md).

## Opening it
Start the gateway (WINDOWS_RUNBOOK.md), then open the printed URL once, or run `scripts\windows\open_dashboard.ps1`. The browser keeps a login cookie for 7 days. Without it you only see "Authentication required".

## The five regions
1. **Live market** (top bar and chart): bid / ask / spread, the connection state (`CONNECTED_ACTIVE` is the only state that means live ticks; anything else means the prices on screen may be old and are struck through), timeframe buttons M1 to H4, the chart, and the *Data quality & latency* panel (tick rate, data age, queue, drops, gateway latency).
2. **Market intelligence**: H1 direction, H4 direction (and a CONFLICT flag when they oppose), regime per timeframe, structure and EMA alignment, RSI / ATR, and the nearest confirmed support/resistance zones.
3. **Setup intelligence**: the V1 setup lifecycle inside the decision card (stage, evidence, invalidation, expiry) and the separate **M1 entry intelligence (SHADOW)** card.
4. **Decision and risk**: the V1 research decision (BUY / SELL / WAIT / BLOCKED), its three reason layers, the next required confirmation and the hypothetical Entry / SL / TP / R:R.
5. **History and research**: recent setup events (click a time to jump to that moment on the chart without recomputing anything) and the research status lines.

## What BUY, SELL, WAIT and BLOCKED mean
- **WAIT**: no entry is justified now. The line below names the exact reason (for example `AWAITING_PULLBACK`, `AWAITING_CONFIRMATION`, `SIGNAL_CONFLICT`) and "Next required" says what has to happen next. WAIT is the normal state; most of the time it is correct.
- **BUY / SELL**: a setup reached `ENTRY_ELIGIBLE` AND every gate (fresh data, spread, risk plan, net R:R) passed. The plan below it is hypothetical.
- **BLOCKED**: the strategy side is eligible but a gate or risk check failed (for example `RISK:RR_TOO_LOW`, `SPREAD_TOO_WIDE`, `RISK:SL_TOO_CLOSE` = the broker's 6.00 USD stops level). Levels may be drawn dashed grey and titled **NOT ELIGIBLE**; no size is shown. It must never be read as permission to enter.
- **STALE** (grey, struck through): the data or the analysis is not fresh. Every level, plan and marker is removed. Do not rely on anything that was on screen before.
- The **three reason layers** are *Market* (why there is or is no direction), *Strategy* (where the setup lifecycle stands) and *Gate* (data, spread, risk). When the setup is not eligible the strategy reason is shown first even if a gate also fails.

## Entry, SL, TP, R:R and risk
- Entry is the planned entry price, SL the invalidation level plus a buffer, TP the impulse extreme. R:R is net of spread, slippage and commission assumptions.
- **Privacy mode (default)**: the plan is sized on a *reference* account (10 000 by default) and the lot is hidden. This is NOT a check that your real account has enough margin. `XAU_REVEAL_SIZE=1` (a start-up setting) sizes on the live account and shows the lot; read SECURITY_AND_ROLLBACK.md first.
- **Expiry times** are approximate (bar-count rule): across market breaks the real expiry is later.

## Setup lifecycle in plain words
`SETUP_FORMING` (an impulse leg exists) -> `PULLBACK_IN_PROGRESS` -> `AT_RELEVANT_ZONE` -> `AWAITING_CONFIRMATION` -> `CONFIRMED` -> `ENTRY_WINDOW` / `ENTRY_ELIGIBLE`. Endings: `INVALIDATED` (structure or zone failed), `MISSED` (price ran away), `EXPIRED` (too old). A setup only changes state at a closed bar.

## M1 entry intelligence (SHADOW)
A separate research observation of entry timing: an M15 zone, an M5 confirmation, then a CLOSED M1 trigger bar (rejection / engulfing / momentum shift / local structure break). It never changes the decision above and is not a signal. A **wick without confirmation** is shown as "forming (unconfirmed)" or as "awaiting M5 confirmation" and is never a trigger. Its evidence is collected forward in time only; until at least 100 triggers and 30 days have passed it has **no performance claim**. Many M1-scale stops are smaller than the broker's 6.00 USD stops level and are reported as blocked.

## Chart layers and drawing
- Layer buttons: EMA20 / EMA50 / EMA200 (closed bars), Zones, Structure (breakout / BOS / CHoCH markers), Setups (lifecycle markers), M1 shadow (arrows). Choices persist in the browser.
- Drawing tools (your own notes, never signals): H-line, Trend (two clicks on two different bars), Zone (two clicks); Select then drag to move, Delete / Del to remove, Undo / Redo (Ctrl+Z / Ctrl+Y), Clear. Drawings live in this browser only.
- Markers use short codes: `C` confirmed, `I` invalidated, `M` missed, `X` expired, triangles = structure events, blue arrows = M1 shadow.

## Keyboard
Tab moves through timeframes, drawing tools, layer toggles and history times in reading order; Enter / Space activates; focus is outlined. Decision changes are announced politely to screen readers (not on every refresh).

## What this tool cannot tell you
Whether the next candle goes up; whether the strategy makes money (it has not been shown to); whether your real account can afford the plan; anything about live broker execution.

## The plain-words line (new)
Under the decision's reason code the card shows one sentence in ordinary language (for example "Price is at the zone; no confirming candle has closed yet."). It is generated from the same backend reason code, it adds no information the code does not already carry, and it never says BUY or SELL for a BLOCKED decision. For a BUY/SELL it reads "not an order and not a proven trade". "Next required" (yellow bar) is the one event that would change the picture.
