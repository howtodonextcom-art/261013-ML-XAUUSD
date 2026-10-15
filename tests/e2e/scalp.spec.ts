import { test, expect, Page } from '@playwright/test';

// Level 6.5.1: C2 signal semantics (trigger vs paper signal vs blocked vs historical) and the scalping-first card. Fixtures only: a live C2 PAPER signal is NOT OBSERVED unless it happens.
async function candles(request: any, tf: string, n = 400) { return (await (await request.get(`/api/candles/${tf}?limit=${n}`)).json()).candles as any[]; }
function payload(o: { market?: any; c2?: any }) {
  return {
    type: 'intel', evaluated_at: 1_791_925_680, setup_bar_time: 1, bars: {}, mode: 'READ_ONLY+SHADOW+PAPER_SIMULATION', status: {}, analysis: {}, zones: [],
    market: o.market ?? { direction_tf: 'H1', direction: 'DOWN', conflict_tf: 'H4', conflict_direction: 'DOWN', conflict: false, regime: {}, history: 'OK' },
    setup_events: [], setup_events_total: 0, overlays: { zone: null, lines: [], direction: null }, v1_events: [], v1_current_id: null,
    decision: { kind: 'RESEARCH_DECISION', execution_authorized: false, strategy_version: 'cand-1', dataset_version: 'FIXTURE', action: 'WAIT', primary_reason: 'NO_VALID_IMPULSE', layer: 'strategy', strategy_eligible: false,
      reasons: { market: [], strategy: [], gate: [] }, setup: null, plan: null, risk: null, next_required: 'x', sizing: 'REFERENCE_ACCOUNT' },
    m1_shadow: null, scalp_c2: o.c2 ?? null,
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
  h1_h4: { h1: 'UP', h4: 'NONE', conflict: false, alignment: 'COUNTERTREND' }, side: 'SELL', stage: 'WATCH', candidate: 'WATCH SELL', signal: null, missing: 'a closed M1 trigger bar inside the zone band', expires_at: null, plan: null,
  risk_status: 'NOT_EVALUATED: no closed M1 trigger', provenance: null, block_reasons: [], zone: { low: 4103.5, high: 4108 }, directions: {}, events_recent: [], funnel: {}, display_only_forming: null, ...o });
const trig = (bt: number, o: any = {}) => ({ event_id: `scalp-c2-SELL-M1_REJECTION-${bt}-1`, direction: 'SELL', stage: 'M1_TRIGGERED', kind: 'M1_REJECTION', bar_time: bt, known_at: bt + 60, alignment: 'COUNTERTREND', provenance: 'LIVE_FORWARD', current: true, ...o });
const markers = (page: Page) => page.evaluate(() => (window as any).__layers.state().markerTexts as string[]);

test('the seven scalping fields are visible at once on desktop, above the V1 reference panel', async ({ page }) => {
  await useFixture(page, payload({ c2: c2() }));
  await page.goto('/');
  for (const id of ['c2-bias', 'c2-m1', 'c2-m5', 'c2-candidate', 'c2-signal', 'c2-missing', 'c2-risk']) await expect(page.getByTestId(id)).toBeVisible();
  await expect(page.getByTestId('c2-card')).toContainText('SCALPING INTELLIGENCE');
  await expect(page.getByTestId('c2-badge')).toContainText('RESEARCH BETA');
  await expect(page.getByTestId('c2-bias')).toContainText('BEARISH');
  await expect(page.getByTestId('c2-m5')).toContainText('DOWN');
  await expect(page.getByTestId('c2-candidate')).toContainText('WATCH SELL');
  await expect(page.getByTestId('c2-candidate')).toContainText('COUNTERTREND');
  await expect(page.getByTestId('c2-signal')).toContainText('none');
  await expect(page.getByTestId('c2-missing')).toContainText('closed M1 trigger');
  const box = await page.evaluate(() => ({ risk: document.getElementById('c2-risk')!.getBoundingClientRect().bottom, dec: document.getElementById('decision-card')!.getBoundingClientRect().top, vh: innerHeight }));
  expect(box.risk).toBeLessThan(box.vh);                                 // first screen, no scrolling
  expect(box.risk).toBeLessThanOrEqual(box.dec + 1);                     // C2 above the V1 reference
});

test('M1_TRIGGERED is a research trigger, NOT a signal: no BUY/SELL word, no PAPER marker', async ({ page, request }) => {
  const m1 = await candles(request, 'M1');
  const bt = m1[m1.length - 3].time;
  await useFixture(page, payload({ c2: c2({ stage: 'M1_TRIGGERED', candidate: 'WAIT', provenance: 'LIVE_FORWARD', expires_at: bt + 360, trigger: { known_at: bt + 60, window_ends_at: bt + 360 }, risk_status: 'NOT_EVALUATED: outside the entry band', events_recent: [trig(bt)] }) }));
  await page.goto('/');
  await expect(page.getByTestId('c2-candidate')).toContainText('M1 TRIGGER SELL');
  await expect(page.getByTestId('c2-signal')).toContainText('none');
  await expect(page.getByTestId('c2-signal')).not.toContainText('PAPER');
  const mk = await markers(page);
  expect(mk.some((t) => t.startsWith('C2 TRIG'))).toBe(true);
  expect(mk.some((t) => /C2 (BUY|SELL)/.test(t))).toBe(false);
});

test('only a live trigger through the Risk Gate is C2 BUY/SELL PAPER; BLOCKED shows the reason and an amber marker', async ({ page, request }) => {
  const m1 = await candles(request, 'M1');
  const bt = m1[m1.length - 3].time;
  const common = { stage: 'ENTRY_WINDOW', provenance: 'LIVE_FORWARD', expires_at: bt + 360, trigger: { known_at: bt + 60, window_ends_at: bt + 360 }, events_recent: [trig(bt)] };
  const f = await useFixture(page, payload({ c2: c2({ ...common, signal: 'SELL', risk_status: 'PAPER PREFLIGHT PASSED: stop 6.20 USD, net R:R 1.80 (reference account; live quote and real account NOT verified)', plan: { entry: 4105, stop_loss: 4111.2, take_profit: 4092.6, net_rr: 1.8 }, expected_fill: { price: 4104.8, delta_vs_plan_entry: -0.2 } }) }));
  await page.goto('/');
  await expect(page.getByTestId('c2-signal')).toContainText('C2 SELL PAPER');
  await expect(page.getByTestId('c2-risk')).toContainText('PAPER PREFLIGHT PASSED');
  await expect(page.getByTestId('c2-plan')).toContainText('entry 4105.00');
  await expect(page.getByTestId('c2-plan')).toContainText('registered fill = next M1 open 4104.80');
  expect((await markers(page)).some((t) => t === 'C2 SELL PAPER')).toBe(true);
  f.set(payload({ c2: c2({ ...common, signal: 'BLOCKED', block_reasons: ['RISK:SL_TOO_CLOSE'], risk_status: 'BLOCKED: RISK:SL_TOO_CLOSE' }) }));
  await expect(page.getByTestId('c2-signal')).toContainText('C2 BLOCKED');
  await expect(page.getByTestId('c2-risk')).toContainText('BLOCKED: RISK:SL_TOO_CLOSE');
  await expect(page.getByTestId('c2-plan')).toContainText('BLOCKED: RISK:SL_TOO_CLOSE');
  const mk = await markers(page);
  expect(mk).toContain('C2 BLOCKED');
  expect(mk.some((t) => t.includes('PAPER'))).toBe(false);
});

test('a re-derived (historical) trigger is labelled history: no signal, grey marker, honest provenance', async ({ page, request }) => {
  const m1 = await candles(request, 'M1');
  const bt = m1[m1.length - 3].time;
  await useFixture(page, payload({ c2: c2({ stage: 'ENTRY_WINDOW', provenance: 'RE_DERIVED', expires_at: bt + 360, missing: 'this trigger was re-derived', risk_status: 'NOT_EVALUATED: re-derived history', events_recent: [trig(bt, { provenance: 'RE_DERIVED', current: false })] }) }));
  await page.goto('/');
  await expect(page.getByTestId('c2-candidate')).toContainText('HISTORICAL TRIGGER');
  await expect(page.getByTestId('c2-signal')).not.toContainText('PAPER');
  await expect(page.getByTestId('c2-provenance')).toContainText('RE-DERIVED');
  const mk = await markers(page);
  expect(mk.some((t) => t.startsWith('C2 hist'))).toBe(true);
  expect(mk.some((t) => t.startsWith('C2 TRIG') || t.includes('PAPER'))).toBe(false);
});

test('missing section says unavailable; stale clears it; the layer toggle removes the markers', async ({ page, request }) => {
  const m1 = await candles(request, 'M1');
  const bt = m1[m1.length - 3].time;
  const f = await useFixture(page, payload({ c2: c2({ events_recent: [trig(bt)] }) }));
  await page.goto('/');
  await expect(page.getByTestId('c2-candidate')).toContainText('WATCH SELL');
  expect((await markers(page)).some((t) => t.startsWith('C2'))).toBe(true);
  await page.getByTestId('layer-c2').click();
  await expect(page.getByTestId('layer-c2')).toHaveAttribute('aria-pressed', 'false');
  expect((await markers(page)).some((t) => t.startsWith('C2'))).toBe(false);
  await page.getByTestId('layer-c2').click();
  f.set(payload({}));
  await expect(page.getByTestId('c2-signal')).toContainText('scalping layer unavailable');
  await expect(page.getByTestId('c2-plan')).toHaveText('');
  f.set(payload({ c2: c2() }));
  await expect(page.getByTestId('c2-candidate')).toContainText('WATCH SELL');
  await page.evaluate(() => (window as any).__layers.onStale());
  await expect(page.getByTestId('c2-signal')).toContainText('stale');
  await expect(page.getByTestId('c2-bias')).toHaveText('');
});

test('the V1 decision is a collapsible reference panel and remembers its state', async ({ page }) => {
  await useFixture(page, payload({ c2: c2() }));
  await page.goto('/');
  await expect(page.getByTestId('decision-action')).toBeVisible();
  await page.getByTestId('v1-toggle').click();
  await expect(page.getByTestId('v1-toggle')).toHaveAttribute('aria-expanded', 'false');
  await expect(page.getByTestId('decision-action')).toBeHidden();
  await page.reload();
  await expect(page.getByTestId('decision-action')).toBeHidden();
  await page.getByTestId('v1-toggle').press('Enter');
  await expect(page.getByTestId('decision-action')).toBeVisible();
});

for (const [w, h] of [[1440, 900], [1152, 720], [390, 844]]) {
  test(`C2 card fits the viewport ${w}x${h} without horizontal overflow`, async ({ page }) => {
    await page.setViewportSize({ width: w, height: h });
    await useFixture(page, payload({ c2: c2({ signal: 'BLOCKED', stage: 'ENTRY_WINDOW', provenance: 'LIVE_FORWARD', block_reasons: ['RISK:SL_TOO_CLOSE'], risk_status: 'BLOCKED: RISK:SL_TOO_CLOSE', plan: { entry: 4105, stop_loss: 4110, take_profit: 4095, net_rr: 1.8 } }) }));
    await page.goto('/');
    await page.getByTestId('c2-card').scrollIntoViewIfNeeded();
    await expect(page.getByTestId('c2-signal')).toContainText('BLOCKED');
    const m = await page.evaluate(() => { const r = document.getElementById('c2-card')!.getBoundingClientRect(); return { right: r.right, left: r.left, sw: document.documentElement.scrollWidth, vw: innerWidth }; });
    expect(m.left).toBeGreaterThanOrEqual(0);
    expect(m.right).toBeLessThanOrEqual(m.vw + 1);
    expect(m.sw).toBeLessThanOrEqual(m.vw + 16);
  });
}

// ---------------------------------------------------------------- Level 6.5.2: beginner clarity, dictionary, signal details, expiry
const live = (bt: number, o: any = {}) => c2({ stage: 'ENTRY_WINDOW', provenance: 'LIVE_FORWARD', expires_at: bt + 360, trigger: { known_at: bt + 60, window_ends_at: bt + 360 }, events_recent: [trig(bt)],
  evaluated_at: bt + 90, plan: { entry: 4105, stop_loss: 4111.2, take_profit: 4092.6, net_rr: 1.8 }, signal: 'SELL', risk_status: 'PAPER PREFLIGHT PASSED: stop 6.20 USD, net R:R 1.80 (reference account; live quote and real account NOT verified)',
  quote_check: { status: 'IN_BAND', bid: 4104.9, ask: 4105.2, age_s: 1, fill_side_price: 4104.9, delta_vs_planned_entry: -0.1, delta_atr5: -0.02, band_atr5: 0.25 }, ...o });

test('page title is professional (no "slice 1")', async ({ page }) => {
  await useFixture(page, payload({ c2: c2() }));
  await page.goto('/');
  const t = await page.title();
  expect(t).not.toContain('slice');
  expect(t).toContain('Scalping Intelligence');
});

test('C2 PAPER explains in plain Vietnamese that it is simulated, not an order, and that fill is not confirmed', async ({ page, request }) => {
  const m1 = await candles(request, 'M1');
  const bt = m1[m1.length - 3].time;
  await useFixture(page, payload({ c2: live(bt) }));
  await page.goto('/');
  await expect(page.getByTestId('c2-signal')).toContainText('C2 SELL PAPER');
  await expect(page.getByTestId('c2-explain')).toContainText('không phải lệnh mua hoặc xác nhận giá hiện tại có thể khớp');
  await expect(page.getByTestId('c2-risk')).toContainText('PAPER PREFLIGHT PASSED');
  await expect(page.getByTestId('c2-risk')).not.toContainText('Risk Gate');
  const all = await page.getByTestId('c2-card').innerText();
  expect(/SAFE TO (BUY|SELL)|LIVE EXECUTABLE|KHUYẾN NGHỊ/i.test(all)).toBe(false);
});

test('signal details: times, provenance, planned vs current quote, expected fill, NOT VERIFIED readiness, countdown', async ({ page, request }) => {
  const m1 = await candles(request, 'M1');
  const bt = m1[m1.length - 3].time;
  await useFixture(page, payload({ c2: live(bt, { expected_fill: { price: 4104.8, delta_vs_plan_entry: -0.2 } }) }));
  await page.goto('/');
  await page.getByTestId('c2-details-toggle').click();
  const tbl = page.getByTestId('c2-det-table');
  await expect(tbl).toContainText('scalp-c2 / scalp-c2-1');
  await expect(tbl).toContainText('LIVE_FORWARD');
  await expect(tbl).toContainText('4104.90 / 4105.20');
  await expect(tbl).toContainText('IN_BAND');
  await expect(tbl).toContainText('4104.80');
  await expect(tbl).toContainText('NOT VERIFIED');
  await expect(tbl).toContainText('HYPOTHETICAL reference account');
  await expect(page.locator('#c2-cd')).toHaveText(/(\d+:\d\d|đã hết hạn|không xác định)/);
});

test('a superseded paper signal (price left the band) is shown as expired/not current, with no plan', async ({ page, request }) => {
  const m1 = await candles(request, 'M1');
  const bt = m1[m1.length - 3].time;
  await useFixture(page, payload({ c2: live(bt, { signal: null, plan: null, superseded: 'DRIFTED', risk_status: 'NOT CURRENT: DRIFTED', missing: 'the live price moved beyond the registered entry band after the trigger: this paper signal is no longer current' }) }));
  await page.goto('/');
  await expect(page.getByTestId('c2-signal')).toContainText('expired');
  await expect(page.getByTestId('c2-signal')).not.toContainText('PAPER');
  await expect(page.getByTestId('c2-risk')).toContainText('NOT CURRENT');
  await expect(page.getByTestId('c2-plan')).toHaveText('');
  expect((await markers(page)).some((t) => t.includes('PAPER'))).toBe(false);
});

test('an elapsed window shows EXPIRED, not ENTRY WINDOW', async ({ page, request }) => {
  const m1 = await candles(request, 'M1');
  const bt = m1[m1.length - 8].time;
  await useFixture(page, payload({ c2: live(bt, { stage: 'WINDOW_ELAPSED', signal: null, plan: null, risk_status: 'NOT_EVALUATED: window elapsed' }) }));
  await page.goto('/');
  await expect(page.getByTestId('c2-candidate')).toContainText('EXPIRED');
  await expect(page.getByTestId('c2-signal')).toContainText('expired');
});

test('BLOCKED is orange, historical is muted, and the dictionary lists every state with the five answers', async ({ page, request }) => {
  const m1 = await candles(request, 'M1');
  const bt = m1[m1.length - 3].time;
  const f = await useFixture(page, payload({ c2: live(bt, { signal: 'BLOCKED', block_reasons: ['RISK:SL_TOO_CLOSE'], risk_status: 'BLOCKED: RISK:SL_TOO_CLOSE' }) }));
  await page.goto('/');
  expect(await page.getByTestId('c2-signal').getAttribute('data-tone')).toBe('warn');
  f.set(payload({ c2: live(bt, { provenance: 'RE_DERIVED', signal: null, plan: null, events_recent: [trig(bt, { provenance: 'RE_DERIVED', current: false })] }) }));
  await expect(page.getByTestId('c2-candidate')).toContainText('HISTORICAL');
  expect(await page.getByTestId('c2-candidate').getAttribute('data-tone')).toBe('hist');
  await page.getByTestId('c2-dict-toggle').click();
  const body = page.getByTestId('c2-dict-body');
  for (const w of ['WATCH', 'M1 TRIGGER', 'ENTRY WINDOW', 'C2 BUY/SELL PAPER', 'BLOCKED', 'EXPIRED', 'HISTORICAL', 'Đã xảy ra', 'Còn thiếu', 'Có phải quyết định thật', 'Còn hiệu lực', 'Kiểm tra trước']) await expect(body).toContainText(w);
  await expect(body).toContainText('V1 Decision');
  await expect(body).toContainText('V2 Shadow');
  await expect(body).toContainText('C2 Research');
  await expect(body).toContainText('không phải hướng dẫn đặt lệnh');
});

test('paper marker replaces the plain trigger marker on the same bar; BUY research is green', async ({ page, request }) => {
  const m1 = await candles(request, 'M1');
  const bt = m1[m1.length - 3].time;
  await useFixture(page, payload({ c2: live(bt) }));
  await page.goto('/');
  const mk = await markers(page);
  expect(mk).toContain('C2 SELL PAPER');
  expect(mk.filter((t) => t.startsWith('C2 TRIG')).length).toBe(0);
});

test('BUY research is green and SELL research is red', async ({ page }) => {
  const f = await useFixture(page, payload({ c2: c2({ side: 'BUY', candidate: 'WATCH BUY', m5_structure: 'UP' }) }));
  await page.goto('/');
  await expect(page.getByTestId('c2-candidate')).toContainText('WATCH BUY');
  expect(await page.getByTestId('c2-candidate').getAttribute('data-tone')).toBe('up');
  f.set(payload({ c2: c2() }));
  await expect(page.getByTestId('c2-candidate')).toContainText('WATCH SELL');
  expect(await page.getByTestId('c2-candidate').getAttribute('data-tone')).toBe('down');
});

for (const [w, h] of [[1440, 900], [1152, 720], [390, 844]]) {
  test(`all seven scalping fields stay visible at ${w}x${h}`, async ({ page }) => {
    await page.setViewportSize({ width: w, height: h });
    await useFixture(page, payload({ c2: c2() }));
    await page.goto('/');
    for (const id of ['c2-bias', 'c2-m1', 'c2-m5', 'c2-candidate', 'c2-signal', 'c2-missing', 'c2-risk']) await expect(page.getByTestId(id)).toBeVisible();
  });
}
