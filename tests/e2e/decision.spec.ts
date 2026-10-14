import { test, expect, Page } from '@playwright/test';
import * as fs from 'fs';

const ART = 'qa-artifacts/decision';
fs.mkdirSync(ART, { recursive: true });

type Opt = { action: string; primary: string; layer?: string; eligible?: boolean; setup?: any; plan?: any; reasons?: any; overlays?: any; market?: any; seq?: number; next?: string };
function payload(o: Opt) {
  return {
    type: 'intel', ...(o.seq != null ? { seq: o.seq } : {}), evaluated_at: 1_791_925_680, setup_bar_time: 1_791_924_900, bars: { M15: 2000, H1: 2000, H4: 2000 }, mode: 'READ_ONLY+SHADOW+PAPER_SIMULATION',
    market: o.market ?? { direction_tf: 'H1', direction: 'UP', conflict_tf: 'H4', conflict_direction: 'NONE', conflict: false, regime: { M15: 'TRANSITION', H1: 'TRENDING_UP', H4: 'TRANSITION' }, history: 'OK' },
    status: { decision_context: o.action === 'BUY' ? 'ENTRY_ELIGIBLE' : 'WAIT' }, analysis: {}, setup_events: [],
    overlays: o.overlays ?? { zone: null, lines: [], direction: null },
    decision: {
      kind: 'RESEARCH_DECISION', execution_authorized: false, strategy_version: 'cand-1[setup-1+risk-1+gate-1]', dataset_version: 'ds-test',
      action: o.action, primary_reason: o.primary, layer: o.layer ?? 'strategy', strategy_eligible: o.eligible ?? false,
      reasons: o.reasons ?? { market: [], strategy: [o.primary], gate: [] }, setup: o.setup ?? null, plan: o.plan ?? null, risk: null,
      next_required: o.next ?? (o.setup ? o.setup.next_required_event : 'an impulse leg in the H1 direction, then a pullback of at least 0.5 ATR from its extreme'),
    },
  };
}
const SETUP = { setup_id: 'M15-BUY-1791920000-4100.00', direction: 'BUY', state: 'ENTRY_ELIGIBLE', evidence: ['CONTEXT:higher-timeframe BUY direction', 'ZONE:2 confirmed swings, [4101.10, 4102.40]', 'CONFIRMATION:bullish pattern bar closed at 4103.20'],
  invalidation_level: 4099.8, entry_level: 4103.2, expires_at: 1_791_928_800, entry_window_ends_at: 1_791_926_400, next_required_event: 'entry decision (risk gate) while price stays inside the band and above the invalidation level' };
const PLAN = { direction: 'BUY', entry: 4103.2, stop_loss: 4099.8, take_profit: 4118.4, tp2_reference: 4110.0, lot: 0.17, net_rr: 3.4, gross_rr: 4.1, risk_fraction: 0.005 };
const OV = { zone: { low: 4101.1, high: 4102.4 }, lines: [{ kind: 'ENTRY', price: 4103.2 }, { kind: 'SL', price: 4099.8 }, { kind: 'TP', price: 4118.4 }], direction: 'BUY' };

// Serve fixtures through the page's REAL websocket handler (and the initial fetch), dropping the live server's own intel frames.
async function useFixture(page: Page, first: any) {
  let current: any = first;
  let paused = false;
  await page.route('**/api/intel', (r) => r.fulfill({ json: current }));
  await page.routeWebSocket(/\/ws$/, (ws) => {
    const server = ws.connectToServer();
    server.onMessage((m) => { try { if (JSON.parse(String(m)).type === 'intel') return; } catch { /* forward non-JSON */ } ws.send(m); });
    ws.onMessage((m) => server.send(m));
    const timer = setInterval(() => { if (!paused) ws.send(JSON.stringify(current)); }, 400);
    ws.onClose(() => clearInterval(timer));
  });
  return { set: (p: any) => { current = p; }, pause: () => { paused = true; } };
}
const txt = (page: Page, id: string) => page.getByTestId(id).innerText();

test('F5 WAIT: names the strategy reason, shows no plan and draws no levels', async ({ page }) => {
  await useFixture(page, payload({ action: 'WAIT', primary: 'AWAITING_PULLBACK' }));
  await page.goto('/');
  await expect(page.getByTestId('decision-action')).toHaveText('WAIT');
  await expect(page.getByTestId('decision-primary')).toContainText('AWAITING_PULLBACK');
  await expect(page.getByTestId('decision-primary')).toContainText('strategy reason');
  await expect(page.getByTestId('decision-eligible')).toContainText('Strategy eligible: no');
  await expect(page.getByTestId('decision-plan')).toContainText('No trade plan');
  await expect(page.getByTestId('decision-setup')).toContainText('No active setup');
  await expect(page.getByTestId('decision-next')).toContainText('pullback of at least 0.5 ATR');
  expect(await page.evaluate(() => (window as any).__qa.lines())).toEqual([]);
  await page.screenshot({ path: `${ART}/wait.png` });
});

test('F5 BUY levels near the live price are really drawn inside the visible chart (pixel position), not just created', async ({ page, request }) => {
  const last = (await (await request.get('/api/candles/M1?limit=1')).json()).candles[0].close as number;
  const r2 = (v: number) => Math.round(v * 100) / 100;
  const lv = { entry: r2(last), sl: r2(last - 3), tp: r2(last + 8), zlo: r2(last - 2.6), zhi: r2(last - 1.9) };
  await useFixture(page, payload({ action: 'BUY', primary: 'ENTRY_ELIGIBLE', eligible: true,
    setup: { ...SETUP, entry_level: lv.entry, invalidation_level: lv.sl }, plan: { ...PLAN, entry: lv.entry, stop_loss: lv.sl, take_profit: lv.tp },
    overlays: { zone: { low: lv.zlo, high: lv.zhi }, lines: [{ kind: 'ENTRY', price: lv.entry }, { kind: 'SL', price: lv.sl }, { kind: 'TP', price: lv.tp }], direction: 'BUY' } }));
  await page.goto('/');
  await expect.poll(() => page.evaluate(() => (window as any).__qa.lines().length)).toBe(5);
  const ys = await page.evaluate(() => (window as any).__qa.lines().map((l: any) => ({ title: l.title, price: l.price, y: (window as any).__qa.lineY(l.price) })));
  const box = await page.getByTestId('chart').boundingBox();
  for (const l of ys) { expect(l.y, `${l.title} has no screen position`).not.toBeNull(); expect(l.y).toBeGreaterThan(0); expect(l.y).toBeLessThan(box!.height - 30); }
  const y = Object.fromEntries(ys.map((l: any) => [l.title, l.y]));
  expect(y.TP).toBeLessThan(y.ENTRY); expect(y.ENTRY).toBeLessThan(y.SL);                  // screen y grows downwards: TP above entry above SL for a BUY
  expect(y['ZONE hi']).toBeLessThan(y['ZONE lo']);
  await page.screenshot({ path: `${ART}/buy-levels-on-chart.png` });
});

test('F5 BUY: shows entry, SL, TP, R:R, lot, risk %, the next required event, and the backend levels as price lines', async ({ page }) => {
  await useFixture(page, payload({ action: 'BUY', primary: 'ENTRY_ELIGIBLE', eligible: true, setup: SETUP, plan: PLAN, overlays: OV }));
  await page.goto('/');
  await expect(page.getByTestId('decision-action')).toHaveText('BUY');
  await expect(page.getByTestId('decision-action')).toHaveClass(/act-BUY/);
  const plan = await txt(page, 'decision-plan');
  for (const s of ['4103.20', '4099.80', '4118.40', '0.17', '3.40', '4.10', '0.50% of equity', 'not an exit rule']) expect(plan).toContain(s);
  const setup = await txt(page, 'decision-setup');
  for (const s of ['ENTRY_ELIGIBLE', 'M15-BUY-1791920000-4100.00', 'CONFIRMATION:bullish pattern bar closed at 4103.20', 'invalidation 4099.80']) expect(setup).toContain(s);
  await expect(page.getByTestId('decision-next')).toContainText('Next required');
  await expect(page.getByTestId('decision-expiry')).toContainText('expires ~22:00');
  await expect(page.getByTestId('decision-expiry')).toContainText('entry window closes ~21:20');
  await expect(page.getByTestId('decision-plan-label')).toContainText('hypothetical');
  await expect(page.getByTestId('decision-meta')).toContainText('EXECUTION NOT AUTHORIZED');
  await expect.poll(() => page.evaluate(() => (window as any).__qa.lines().length)).toBe(5);
  const lines = await page.evaluate(() => (window as any).__qa.lines());
  const by = Object.fromEntries(lines.map((l: any) => [l.title, l.price]));
  expect(by).toEqual({ 'ZONE hi': 4102.4, 'ZONE lo': 4101.1, ENTRY: 4103.2, SL: 4099.8, TP: 4118.4 });
  await page.screenshot({ path: `${ART}/buy.png` });
});

test('F5 BLOCKED: eligible setup stays visible as eligible, the gate reason is shown, no BUY is displayed', async ({ page }) => {
  await useFixture(page, payload({ action: 'BLOCKED', primary: 'SPREAD_TOO_WIDE(0.60 ATR > 0.3)', layer: 'gate', eligible: true, setup: SETUP, overlays: OV,
    reasons: { market: [], strategy: [], gate: ['SPREAD_TOO_WIDE(0.60 ATR > 0.3)'] } }));
  await page.goto('/');
  await expect(page.getByTestId('decision-action')).toHaveText('BLOCKED');
  await expect(page.getByTestId('decision-eligible')).toContainText('Strategy eligible: YES');
  await expect(page.getByTestId('decision-eligible')).toContainText('BLOCKED by gate/risk: NOT ELIGIBLE');
  await expect(page.getByTestId('decision-primary')).toContainText('SPREAD_TOO_WIDE');
  await expect(page.getByTestId('decision-layers')).toContainText('gate: SPREAD_TOO_WIDE');
  await expect(page.getByTestId('decision-plan')).toContainText('No trade plan');
  expect(await txt(page, 'decision-action')).not.toMatch(/BUY|SELL/);
});

test('F5 stale data: WAIT with DATA_STALE (no new decision), and the gate reason is not hidden', async ({ page }) => {
  await useFixture(page, payload({ action: 'WAIT', primary: 'DATA_STALE', layer: 'gate', eligible: true, setup: SETUP, reasons: { market: [], strategy: ['ENTRY_WINDOW_NOT_OPEN'], gate: ['DATA_STALE'] } }));
  await page.goto('/');
  await expect(page.getByTestId('decision-action')).toHaveText('STALE');           // the badge never says WAIT/BUY/SELL for data the backend calls stale
  await expect(page.getByTestId('decision-primary')).toContainText('DATA_STALE');
  await expect(page.getByTestId('decision-layers')).toContainText('gate: DATA_STALE');
  for (const id of ['decision-plan', 'decision-setup']) expect(await txt(page, id)).toBe('');
  expect(await page.evaluate(() => (window as any).__qa.lines())).toEqual([]);
});

test('F5 SELL is displayed from the backend record (colour class and direction), the page computes nothing', async ({ page }) => {
  const sell = payload({ action: 'SELL', primary: 'ENTRY_ELIGIBLE', eligible: true, setup: { ...SETUP, direction: 'SELL', setup_id: 'M15-SELL-1-4200.00', invalidation_level: 4106.0, entry_level: 4100.0 },
    plan: { ...PLAN, direction: 'SELL', entry: 4100.0, stop_loss: 4106.0, take_profit: 4082.0 }, overlays: { zone: { low: 4104.0, high: 4105.5 }, lines: [{ kind: 'ENTRY', price: 4100 }, { kind: 'SL', price: 4106 }, { kind: 'TP', price: 4082 }], direction: 'SELL' } });
  await useFixture(page, sell);
  await page.goto('/');
  await expect(page.getByTestId('decision-action')).toHaveText('SELL');
  await expect(page.getByTestId('decision-action')).toHaveClass(/act-SELL/);
  await expect(page.getByTestId('decision-setup')).toContainText('SELL');
});

test('F5 the displayed action always equals the backend action, over a sequence of states (no front-end decision logic)', async ({ page }) => {
  const seq = [payload({ action: 'WAIT', primary: 'NO_DIRECTION', layer: 'market' }), payload({ action: 'BUY', primary: 'ENTRY_ELIGIBLE', eligible: true, setup: SETUP, plan: PLAN, overlays: OV }),
    payload({ action: 'BLOCKED', primary: 'MARKET_CLOSED', layer: 'gate', eligible: true, setup: SETUP }), payload({ action: 'WAIT', primary: 'SIGNAL_CONFLICT' }),
    payload({ action: 'SELL', primary: 'ENTRY_ELIGIBLE', eligible: true, setup: { ...SETUP, direction: 'SELL' }, plan: { ...PLAN, direction: 'SELL' } })];
  const fx = await useFixture(page, seq[0]);
  await page.goto('/');
  for (const p of seq) {
    fx.set(p);
    await expect(page.getByTestId('decision-action')).toHaveText(p.decision.action, { timeout: 5000 });
    await expect(page.getByTestId('decision-primary')).toContainText(p.decision.primary_reason);
  }
});

test('F5 a decision that stops refreshing is marked stale and its levels are removed (no old signal left on the chart)', async ({ page }) => {
  const fx = await useFixture(page, payload({ action: 'BUY', primary: 'ENTRY_ELIGIBLE', eligible: true, setup: SETUP, plan: PLAN, overlays: OV }));
  await page.goto('/');
  await expect.poll(() => page.evaluate(() => (window as any).__qa.lines().length)).toBe(5);
  fx.pause();
  await expect(page.getByTestId('decision-card')).toHaveClass(/stale/, { timeout: 20_000 });
  await expect(page.getByTestId('decision-primary')).toContainText('DECISION NOT REFRESHED');
  expect(await page.evaluate(() => (window as any).__qa.lines())).toEqual([]);
  await page.screenshot({ path: `${ART}/stale-decision.png` });
});

test('F5 server-provided text is escaped (no HTML injection through setup ids, evidence or reasons)', async ({ page }) => {
  const evil = '<img src=x onerror="window.__pwned=1">';
  await useFixture(page, payload({ action: 'WAIT', primary: evil, setup: { ...SETUP, setup_id: evil, evidence: [evil] }, reasons: { market: [evil], strategy: [evil], gate: [evil] } }));
  await page.goto('/');
  await expect(page.getByTestId('decision-setup')).toContainText('<img src=x');
  expect(await page.evaluate(() => (window as any).__pwned)).toBeUndefined();
  expect(await page.locator('[data-testid=decision-card] img').count()).toBe(0);
});

test('F5 live backend: the panel shows exactly the backend record, with a primary reason, versions and no execution authority', async ({ page, request }) => {
  await page.goto('/');
  await expect.poll(async () => (await page.getByTestId('decision-action').innerText()).trim(), { timeout: 20_000 }).toMatch(/^(BUY|SELL|WAIT|BLOCKED)$/);
  const api = await (await request.get('/api/intel')).json();
  expect(api.decision.execution_authorized).toBe(false);
  expect(api.mode).toBe('READ_ONLY+SHADOW+PAPER_SIMULATION');
  const shown = await page.evaluate(() => (window as any).__qa.intel());
  expect(shown.decision.strategy_version).toBe(api.decision.strategy_version);
  expect(await txt(page, 'decision-action')).toBe(shown.decision.action);                       // the DOM equals the last frame the page received
  expect((await txt(page, 'decision-primary')).length).toBeGreaterThan(3);
  expect(JSON.stringify(api)).not.toMatch(/risk_budget|estimated_loss_at_sl|margin_estimate|free_margin|equity/);   // no account figures leave the backend
  await page.screenshot({ path: `${ART}/live.png` });
});

test('F5 BLOCKED that still carries a plan (e.g. RR_TOO_LOW) is displayed as BLOCKED, never as the plan direction', async ({ page }) => {
  await useFixture(page, payload({ action: 'BLOCKED', primary: 'RISK:RR_TOO_LOW: net 1.10 < 1.5 (gross 1.3)', layer: 'gate', eligible: true, setup: SETUP,
    plan: { ...PLAN, net_rr: 1.1, gross_rr: 1.3 }, overlays: OV, reasons: { market: [], strategy: [], gate: ['RISK:RR_TOO_LOW: net 1.10 < 1.5 (gross 1.3)'] } }));
  await page.goto('/');
  await expect(page.getByTestId('decision-action')).toHaveText('BLOCKED');
  await expect(page.getByTestId('decision-action')).toHaveClass(/act-BLOCKED/);
  await expect(page.getByTestId('decision-action')).not.toHaveClass(/act-BUY/);
  await expect(page.getByTestId('decision-primary')).toContainText('RR_TOO_LOW');
});

test('F5 a stale decision no longer shows BUY/SELL at all: the action reads STALE and the levels are gone', async ({ page }) => {
  const fx = await useFixture(page, payload({ action: 'BUY', primary: 'ENTRY_ELIGIBLE', eligible: true, setup: SETUP, plan: PLAN, overlays: OV }));
  await page.goto('/');
  await expect(page.getByTestId('decision-action')).toHaveText('BUY');
  fx.pause();
  await expect(page.getByTestId('decision-action')).toHaveText('STALE', { timeout: 20_000 });
  await expect(page.getByTestId('decision-action')).toHaveClass(/act-STALE/);
  expect(await txt(page, 'decision-action')).not.toMatch(/BUY|SELL/);
  expect(await page.evaluate(() => (window as any).__qa.lines())).toEqual([]);
});

test('F5 a cached payload that is already old when it arrives is shown as STALE immediately (initial fetch and first frame)', async ({ page }) => {
  await useFixture(page, { ...payload({ action: 'BUY', primary: 'ENTRY_ELIGIBLE', eligible: true, setup: SETUP, plan: PLAN, overlays: OV }), intel_age_s: 90 });
  await page.goto('/');
  await expect(page.getByTestId('decision-action')).toHaveText('STALE', { timeout: 5000 });
  await expect(page.getByTestId('decision-primary')).toContainText('NOT REFRESHED');
  expect(await page.evaluate(() => (window as any).__qa.lines())).toEqual([]);
});

test('F5 an engine error record is displayed as WAIT / INTEL_ENGINE_ERROR with no plan and no levels', async ({ page }) => {
  const err = payload({ action: 'WAIT', primary: 'INTEL_ENGINE_ERROR', layer: 'gate', reasons: { market: [], strategy: [], gate: ['INTEL_ENGINE_ERROR:RuntimeError'] } });
  await useFixture(page, err);
  await page.goto('/');
  await expect(page.getByTestId('decision-action')).toHaveText('WAIT');
  await expect(page.getByTestId('decision-primary')).toContainText('INTEL_ENGINE_ERROR');
  await expect(page.getByTestId('decision-layers')).toContainText('gate: INTEL_ENGINE_ERROR:RuntimeError');
  await expect(page.getByTestId('decision-plan')).toContainText('No trade plan');
});


test('F6 BLOCKED with hypothetical levels: labelled NOT ELIGIBLE, no size, dashed grey lines titled NOT ELIGIBLE (never the live ENTRY/SL/TP look)', async ({ page }) => {
  const hypo = { direction: 'BUY', entry: 4103.2, stop_loss: 4099.8, take_profit: 4112.0, tp2_reference: 4110.0, net_rr: 1.2, gross_rr: 1.6, risk_fraction: 0.005 };   // no `lot`: the backend omits it
  await useFixture(page, payload({ action: 'BLOCKED', primary: 'RISK:RR_TOO_LOW', layer: 'gate', eligible: true, setup: SETUP, plan: hypo, overlays: OV,
    reasons: { market: [], strategy: [], gate: ['RISK:RR_TOO_LOW'] } }));
  await page.goto('/');
  await expect(page.getByTestId('decision-action')).toHaveText('BLOCKED');
  await expect(page.getByTestId('decision-plan-label')).toContainText('NOT ELIGIBLE');
  const plan = await txt(page, 'decision-plan');
  expect(plan).not.toMatch(/lot|of equity/); expect(plan).toContain('4103.20');
  await expect.poll(() => page.evaluate(() => (window as any).__qa.lines().length)).toBe(5);
  const titles = await page.evaluate(() => (window as any).__qa.lines().map((l: any) => l.title));
  expect(titles).toContain('NOT ELIGIBLE · ENTRY'); expect(titles).not.toContain('ENTRY'); expect(titles).not.toContain('TP');
  await page.screenshot({ path: `${ART}/blocked-not-eligible.png` });
});

test('F6 an older frame (lower seq) never overwrites a newer decision', async ({ page }) => {
  const f = await useFixture(page, payload({ action: 'BUY', primary: 'ENTRY_ELIGIBLE', eligible: true, setup: SETUP, plan: PLAN, overlays: OV, seq: 10 }));
  await page.goto('/');
  await expect(page.getByTestId('decision-action')).toHaveText('BUY');
  await page.waitForTimeout(1200);                       // let a websocket frame with seq 10 arrive after the socket opened (the socket resets the guard on connect)
  f.set(payload({ action: 'WAIT', primary: 'NO_DIRECTION', layer: 'market', seq: 4 }));            // an old frame arrives late
  await page.waitForTimeout(1500);
  await expect(page.getByTestId('decision-action')).toHaveText('BUY');
  f.set(payload({ action: 'WAIT', primary: 'NO_DIRECTION', layer: 'market', seq: 11 }));
  await expect(page.getByTestId('decision-action')).toHaveText('WAIT');
});

test('F6 losing the websocket blanks every part of the decision (nothing actionable stays on screen)', async ({ page }) => {
  let killed = false;
  await page.route('**/api/intel', (r) => r.fulfill({ json: payload({ action: 'BUY', primary: 'ENTRY_ELIGIBLE', eligible: true, setup: SETUP, plan: PLAN, overlays: OV }) }));
  await page.routeWebSocket(/\/ws$/, (ws) => {
    const server = ws.connectToServer();
    server.onMessage((m) => { try { if (JSON.parse(String(m)).type === 'intel') return; } catch { /* forward */ } if (!killed) ws.send(m); });
    const t = setInterval(() => { if (killed) { clearInterval(t); ws.close(); } else ws.send(JSON.stringify(payload({ action: 'BUY', primary: 'ENTRY_ELIGIBLE', eligible: true, setup: SETUP, plan: PLAN, overlays: OV }))); }, 300);
  });
  await page.goto('/');
  await expect(page.getByTestId('decision-action')).toHaveText('BUY');
  killed = true;
  await expect(page.getByTestId('decision-action')).toHaveText('STALE', { timeout: 8000 });
  for (const id of ['decision-plan', 'decision-setup', 'decision-eligible', 'decision-next']) expect(await txt(page, id), id).toBe('');
  expect(await page.evaluate(() => (window as any).__qa.lines())).toEqual([]);
});

test('F6 terminal setup events (INVALIDATED / MISSED) are listed with their reason and time, never hidden behind a bare WAIT (backend order is chronological, shown newest first)', async ({ page }) => {
  const p = payload({ action: 'WAIT', primary: 'AWAITING_PULLBACK' });
  (p as any).setup_events = [
    { setup_id: 'M15-SELL-1791890000-4150.00', direction: 'SELL', state: 'MISSED', prev_state: 'ENTRY_WINDOW', known_at: 1_791_915_000, reasons: ['PRICE_RAN_AWAY'] },
    { setup_id: 'M15-BUY-1791900000-4090.00', direction: 'BUY', state: 'INVALIDATED', prev_state: 'AWAITING_CONFIRMATION', known_at: 1_791_924_900, reasons: ['ZONE_FAILED'] }];
  await useFixture(page, p);
  await page.goto('/');
  const t = await txt(page, 'decision-events');
  expect(t).toContain('INVALIDATED (ZONE_FAILED)'); expect(t).toContain('MISSED (PRICE_RAN_AWAY)'); expect(t.indexOf('INVALIDATED')).toBeLessThan(t.indexOf('MISSED'));   // newest first
  await expect(page.getByTestId('decision-action')).toHaveText('WAIT');
});

test('F6 server text in setup events is escaped (no HTML injection through setup ids or reasons)', async ({ page }) => {
  const p = payload({ action: 'WAIT', primary: 'AWAITING_PULLBACK' });
  (p as any).setup_events = [{ setup_id: '<img src=x onerror="window.__xss=1">', direction: 'BUY', state: 'INVALIDATED', known_at: 1_791_924_900, reasons: ['<b>bold</b>'] }];
  await useFixture(page, p);
  await page.goto('/');
  await expect(page.getByTestId('decision-events')).toContainText('<img src=x');
  expect(await page.evaluate(() => (window as any).__xss)).toBeUndefined();
  expect(await page.getByTestId('decision-events').locator('img').count()).toBe(0);
  expect(await page.getByTestId('decision-events').locator('b').count()).toBe(1);                       // only the panel's own heading, never the injected <b>
});

test('F6 losing the websocket also blanks the recent setup events', async ({ page }) => {
  let killed = false;
  const mk = () => { const p = payload({ action: 'BUY', primary: 'ENTRY_ELIGIBLE', eligible: true, setup: SETUP, plan: PLAN, overlays: OV }); (p as any).setup_events = [{ setup_id: 'M15-BUY-1', direction: 'BUY', state: 'INVALIDATED', known_at: 1_791_924_900, reasons: ['ZONE_FAILED'] }]; return p; };
  await page.route('**/api/intel', (r) => r.fulfill({ json: mk() }));
  await page.routeWebSocket(/\/ws$/, (ws) => {
    const server = ws.connectToServer();
    server.onMessage((m) => { try { if (JSON.parse(String(m)).type === 'intel') return; } catch { /* forward */ } if (!killed) ws.send(m); });
    const t = setInterval(() => { if (killed) { clearInterval(t); ws.close(); } else ws.send(JSON.stringify(mk())); }, 300);
  });
  await page.goto('/');
  await expect(page.getByTestId('decision-events')).toContainText('INVALIDATED');
  killed = true;
  await expect(page.getByTestId('decision-action')).toHaveText('STALE', { timeout: 8000 });
  expect(await txt(page, 'decision-events')).toBe('');
});

test('F6 on a 390x844 phone the decision badge and reason are visible without scrolling and nothing overflows horizontally', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await useFixture(page, payload({ action: 'BUY', primary: 'ENTRY_ELIGIBLE', eligible: true, setup: SETUP, plan: PLAN, overlays: OV }));
  await page.goto('/');
  await expect(page.getByTestId('decision-action')).toHaveText('BUY');
  const m = await page.evaluate(() => ({ actionBottom: document.getElementById('d-action')!.getBoundingClientRect().bottom, primaryBottom: document.getElementById('d-primary')!.getBoundingClientRect().bottom,
    overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth, chartH: document.getElementById('chart')!.getBoundingClientRect().height }));
  expect(m.primaryBottom).toBeLessThan(844); expect(m.overflow).toBe(false); expect(m.chartH).toBeLessThan(400); expect(m.chartH).toBeGreaterThan(250);
});
