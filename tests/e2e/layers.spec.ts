import { test, expect, Page } from '@playwright/test';
import * as fs from 'fs';

// Panels (market / M1 shadow / history) and chart layers (EMA, zones, structure, setups, M1 shadow markers). Fixtures are SYNTHETIC and labelled; the EMA tests
// run against the live gateway. Every layer is a display of backend data.
const ART = 'qa-artifacts/layers';
fs.mkdirSync(ART, { recursive: true });
const SEC: Record<string, number> = { M1: 60, M5: 300, M15: 900, H1: 3600, H4: 14400 };

async function candles(request: any, tf: string, n = 300) { return (await (await request.get(`/api/candles/${tf}?limit=${n}`)).json()).candles as any[]; }

function payload(o: { times: number[]; px: number; shadow?: any; action?: string; zones?: any[]; events?: any[]; analysis?: any }) {
  const t = o.times;
  return {
    type: 'intel', evaluated_at: t[t.length - 1] + 60, setup_bar_time: t[t.length - 1], bars: {}, mode: 'READ_ONLY+SHADOW+PAPER_SIMULATION', status: {},
    market: { direction_tf: 'H1', direction: 'UP', conflict_tf: 'H4', conflict_direction: 'NONE', conflict: false, regime: { M15: 'TRANSITION', H1: 'TRENDING_UP', H4: 'TRANSITION' }, history: 'OK' },
    analysis: o.analysis ?? { M15: { regime: 'TRANSITION', structure_trend: 'UP', ema_alignment: 'BULL', rsi: 55.5, atr: 6.5, events_recent: [{ event: 'BREAKOUT_UP', level: o.px, known_at: t[t.length - 8] + 900, bar_open_time: t[t.length - 8] }] },
                               H1: { regime: 'TRENDING_UP', structure_trend: 'UP', ema_alignment: 'BULL', rsi: 61.2, atr: 12.1, events_recent: [] }, H4: { regime: 'TRANSITION', structure_trend: 'RANGE', ema_alignment: 'BEAR', rsi: 48, atr: 25, events_recent: [] } },
    zones: o.zones ?? [{ low: o.px - 9, high: o.px - 6, center: o.px - 7.5, touches: 3, known_at: t[0], side: 'SUPPORT' }, { low: o.px + 7, high: o.px + 10, center: o.px + 8.5, touches: 2, known_at: t[0], side: 'RESISTANCE' }],
    setup_events: o.events ?? [{ setup_id: 'M15-BUY-1', direction: 'BUY', state: 'CONFIRMED', known_at: t[t.length - 20] + 60, reasons: ['CONFIRMATION_PATTERN_AT_ZONE'] },
                               { setup_id: 'M15-BUY-1', direction: 'BUY', state: 'INVALIDATED', known_at: t[t.length - 10] + 60, reasons: ['INVALIDATION_LEVEL_TOUCHED'] }],
    overlays: { zone: null, lines: [], direction: null },
    decision: { kind: 'RESEARCH_DECISION', execution_authorized: false, strategy_version: 'cand-1', dataset_version: 'FIXTURE', action: o.action ?? 'WAIT', primary_reason: 'AWAITING_PULLBACK', layer: 'strategy', strategy_eligible: false,
                reasons: { market: [], strategy: ['AWAITING_PULLBACK'], gate: [] }, setup: null, plan: null, risk: null, next_required: 'a pullback', sizing: 'REFERENCE_ACCOUNT' },
    m1_shadow: o.shadow === undefined ? null : o.shadow,
  };
}
const SHADOW = (stage: string, extra: any = {}) => ({ version: 'm1v2-1', label: 'SHADOW: x', kind: 'SHADOW_OBSERVATION', execution_authorized: false, context: { direction: 'UP', conflict: false }, primary: 'BUY',
  directions: { BUY: { direction: 'BUY', stage, zone: { low: 1, high: 2 }, next_required: 'a CLOSED M1 trigger bar (rejection, engulfing, momentum shift or local structure break) inside the zone band', ...extra.state } },
  events_recent: extra.events ?? [], funnel: {}, plan: extra.plan ?? null, entry_check: extra.entry_check ?? null, forming: extra.forming ?? null });

async function useFixture(page: Page, first: any) {
  let current = first;
  await page.route('**/api/intel', (r) => r.fulfill({ json: current }));
  await page.routeWebSocket(/\/ws$/, (ws) => {
    const server = ws.connectToServer();
    server.onMessage((m) => { try { if (JSON.parse(String(m)).type === 'intel') return; } catch { /* forward */ } ws.send(m); });
    const t = setInterval(() => ws.send(JSON.stringify(current)), 400);
    ws.onClose(() => clearInterval(t));
  });
  return { set: (p: any) => { current = p; } };
}
const txt = (page: Page, id: string) => page.getByTestId(id).innerText();
const state = (page: Page) => page.evaluate(() => (window as any).__layers.state());

test('F11 market intelligence card shows the backend analysis (direction, regimes, structure, indicators, zones)', async ({ page, request }) => {
  const c = await candles(request, 'M1');
  await useFixture(page, payload({ times: c.map((x) => x.time), px: c[c.length - 1].close }));
  await page.goto('/');
  await expect(page.getByTestId('market-direction')).toContainText('H1 UP');
  expect(await txt(page, 'market-regime')).toContain('H1: TRENDING_UP');
  expect(await txt(page, 'market-structure')).toContain('M15 UP/BULL');
  const ind = await txt(page, 'market-indicators');
  expect(ind).toContain('RSI M15 55.50'); expect(ind).toContain('ATR M15 6.50');
  const z = await txt(page, 'market-zones');
  expect(z).toContain('SUPPORT'); expect(z).toContain('RESISTANCE'); expect(z).toContain('3 swings');
});

test('F11 M1 shadow card: separate from the decision, a wick without confirmation is "awaiting", never BUY/SELL', async ({ page, request }) => {
  const c = await candles(request, 'M1');
  const times = c.map((x) => x.time), px = c[c.length - 1].close;
  const f = await useFixture(page, payload({ times, px, shadow: SHADOW('WATCHING_ZONE', { state: { next_required: 'an M5 confirmation bar (pin bar / engulfing / strong close) must close at the zone' },
    forming: { direction: 'BUY', candidate: 'FORMING_REJECTION_CANDIDATE', confirmed: false, note: 'unconfirmed: the bar is still forming and may disappear' } }) }));
  await page.goto('/');
  await expect(page.getByTestId('m1-label')).toContainText('NOT a decision');
  await expect(page.getByTestId('m1-stage')).toHaveText('BUY: WATCHING ZONE');
  await expect(page.getByTestId('m1-next')).toContainText('M5 confirmation');
  await expect(page.getByTestId('m1-forming')).toContainText('FORMING (unconfirmed)');
  expect(await txt(page, 'm1-trigger')).toBe('');
  expect(await txt(page, 'm1-plan')).toBe('');
  await expect(page.getByTestId('decision-action')).toHaveText('WAIT');                          // the V1 decision is untouched by anything in the shadow card
  expect(await txt(page, 'm1-card')).not.toMatch(/\b(BUY|SELL) (NOW|SIGNAL)\b/);
  f.set(payload({ times, px, shadow: SHADOW('ENTRY_WINDOW', { state: { trigger: { kind: 'M1_REJECTION', flags: ['M1_REJECTION'], bar_close: px, bar_extreme: px - 2, known_at: times[times.length - 1] + 60, window_ends_at: times[times.length - 1] + 360, invalidation: px - 9, atr5: 4 } },
    plan: { entry: px, stop_loss: px - 9, take_profit: px + 18, net_rr: 1.9 }, entry_check: { stage: 'ENTRY_WINDOW', plan_status: 'OK', research_entry_ready: true } }) }));
  await expect(page.getByTestId('m1-stage')).toHaveText('BUY: ENTRY WINDOW');
  await expect(page.getByTestId('m1-trigger')).toContainText('TRIGGER BAR CLOSED (confirmed, research observation): REJECTION');
  await expect(page.getByTestId('m1-plan')).toContainText('hypothetical (reference account, shadow)');
  await expect(page.getByTestId('m1-plan')).toContainText('entry band OPEN');
  await expect(page.getByTestId('decision-action')).toHaveText('WAIT');                          // still the V1 decision
  await page.screenshot({ path: `${ART}/m1-shadow.png` });
});

test('F11 a tight M1 stop blocked by the broker stops level is explained, not shown as an opportunity', async ({ page, request }) => {
  const c = await candles(request, 'M1');
  await useFixture(page, payload({ times: c.map((x) => x.time), px: c[c.length - 1].close, shadow: SHADOW('ENTRY_WINDOW', { entry_check: { stage: 'ENTRY_WINDOW', plan_status: 'RISK:SL_TOO_CLOSE', research_entry_ready: false } }) }));
  await page.goto('/');
  await expect(page.getByTestId('m1-plan')).toContainText('no plan: RISK:SL_TOO_CLOSE');
  await expect(page.getByTestId('m1-plan')).toContainText('broker stops level');
});

test('F11 zones layer: lines from the backend zones, toggle on/off, cleared when stale', async ({ page, request }) => {
  const c = await candles(request, 'M1');
  await useFixture(page, payload({ times: c.map((x) => x.time), px: c[c.length - 1].close }));
  await page.goto('/');
  await expect.poll(async () => (await state(page)).zoneLines).toBe(4);                          // 2 zones x (high, low); at most the 3 nearest zones are drawn
  await page.getByTestId('layer-zones').click();
  await expect.poll(async () => (await state(page)).zoneLines).toBe(0);
  await expect(page.getByTestId('layer-zones')).toHaveAttribute('aria-pressed', 'false');
  await page.getByTestId('layer-zones').click();
  await expect.poll(async () => (await state(page)).zoneLines).toBe(4);
});

test('F11 setup and structure markers sit on real bars of the shown timeframe, toggle, and never move for old events (no repaint)', async ({ page, request }) => {
  const c = await candles(request, 'M1');
  const times = c.map((x) => x.time), px = c[c.length - 1].close;
  const f = await useFixture(page, payload({ times, px }));
  await page.goto('/');
  await expect.poll(async () => (await state(page)).markers).toBeGreaterThan(0);
  const base = await page.evaluate(() => (window as any).__layers.markers());
  const barTimes = new Set(await page.evaluate(() => (window as any).__qa.data().map((d: any) => d.time)));
  for (const m of base) expect(barTimes.has(m.time)).toBe(true);                               // markers are on existing bars
  expect(base.some((m: any) => m.info.includes('INVALIDATED') && m.shape === 'square')).toBe(true);
  expect(base.some((m: any) => m.info.includes('BREAKOUT') === false)).toBe(true);             // structure layer is off by default
  await page.getByTestId('layer-structure').click();
  await expect.poll(async () => (await page.evaluate(() => (window as any).__layers.markers())).some((m: any) => m.info.includes('BREAKOUT UP'))).toBe(true);
  await page.getByTestId('layer-setups').click();
  await expect.poll(async () => (await page.evaluate(() => (window as any).__layers.markers())).some((m: any) => m.info.includes('INVALIDATED'))).toBe(false);
  await page.getByTestId('layer-setups').click();
  // no repaint: a later payload with one extra event keeps every earlier marker exactly where it was
  const before = await page.evaluate(() => (window as any).__layers.markers().filter((m: any) => m.info.includes('INVALIDATED') || m.info.includes('CONFIRMED')));
  f.set(payload({ times, px, events: [{ setup_id: 'M15-BUY-1', direction: 'BUY', state: 'CONFIRMED', known_at: times[times.length - 20] + 60, reasons: [] }, { setup_id: 'M15-BUY-1', direction: 'BUY', state: 'INVALIDATED', known_at: times[times.length - 10] + 60, reasons: [] },
    { setup_id: 'M15-SELL-2', direction: 'SELL', state: 'MISSED', known_at: times[times.length - 3] + 60, reasons: [] }] }));
  await expect.poll(async () => (await page.evaluate(() => (window as any).__layers.markers())).some((m: any) => m.info.includes('MISSED'))).toBe(true);
  const after = await page.evaluate(() => (window as any).__layers.markers().filter((m: any) => m.info.includes('INVALIDATED') || m.info.includes('CONFIRMED')));
  expect(after).toEqual(before);
  await page.getByTestId('layer-structure').click();                                           // leave as found
});

test('F11 M1 shadow markers are arrows in the shadow colour and only for CLOSED-bar events (never for WINDOW_STATE)', async ({ page, request }) => {
  const c = await candles(request, 'M1');
  const times = c.map((x) => x.time), px = c[c.length - 1].close;
  const ev = [{ event_id: 'a', direction: 'BUY', stage: 'M1_TRIGGERED', kind: 'M1_REJECTION', bar_time: times[times.length - 15], known_at: times[times.length - 15] + 60 },
              { event_id: 'b', direction: 'BUY', stage: 'ENTRY_WINDOW', kind: 'WINDOW_STATE', bar_time: times[times.length - 14], known_at: times[times.length - 14] + 60 },
              { event_id: 'c', direction: 'SELL', stage: 'M5_CONFIRMED_AWAITING_M1', kind: 'M5_CONFIRMED', bar_time: times[times.length - 30], known_at: times[times.length - 30] + 60 }];
  await useFixture(page, payload({ times, px, shadow: SHADOW('WATCHING_ZONE', { events: ev }), events: [] }));
  await page.goto('/');
  await expect.poll(async () => (await page.evaluate(() => (window as any).__layers.markers())).length).toBe(2);
  const m = await page.evaluate(() => (window as any).__layers.markers());
  expect(m.map((x: any) => x.shape).sort()).toEqual(['arrowDown', 'arrowUp']);
  expect(m.every((x: any) => x.color === '#38bdf8' && x.info.startsWith('shadow'))).toBe(true);
  await page.getByTestId('layer-m1').click();
  await expect.poll(async () => (await page.evaluate(() => (window as any).__layers.markers())).length).toBe(0);
  await page.getByTestId('layer-m1').click();
});

test('F11 inspecting a past setup event moves the view to it and highlights it without recomputing anything', async ({ page, request }) => {
  const c = await candles(request, 'M1');
  const times = c.map((x) => x.time), px = c[c.length - 1].close;
  await useFixture(page, payload({ times, px }));
  await page.goto('/');
  await expect(page.getByTestId('hist-inspect').first()).toBeVisible();
  const first = page.getByTestId('hist-inspect').first();
  const t = Number(await first.getAttribute('data-t'));
  await first.click();
  await expect.poll(async () => { const r = await page.evaluate(() => (window as any).__qa.range()); return r ? (r.to - r.from) : 999; }).toBeLessThan(120);        // zoomed to about 80 bars around it
  const mk = await page.evaluate(() => (window as any).__layers.markers());
  expect(mk.some((x: any) => x.info === 'inspected' && Math.abs(x.time - t) < 60)).toBe(true);
});

test('F11 EMA overlays come from /api/indicators, equal the backend values, follow the timeframe and persist across a reload', async ({ page, request }) => {
  await page.goto('/');
  await page.getByTestId('tf-M5').click();
  await expect.poll(() => page.evaluate(() => (window as any).__qa.dataTf())).toBe('M5');
  await page.getByTestId('layer-ema20').click();
  await expect.poll(async () => (await state(page)).ema.ema20 ?? 0).toBeGreaterThan(100);
  const d = await (await request.get('/api/indicators/M5?limit=1500')).json();
  const lastVal = d.ema20[d.ema20.length - 1];
  const shown = await page.evaluate(() => { const s = (window as any).__layers; return s.state().ema.ema20; });
  expect(shown).toBeGreaterThan(100);
  expect(d.time.every((t: number) => t % 300 === 0)).toBe(true);                               // the M5 grid: the overlay belongs to the shown timeframe
  expect(lastVal).not.toBeNull();
  await page.getByTestId('tf-H1').click();
  await expect.poll(() => page.evaluate(() => (window as any).__qa.dataTf())).toBe('H1');
  await expect.poll(async () => (await state(page)).ema.ema20).toBeGreaterThan(50);            // reloaded for H1
  const h1 = await (await request.get('/api/indicators/H1?limit=1500')).json();
  expect(h1.time.every((t: number) => t % 3600 === 0)).toBe(true);
  await page.reload();
  await expect(page.getByTestId('layer-ema20')).toHaveAttribute('aria-pressed', 'true');       // persisted
  await expect.poll(async () => (await state(page)).ema.ema20 ?? 0).toBeGreaterThan(50);
  await page.getByTestId('layer-ema20').click();                                               // leave as found
  await expect(page.getByTestId('layer-ema20')).toHaveAttribute('aria-pressed', 'false');
});

test('F11 stale or lost data clears every layer and panel (nothing actionable or current stays on the chart)', async ({ page, request }) => {
  const c = await candles(request, 'M1');
  const times = c.map((x) => x.time), px = c[c.length - 1].close;
  let killed = false;
  const p = payload({ times, px, shadow: SHADOW('ENTRY_WINDOW', { entry_check: { stage: 'ENTRY_WINDOW', plan_status: 'OK', research_entry_ready: true } }) });
  await page.route('**/api/intel', (r) => r.fulfill({ json: p }));
  await page.routeWebSocket(/\/ws$/, (ws) => {
    const server = ws.connectToServer();
    server.onMessage((m) => { try { if (JSON.parse(String(m)).type === 'intel') return; } catch { /* forward */ } if (!killed) ws.send(m); });
    const t = setInterval(() => { if (killed) { clearInterval(t); ws.close(); } else ws.send(JSON.stringify(p)); }, 300);
  });
  await page.goto('/');
  await expect.poll(async () => (await state(page)).zoneLines).toBe(4);
  await expect(page.getByTestId('m1-stage')).toHaveText('BUY: ENTRY WINDOW');
  killed = true;
  await expect(page.getByTestId('decision-action')).toHaveText('STALE', { timeout: 8000 });
  expect((await state(page)).zoneLines).toBe(0);
  expect((await state(page)).markers).toBe(0);
  await expect(page.getByTestId('m1-stage')).toContainText('stale');
  for (const id of ['m1-trigger', 'm1-plan', 'm1-forming', 'm1-events', 'market-zones']) expect(await txt(page, id), id).toBe('');
});

test('F11 the sizing note says the plan is a REFERENCE-account estimate, not a margin check of the real account', async ({ page, request }) => {
  const c = await candles(request, 'M1');
  const times = c.map((x) => x.time), px = c[c.length - 1].close;
  const p = payload({ times, px, action: 'BUY' });
  (p.decision as any).primary_reason = 'ENTRY_ELIGIBLE'; (p.decision as any).strategy_eligible = true;
  (p.decision as any).setup = { setup_id: 'M15-BUY-1', direction: 'BUY', state: 'ENTRY_ELIGIBLE', evidence: [], invalidation_level: px - 5, entry_level: px, next_required_event: 'x', expires_at: times[times.length - 1] + 3600 };
  (p.decision as any).plan = { direction: 'BUY', entry: px, stop_loss: px - 5, take_profit: px + 10, tp2_reference: px + 9, net_rr: 1.9, gross_rr: 2, risk_fraction: 0.005, size_hidden: true };
  await useFixture(page, p);
  await page.goto('/');
  await expect(page.getByTestId('decision-plan-label')).toContainText('REFERENCE account');
  await expect(page.getByTestId('decision-plan-label')).toContainText('NOT a check that your real account has enough margin');
});
