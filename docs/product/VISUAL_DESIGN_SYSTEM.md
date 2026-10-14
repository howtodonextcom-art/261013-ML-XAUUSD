# Visual design system (Level 6.4)

Dark trading terminal; own tokens, no third-party branding. State is always carried by TEXT or SHAPE as well as colour.

| Token | Value | Use | Contrast on panel #131822 (WCAG) |
|---|---|---|---|
| text | #d6dde8 | body | 13.0:1 |
| muted | #9aa7bb (was #7d8aa0, 5.1:1) | secondary text | 7.3:1 |
| BUY / ok | #2ebd85 | V1 BUY, DONE | 7.4:1 |
| SELL | #ff6b7f (markers/text), #f6465d (accent, 5.0:1) | V1 SELL | 6.5:1 |
| WAIT | neutral grey (muted) | WAIT | 7.3:1 |
| BLOCKED / warning | #f0b90b, markers #ff9f1c | BLOCKED, WAITING, next required bar | 9.9:1 / 8.7:1 |
| V2 SHADOW | #38bdf8 (cyan-blue) | shadow markers, always the text V2 SHADOW | 8.3:1 |
| stale | line-through plus the word STALE and a banner | stale/disconnected | n/a |
| market bias | green/red TEXT colour on its own line, a different presentation (sentence, not a big label) from the V1 action | BULLISH / BEARISH | as BUY / SELL |

Shapes and words: BUY ▲ `BUY · RESEARCH`, SELL ▼ `SELL · RESEARCH`, BLOCKED amber square, setup observations circles / squares with the letters F C X I M and the side B/S, V2 arrows labelled `V2 SHADOW`; current decision tagged `NOW`, history untagged. Progress steps are words (DONE / ACTIVE / WAITING / FAILED / NOT EVALUATED) with a left bar as a redundant cue.

Typography: body 14 px (was 13), secondary 12 px (was 11), hero action 28 px monospace; hero, chips and next-required line wrap instead of clipping. No animation or flashing; the toast appears without motion and is dismissible.

Layout (option B of docs/product/PRODUCT_FIT_AUDIT.md): chart sticky at full viewport height; right column = decision hero (action, reason, plain sentence, eligibility and signal-age chips, market bias, setup progress, next required, plan), M1 price action (V2 SHADOW), one collapsible "More" (market details, setup event inspector, history and research status), collapsed "Advanced diagnostics"; the "Panels" button hides the right column; below 900 px one column (decision, chart, panels). Verified 1440x900, 1152x720 and 390x844 (emulated) without horizontal overflow; native zoom NOT TESTED.

Tests: `tests/e2e/redesign.spec.ts` (sizes >= 14 px / 12 px, muted contrast >= 4.5 computed in the browser, hero not clipped, clock, chips, alerts, collapsible More, sidebar toggle, M1 lines), visual baselines of the decision card, the accessibility and inventory suites.
