import { test, expect, Page } from '@playwright/test';
import * as fs from 'fs';

// Level 6.4: hero chips, analysis clock, alerts (toast always; sound and desktop notification opt-in), collapsible More panel, sidebar toggle, M1 price-action lines, readable sizes.
// Fixtures are SYNTHETIC and labelled; candles come from the live gateway.
const ART = 'qa-artifacts/redesign';
fs.mkdirSync(ART, { recursive: true });
async function candles(request: any, tf: string, n = 400) { return (await (await request.get(`/api/candles/${tf}?limit=${n}`)).json()).candles as any[]; }
const PLAN = { direction: 'BUY', entry: 4103.2, stop_loss: 4099.8, take_profit: 4118.4, net_rr: 3.4, gross_rr: 4.1, size_hidden: true, risk_fraction: 0.005 };
const ev = (o: any) => ({ log_schema: 1, kind: 'RESEARCH_DECISION_EVENT', execution_authorized: false, source_timeframe: 'M15', strategy_version: 'cand-1', dataset_version: 'FIXTURE', primary_reason: 'ENTRY_ELIGIBLE', risk_status: 'OK', gates: [], plan: PLAN,
  valid: { expires_at: o.published_at + 7200, invalidation_level: 4099.8 }, price: 4103.2, evaluated_at: o.published_at, known_at: o.published_at - 5, publish_latency_s: 5, ...o });
function payload(o: { events?: any[]; current?: string | null; evaluated_at?: number; shadow?: any; market?: any; decision?: any }) {
  return {
    type: 'intel', evaluated_at: o.evaluated_at ?? 1_791_925_680, setup_bar_time: 1, bars: {}, mode: 'READ_ONLY+SHADOW+PAPER_SIMULATION', status: {}, analysis: {}, zones: [],
    market: o.market ?? { direction_tf: 'H1', direction: 'DOWN', conflict_tf: 'H4', conflict_direction: 'DOWN', conflict: false, regime: {}, history: 'OK' },
    setup_events: [], setup_events_total: 0, overlays: { zone: null, lines: [], direction: null }, v1_events: o.events ?? [], v1_current_id: o.current ?? null,
    decision: o.decision ?? { kind: 'RESEARCH_DECISION', execution_authorized: false, strategy_version: 'cand-1', dataset_version: 'FIXTURE', action: 'WAIT', primary_reason: 'NO_VALID_IMPULSE', layer: 'strategy', strategy_eligible: false,
      reasons: { market: [], strategy: [], gate: [] }, setup: null, plan: null, risk: null, next_required: 'an impulse leg must form first', sizing: 'REFERENCE_ACCOUNT' },
    m1_shadow: o.shadow ?? null,
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

test('hero chips: eligibility, no current signal, and for a current BUY its age, publication time and expiry', async ({ page, request }) => {
  const c = await candles(request, 'M1');
  const at = c[c.length - 5].time + 3;
  const f = await useFixture(page, payload({}));
  await page.goto('/');
  await expect(page.getByTestId('decision-chips')).toContainText('Strategy eligible: NO');
  await expect(page.getByTestId('decision-chips')).toContainText('No current signal');
  const setup = { setup_id: 'S1', direction: 'BUY', state: 'ENTRY_ELIGIBLE', evidence: ['x'], invalidation_level: 4099.8, entry_level: 4103.2, expires_at: at + 7200, entry_window_ends_at: 1, known_at: at - 5, zone: null };
  const dec = { kind: 'RESEARCH_DECISION', execution_authorized: false, strategy_version: 'cand-1', dataset_version: 'FIXTURE', action: 'BUY', primary_reason: 'ENTRY_ELIGIBLE', layer: 'strategy', strategy_eligible: true, reasons: { market: [], strategy: [], gate: [] }, setup, plan: PLAN, risk: { status: 'OK' }, next_required: 'x', sizing: 'REFERENCE_ACCOUNT' };
  f.set(payload({ evaluated_at: at + 42, events: [ev({ decision_id: 'S1|BUY', setup_id: 'S1', action: 'BUY', direction: 'BUY', published_at: at })], current: 'S1|BUY', decision: dec, market: { direction_tf: 'H1', direction: 'UP', conflict_tf: 'H4', conflict_direction: 'NONE', conflict: false, regime: {}, history: 'OK' } }));
  await expect(page.getByTestId('decision-chips')).toContainText('Strategy eligible: YES');
  await expect(page.getByTestId('decision-chips')).toContainText('Signal CURRENT · age 42 s');
  await expect(page.getByTestId('decision-chips')).toContainText('expires ~');
  await page.screenshot({ path: `${ART}/hero-buy.png` });
});

test('alerts: history is never announced, a NEW BUY raises a toast (and a notification only when opted in), BLOCKED never sounds, the toast can be dismissed', async ({ page, request }) => {
  await page.addInitScript(() => {
    (window as any).__notes = [];
    class FakeNotification { static permission = 'granted'; static requestPermission() { return Promise.resolve('granted'); } constructor(t: string, o: any) { (window as any).__notes.push({ t, o }); } }
    (window as any).Notification = FakeNotification;
    (window as any).AudioContext = class { createOscillator() { (window as any).__beeps = ((window as any).__beeps || 0) + 1; return { frequency: {}, connect() {}, start() {}, stop() {} }; } createGain() { return { gain: {}, connect() {} }; } get destination() { return {}; } get currentTime() { return 0; } };
  });
  const c = await candles(request, 'M1');
  const old = ev({ decision_id: 'OLD|SELL', setup_id: 'OLD', action: 'SELL', direction: 'SELL', published_at: c[c.length - 50].time + 1 });
  const f = await useFixture(page, payload({ events: [old] }));
  await page.goto('/');
  await page.waitForTimeout(1200);
  await expect(page.getByTestId('toast')).toBeHidden();                                           // the history present at load is not announced
  await page.getByTestId('alert-notify').click();
  await page.getByTestId('alert-sound').click();
  await expect(page.getByTestId('alert-sound')).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByTestId('alert-notify')).toHaveAttribute('aria-pressed', 'true');
  const nb = ev({ decision_id: 'NEW|BUY', setup_id: 'NEW', action: 'BUY', direction: 'BUY', published_at: c[c.length - 3].time + 2 });
  f.set(payload({ events: [old, nb], current: 'NEW|BUY' }));
  await expect(page.getByTestId('toast')).toBeVisible();
  const t = await page.getByTestId('toast').innerText();
  expect(t).toContain('V1 BUY · RESEARCH'); expect(t).toContain('NEW'); expect(t).toContain('not an order');
  expect(await page.evaluate(() => (window as any).__notes.length)).toBe(1);
  expect(await page.evaluate(() => (window as any).__beeps)).toBeGreaterThanOrEqual(1);
  const beeps = await page.evaluate(() => (window as any).__beeps);
  await page.waitForTimeout(1200);
  expect(await page.evaluate(() => (window as any).__notes.length)).toBe(1);                        // repeated frames: still one notification
  await page.getByTestId('toast-close').click();
  await expect(page.getByTestId('toast')).toBeHidden();
  const blk = ev({ decision_id: 'B|BLOCKED|RISK:RR_TOO_LOW', setup_id: 'B', action: 'BLOCKED', direction: 'BUY', published_at: c[c.length - 2].time + 2, primary_reason: 'RISK:RR_TOO_LOW', risk_status: 'RR_TOO_LOW', gates: ['RISK:RR_TOO_LOW'] });
  f.set(payload({ events: [old, nb, blk], current: null }));
  await expect(page.getByTestId('toast')).toContainText('V1 BLOCKED (research)');
  expect(await page.evaluate(() => (window as any).__notes.length)).toBe(1);                        // BLOCKED raises a toast but never a notification or a sound
  expect(await page.evaluate(() => (window as any).__beeps)).toBe(beeps);
});

test('alerts are off by default: no notification and no sound unless the user opted in', async ({ page, request }) => {
  await page.addInitScript(() => { (window as any).__notes = []; (window as any).Notification = class { static permission = 'granted'; constructor(t: string) { (window as any).__notes.push(t); } }; });
  const c = await candles(request, 'M1');
  const f = await useFixture(page, payload({ events: [] }));
  await page.goto('/');
  await page.waitForTimeout(800);
  f.set(payload({ events: [ev({ decision_id: 'N|SELL', setup_id: 'N', action: 'SELL', direction: 'SELL', published_at: c[c.length - 3].time + 1 })], current: 'N|SELL' }));
  await expect(page.getByTestId('toast')).toBeVisible();                                           // the visual alert always exists
  expect(await page.evaluate(() => (window as any).__notes.length)).toBe(0);
  await expect(page.getByTestId('alert-sound')).toHaveAttribute('aria-pressed', 'false');
  await expect(page.getByTestId('alert-notify')).toHaveAttribute('aria-pressed', 'false');
});

test('More is closed by default and remembers its state; the sidebar toggle gives the chart the full width and persists', async ({ browser }) => {
  const ctx = await browser.newContext({ storageState: 'qa-artifacts/auth-state.json', viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  await page.addInitScript(() => { try { if (!sessionStorage.getItem('reset')) { sessionStorage.setItem('reset', '1'); localStorage.removeItem('xau.more'); localStorage.removeItem('xau.sidebar'); } } catch { /* ignore */ } });
  await useFixture(page, payload({}));
  await page.goto('/');
  expect(await page.getByTestId('more-panel').evaluate((e) => (e as HTMLDetailsElement).open)).toBe(false);
  await page.getByTestId('more-toggle').click();
  expect(await page.getByTestId('more-panel').evaluate((e) => (e as HTMLDetailsElement).open)).toBe(true);
  expect(await page.evaluate(() => localStorage.getItem('xau.more'))).toBe('1');
  const w0 = (await page.getByTestId('chart').boundingBox())!.width;
  await page.getByTestId('sidebar-toggle').click();
  await expect(page.getByTestId('sidebar-toggle')).toHaveAttribute('aria-pressed', 'false');
  await expect.poll(async () => (await page.getByTestId('chart').boundingBox())!.width).toBeGreaterThan(w0 + 200);
  await expect(page.getByTestId('decision-card')).toBeHidden();
  await expect.poll(async () => page.evaluate(() => Math.round(document.querySelector('[data-testid=chart] canvas')!.getBoundingClientRect().width))).toBeGreaterThan(w0);   // the chart canvas followed the new width
  await page.reload();
  await expect(page.getByTestId('sidebar-toggle')).toHaveAttribute('aria-pressed', 'false');
  await page.getByTestId('sidebar-toggle').click();
  await expect(page.getByTestId('decision-card')).toBeVisible();
  await ctx.close();
});

test('readable sizes and contrast: body text is at least 14 px, small text 12 px, no clipped hero, analysis clock ticks', async ({ page }) => {
  await useFixture(page, payload({ evaluated_at: 1_791_925_680 }));
  await page.goto('/');
  const m = await page.evaluate(() => {
    const px = (sel: string) => parseFloat(getComputedStyle(document.querySelector(sel)!).fontSize);
    const lum = (rgb: string) => { const [r, g, b] = (rgb.match(/\d+(\.\d+)?/g) || []).slice(0, 3).map(Number).map((v) => { const c = v / 255; return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; }); return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
    const cr = (a: string, b: string) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
    const bg = getComputedStyle(document.querySelector('#decision-card')!).backgroundColor;
    const muted = getComputedStyle(document.querySelector('#d-meta')!).color;
    const hero = document.querySelector('#d-action')!.getBoundingClientRect(), card = document.querySelector('#decision-card')!.getBoundingClientRect();
    return { body: px('body'), meta: px('#d-meta'), why: px('#d-primary'), mutedContrast: cr(muted, bg), heroInside: hero.right <= card.right && hero.left >= card.left, over: document.documentElement.scrollWidth > innerWidth };
  });
  expect(m.body).toBeGreaterThanOrEqual(14); expect(m.why).toBeGreaterThanOrEqual(14); expect(m.meta).toBeGreaterThanOrEqual(12);
  expect(m.mutedContrast).toBeGreaterThanOrEqual(4.5); expect(m.heroInside).toBe(true); expect(m.over).toBe(false);
  await expect(page.getByTestId('analysis-time')).toContainText('analysis ', { timeout: 4000 });
  await expect(page.getByTestId('analysis-time')).toContainText('server time');
});

test('M1 price action lines: shadow side versus H1/H4 (agrees / conflicts) and the closed-bar flags, labelled research only', async ({ page, request }) => {
  const c = await candles(request, 'M1');
  const bt = c[c.length - 10].time;
  const mk = (side: string, flags: string[]) => ({ version: 'm1v2-1', kind: 'SHADOW_OBSERVATION', execution_authorized: false, context: { direction: 'DOWN', conflict: false }, primary: side,
    directions: { [side]: { direction: side, stage: 'M1_TRIGGERED', next_required: 'x', trigger: { kind: 'M1_REJECTION', flags, bar_close: 1, bar_extreme: 1, known_at: bt + 60, window_ends_at: bt + 360, invalidation: 1, atr5: 1 } } },
    events_recent: [], funnel: {}, plan: null, entry_check: null, forming: null });
  const f = await useFixture(page, payload({ shadow: mk('SELL', ['M1_REJECTION', 'M1_MOMENTUM_SHIFT']) }));
  await page.goto('/');
  await expect(page.getByTestId('m1-card')).toContainText('V2 SHADOW (research only)');
  await expect(page.getByTestId('m1-agree')).toContainText('M1 shadow side SELL vs H1 DOWN · H4 DOWN: AGREES');
  await expect(page.getByTestId('m1-momentum')).toContainText('momentum shift on a CLOSED bar');
  f.set(payload({ shadow: mk('BUY', ['M1_REJECTION']) }));
  await expect(page.getByTestId('m1-agree')).toContainText('CONFLICT');
  await expect(page.getByTestId('m1-momentum')).toContainText('no momentum-shift flag');
});

test('a BUY/SELL action is never shown next to "No current signal" (publication time missing from the list is said, not hidden)', async ({ page }) => {
  const setup = { setup_id: 'S1', direction: 'BUY', state: 'ENTRY_ELIGIBLE', evidence: ['x'], invalidation_level: 1, entry_level: 2, expires_at: 2, entry_window_ends_at: 1, known_at: 1, zone: null };
  const dec = { kind: 'RESEARCH_DECISION', execution_authorized: false, strategy_version: 'cand-1', dataset_version: 'FIXTURE', action: 'BUY', primary_reason: 'ENTRY_ELIGIBLE', layer: 'strategy', strategy_eligible: true, reasons: { market: [], strategy: [], gate: [] }, setup, plan: PLAN, risk: { status: 'OK' }, next_required: 'x', sizing: 'REFERENCE_ACCOUNT' };
  await useFixture(page, payload({ decision: dec, events: [], current: null }));
  await page.goto('/');
  await expect(page.getByTestId('decision-chips')).toContainText('Signal CURRENT');
  await expect(page.getByTestId('decision-chips')).not.toContainText('No current signal');
});
