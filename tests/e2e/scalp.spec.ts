import { test, expect, Page } from '@playwright/test';

// Level 6.5: the SCALPING INTELLIGENCE (C2) card and markers. Fixtures only: a live C2 BUY/SELL is NOT OBSERVED unless it happens.
async function candles(request: any, tf: string, n = 400) { return (await (await request.get(`/api/candles/${tf}?limit=${n}`)).json()).candles as any[]; }
const PLAN = { direction: 'BUY', entry: 4103.2, stop_loss: 4099.8, take_profit: 4118.4, net_rr: 3.4, gross_rr: 4.1, size_hidden: true, risk_fraction: 0.005 };
const ev = (o: any) => ({ log_schema: 1, kind: 'RESEARCH_DECISION_EVENT', execution_authorized: false, source_timeframe: 'M15', strategy_version: 'cand-1', dataset_version: 'FIXTURE', primary_reason: 'ENTRY_ELIGIBLE', risk_status: 'OK', gates: [], plan: PLAN,
  valid: { expires_at: o.published_at + 7200, invalidation_level: 4099.8 }, price: 4103.2, evaluated_at: o.published_at, known_at: o.published_at - 5, publish_latency_s: 5, ...o });
function payload(o: { events?: any[]; current?: string | null; shadow?: any; market?: any; c2?: any }) {
  return {
    type: 'intel', evaluated_at: 1_791_925_680, setup_bar_time: 1, bars: {}, mode: 'READ_ONLY+SHADOW+PAPER_SIMULATION', status: {}, analysis: {}, zones: [],
    market: o.market ?? { direction_tf: 'H1', direction: 'DOWN', conflict_tf: 'H4', conflict_direction: 'DOWN', conflict: false, regime: {}, history: 'OK' },
    setup_events: [], setup_events_total: 0, overlays: { zone: null, lines: [], direction: null }, v1_events: o.events ?? [], v1_current_id: o.current ?? null,
    decision: { kind: 'RESEARCH_DECISION', execution_authorized: false, strategy_version: 'cand-1', dataset_version: 'FIXTURE', action: 'WAIT', primary_reason: 'NO_VALID_IMPULSE', layer: 'strategy', strategy_eligible: false,
      reasons: { market: [], strategy: [], gate: [] }, setup: null, plan: null, risk: null, next_required: 'x', sizing: 'REFERENCE_ACCOUNT' },
    m1_shadow: o.shadow ?? null, scalp_c2: o.c2 ?? null,
  };
}
async function useFixture(page: Page, first: any) {
  let current = first;
  await page.route('**/api/intel', (r) => r.fulfill({ json: current }));
  await page.route('**/api/setup_events*', (r) => r.fulfill({ json: { kind: 'SETUP_EVENTS', total_events: 0, events: [], total_in_range: 0, returned: 0, truncated: false, next_cursor: null, replay_error: null } }));
  await page.routeWebSocket(/\/ws$/, (ws) => {
    const server = ws.connectToServer();
    server.onMessage((m) => { try { if (JSON.parse(String(m)).type === 'intel') return; } catch { /* forward */ } ws.send(m); });
    const t = setInterval(() => ws.send(JSON.stringify(current)), 300);
    ws.onClose(() => clearInterval(t));
  });
  return { set: (p: any) => { current = p; } };
}

const c2 = (o: any = {}) => ({ strategy_id: 'scalp-c2', version: 'scalp-c2-1', kind: 'SCALP_RESEARCH_OBSERVATION', execution_authorized: false, m5_structure: 'DOWN', m1_momentum: 'DOWN', m15: { atr: 5.2 },
  h1_h4: { h1: 'UP', h4: 'NONE', conflict: false, alignment: 'COUNTERTREND' }, side: 'SELL', candidate: 'WATCH SELL', signal: null, missing: 'a closed M1 trigger bar inside the zone band', expires_at: null, plan: null,
  block_reasons: [], zone: { low: 4103.5, high: 4108 }, directions: {}, events_recent: [], funnel: {}, display_only_forming: null, ...o });
const trig = (bt: number, dir = 'SELL') => ({ event_id: `scalp-c2-${dir}-M1_REJECTION-${bt}-1`, direction: dir, stage: 'M1_TRIGGERED', kind: 'M1_REJECTION', bar_time: bt, known_at: bt + 60, alignment: 'COUNTERTREND' });

test('card shows structure, H1 label, candidate and the exact missing condition; V1 hero is untouched', async ({ page }) => {
  await useFixture(page, payload({ c2: c2() }));
  await page.goto('/');
  await expect(page.getByTestId('c2-card')).toContainText('SCALPING INTELLIGENCE · RESEARCH ONLY');
  await expect(page.getByTestId('c2-tfs')).toContainText('M5 structure DOWN');
  await expect(page.getByTestId('c2-align')).toContainText('COUNTERTREND');
  await expect(page.getByTestId('c2-state')).toContainText('WATCH SELL');
  await expect(page.getByTestId('c2-missing')).toContainText('closed M1 trigger bar');
  await expect(page.getByTestId('decision-card')).not.toContainText('C2');
});

test('a closed-bar signal shows the paper plan and expiry; BLOCKED shows the reason, never a widened stop', async ({ page }) => {
  const f = await useFixture(page, payload({ c2: c2({ signal: 'SELL', candidate: 'WAIT', expires_at: 1_791_925_900, plan: { entry: 4105, stop_loss: 4110, take_profit: 4095, net_rr: 1.8 } }) }));
  await page.goto('/');
  await expect(page.getByTestId('c2-state')).toContainText('SELL (research signal');
  await expect(page.getByTestId('c2-plan')).toContainText('entry 4105.00');
  await expect(page.getByTestId('c2-plan')).toContainText('net R:R 1.80');
  f.set(payload({ c2: c2({ signal: 'BLOCKED', block_reasons: ['RISK:SL_TOO_CLOSE'], plan: null }) }));
  await expect(page.getByTestId('c2-plan')).toContainText('BLOCKED: RISK:SL_TOO_CLOSE');
});

test('missing section says unavailable; stale clears it', async ({ page }) => {
  const f = await useFixture(page, payload({ c2: c2() }));
  await page.goto('/');
  await expect(page.getByTestId('c2-state')).toContainText('WATCH SELL');
  f.set(payload({}));
  await expect(page.getByTestId('c2-state')).toContainText('scalping layer unavailable');
  await expect(page.getByTestId('c2-plan')).toHaveText('');
  f.set(payload({ c2: c2() }));
  await expect(page.getByTestId('c2-state')).toContainText('WATCH SELL');
  await page.evaluate(() => (window as any).__layers.onStale());
  await expect(page.getByTestId('c2-state')).toContainText('stale');
});

test('C2 markers are purple, carry the strategy name, and the layer toggle removes them', async ({ page, request }) => {
  const m1 = await candles(request, 'M1');
  const bt = m1[m1.length - 20].time;
  await useFixture(page, payload({ c2: c2({ events_recent: [trig(bt)] }) }));
  await page.goto('/');
  await page.waitForFunction(() => (window as any).__layers && (window as any).__layers.state().markers > 0);
  const has = () => page.evaluate(() => (window as any).__layers.state().markerTexts.some((t: string) => String(t).startsWith('C2 ')));
  expect(await has()).toBe(true);
  await page.getByTestId('layer-c2').click();
  await expect(page.getByTestId('layer-c2')).toHaveAttribute('aria-pressed', 'false');
  expect(await has()).toBe(false);
});

for (const [w, h] of [[1440, 900], [1152, 720], [390, 844]]) {
  test(`C2 card fits the viewport ${w}x${h} without horizontal overflow`, async ({ page }) => {
    await page.setViewportSize({ width: w, height: h });
    await useFixture(page, payload({ c2: c2({ signal: 'BLOCKED', block_reasons: ['RISK:SL_TOO_CLOSE'], plan: { entry: 4105, stop_loss: 4110, take_profit: 4095, net_rr: 1.8 } }) }));
    await page.goto('/');
    await page.getByTestId('c2-card').scrollIntoViewIfNeeded();
    await expect(page.getByTestId('c2-plan')).toContainText('BLOCKED');
    const m = await page.evaluate(() => { const r = document.getElementById('c2-card')!.getBoundingClientRect(); return { right: r.right, left: r.left, sw: document.documentElement.scrollWidth, vw: innerWidth }; });
    expect(m.left).toBeGreaterThanOrEqual(0);
    expect(m.right).toBeLessThanOrEqual(m.vw + 1);
    expect(m.sw).toBeLessThanOrEqual(m.vw + 16);
  });
}
