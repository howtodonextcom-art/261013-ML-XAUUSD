import { test, expect, Page } from '@playwright/test';

// Visual regression of the DECISION CARD on deterministic SYNTHETIC fixtures (never live data). Baselines live in tests/e2e/visual.spec.ts-snapshots
// (Windows + Chrome 155 rendering; regenerate with --update-snapshots only after a deliberate UI change and review the diff).
const SETUP = { setup_id: 'M15-BUY-1791920000-4100.00', direction: 'BUY', state: 'ENTRY_ELIGIBLE', evidence: ['CONTEXT:higher-timeframe BUY direction', 'ZONE:2 confirmed swings, [4101.10, 4102.40]', 'CONFIRMATION:bullish pattern bar closed at 4103.20'],
  invalidation_level: 4099.8, entry_level: 4103.2, expires_at: 1_791_928_800, entry_window_ends_at: 1_791_926_400, next_required_event: 'entry decision (risk gate) while price stays inside the band and above the invalidation level' };
const PLAN = { direction: 'BUY', entry: 4103.2, stop_loss: 4099.8, take_profit: 4118.4, tp2_reference: 4110.0, net_rr: 3.4, gross_rr: 4.1, risk_fraction: 0.005, size_hidden: true };
function p(o: any) {
  return { type: 'intel', evaluated_at: 1_791_925_680, mode: 'READ_ONLY+SHADOW+PAPER_SIMULATION', bars: {}, status: {}, analysis: {}, setup_events: o.events ?? [],
    market: { direction_tf: 'H1', direction: 'UP', conflict_tf: 'H4', conflict_direction: 'NONE', conflict: false, regime: { M15: 'TRANSITION', H1: 'TRENDING_UP', H4: 'TRANSITION' }, history: 'OK' },
    overlays: { zone: null, lines: [], direction: null },
    decision: { kind: 'RESEARCH_DECISION', execution_authorized: false, strategy_version: 'cand-1[setup-1+risk-1+gate-1]', dataset_version: 'FIXTURE', action: o.action, primary_reason: o.primary, layer: o.layer ?? 'strategy',
      strategy_eligible: !!o.eligible, reasons: o.reasons ?? { market: [], strategy: [o.primary], gate: [] }, setup: o.setup ?? null, plan: o.plan ?? null, risk: null, next_required: o.next ?? null } };
}
async function fixture(page: Page, payload: any) {
  await page.route('**/api/intel', (r) => r.fulfill({ json: payload }));
  await page.routeWebSocket(/\/ws$/, (ws) => {
    const server = ws.connectToServer();
    server.onMessage((m) => { try { if (JSON.parse(String(m)).type === 'intel') return; } catch { /* forward */ } ws.send(m); });
    const t = setInterval(() => ws.send(JSON.stringify(payload)), 400);
    ws.onClose(() => clearInterval(t));
  });
}
const CASES: Record<string, any> = {
  'wait-no-direction': p({ action: 'WAIT', primary: 'NO_DIRECTION', layer: 'market', next: 'the higher timeframe (H1) structure and trend must agree on a direction', reasons: { market: ['NO_DIRECTION'], strategy: [], gate: [] } }),
  'buy-eligible': p({ action: 'BUY', primary: 'ENTRY_ELIGIBLE', eligible: true, setup: SETUP, plan: PLAN, next: 'decision only: no order is sent; the paper plan is hypothetical' }),
  'blocked-not-eligible': p({ action: 'BLOCKED', primary: 'RISK:RR_TOO_LOW', layer: 'gate', eligible: true, setup: SETUP, plan: { ...PLAN, size_hidden: undefined, take_profit: 4112.0, net_rr: 1.2, gross_rr: 1.6 }, next: 'price must offer at least the minimum net reward-to-risk after costs', reasons: { market: [], strategy: ['ENTRY_ELIGIBLE'], gate: ['RISK:RR_TOO_LOW'] } }),
  'stale': p({ action: 'WAIT', primary: 'DATA_STALE', layer: 'gate', reasons: { market: [], strategy: [], gate: ['DATA_STALE', 'INTEL_ENGINE_STALLED'] } }),
  'wait-with-terminal-events': p({ action: 'WAIT', primary: 'AWAITING_PULLBACK', next: 'an impulse leg in the H1 direction, then a pullback of at least 0.5 ATR from its extreme',
    events: [{ setup_id: 'M15-SELL-1791890000-4150.00', direction: 'SELL', state: 'MISSED', known_at: 1_791_915_000, reasons: ['PRICE_RAN_AWAY'] }, { setup_id: 'M15-BUY-1791900000-4090.00', direction: 'BUY', state: 'INVALIDATED', known_at: 1_791_924_900, reasons: ['ZONE_FAILED'] }] }),
};
for (const [name, payload] of Object.entries(CASES)) {
  test(`F10 visual regression: decision card, ${name}`, async ({ page }) => {
    await fixture(page, payload);
    await page.goto('/');
    await expect(page.getByTestId('decision-action')).not.toHaveText('…');
    await page.waitForTimeout(700);
    await expect(page.getByTestId('decision-card')).toHaveScreenshot(`card-${name}.png`, { maxDiffPixelRatio: 0.01 });
  });
}
