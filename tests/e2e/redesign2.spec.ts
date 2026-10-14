import { test, expect, Page } from '@playwright/test';

// Level 6.4 review round 17: the alert and M1-line edge cases the first tests did not pin down (each one was a surviving mutant or a reviewer counterexample).
async function candles(request: any, tf: string, n = 400) { return (await (await request.get(`/api/candles/${tf}?limit=${n}`)).json()).candles as any[]; }
const PLAN = { direction: 'BUY', entry: 4103.2, stop_loss: 4099.8, take_profit: 4118.4, net_rr: 3.4, gross_rr: 4.1, size_hidden: true, risk_fraction: 0.005 };
const ev = (o: any) => ({ log_schema: 1, kind: 'RESEARCH_DECISION_EVENT', execution_authorized: false, source_timeframe: 'M15', strategy_version: 'cand-1', dataset_version: 'FIXTURE', primary_reason: 'ENTRY_ELIGIBLE', risk_status: 'OK', gates: [], plan: PLAN,
  valid: { expires_at: o.published_at + 7200, invalidation_level: 4099.8 }, price: 4103.2, evaluated_at: o.published_at, known_at: o.published_at - 5, publish_latency_s: 5, ...o });
function payload(o: { events?: any[]; current?: string | null; shadow?: any; market?: any }) {
  return {
    type: 'intel', evaluated_at: 1_791_925_680, setup_bar_time: 1, bars: {}, mode: 'READ_ONLY+SHADOW+PAPER_SIMULATION', status: {}, analysis: {}, zones: [],
    market: o.market ?? { direction_tf: 'H1', direction: 'DOWN', conflict_tf: 'H4', conflict_direction: 'DOWN', conflict: false, regime: {}, history: 'OK' },
    setup_events: [], setup_events_total: 0, overlays: { zone: null, lines: [], direction: null }, v1_events: o.events ?? [], v1_current_id: o.current ?? null,
    decision: { kind: 'RESEARCH_DECISION', execution_authorized: false, strategy_version: 'cand-1', dataset_version: 'FIXTURE', action: 'WAIT', primary_reason: 'NO_VALID_IMPULSE', layer: 'strategy', strategy_eligible: false,
      reasons: { market: [], strategy: [], gate: [] }, setup: null, plan: null, risk: null, next_required: 'x', sizing: 'REFERENCE_ACCOUNT' },
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
const SPY = () => {
  (window as any).__notes = [];
  (window as any).__beeps = 0;
  (window as any).Notification = class { static permission = (window as any).__perm ?? 'granted'; static requestPermission() { return Promise.resolve((window as any).__reqResult ?? 'granted'); } constructor(t: string) { (window as any).__notes.push(t); } };
  (window as any).AudioContext = class { createOscillator() { (window as any).__beeps++; return { frequency: {}, connect() {}, start() {}, stop() {} }; } createGain() { return { gain: {}, connect() {} }; } get destination() { return {}; } get currentTime() { return 0; } };
};
const shadow = (side: string, flags: string[], bt: number) => ({ version: 'm1v2-1', kind: 'SHADOW_OBSERVATION', execution_authorized: false, context: { direction: 'DOWN', conflict: false }, primary: side,
  directions: { [side]: { direction: side, stage: 'M1_TRIGGERED', next_required: 'x', trigger: { kind: 'M1_REJECTION', flags, bar_close: 1, bar_extreme: 1, known_at: bt + 60, window_ends_at: bt + 360, invalidation: 1, atr5: 1 } } }, events_recent: [], funnel: {}, plan: null, entry_check: null, forming: null });

test('sound and notifications are silent by default even when a NEW BUY arrives', async ({ page, request }) => {
  await page.addInitScript(SPY);
  const c = await candles(request, 'M1');
  const f = await useFixture(page, payload({}));
  await page.goto('/');
  await page.waitForTimeout(700);
  f.set(payload({ events: [ev({ decision_id: 'N|BUY', setup_id: 'N', action: 'BUY', direction: 'BUY', published_at: c[c.length - 3].time + 1 })], current: 'N|BUY' }));
  await expect(page.getByTestId('toast')).toBeVisible();
  expect(await page.evaluate(() => (window as any).__beeps)).toBe(0);
  expect(await page.evaluate(() => (window as any).__notes.length)).toBe(0);
});

test('Notify is stored as ON only when the browser granted permission; sound alone never raises a notification', async ({ page, request }) => {
  await page.addInitScript(() => { (window as any).__perm = 'default'; (window as any).__reqResult = 'denied'; });
  await page.addInitScript(SPY);
  await page.addInitScript(() => { (window as any).Notification.requestPermission = () => Promise.resolve('denied'); });
  const c = await candles(request, 'M1');
  const f = await useFixture(page, payload({}));
  await page.goto('/');
  await page.getByTestId('alert-notify').click();
  await expect(page.getByTestId('alert-notify')).toHaveAttribute('aria-pressed', 'false');
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem('xau.alerts.v1') || '{}').notify)).toBe(false);          // not remembered as ON: no silent switch-on if the permission changes later
  await page.getByTestId('alert-sound').click();
  f.set(payload({ events: [ev({ decision_id: 'S|SELL', setup_id: 'S', action: 'SELL', direction: 'SELL', published_at: c[c.length - 3].time + 1 })], current: 'S|SELL' }));
  await expect(page.getByTestId('toast')).toBeVisible();
  expect(await page.evaluate(() => (window as any).__beeps)).toBeGreaterThanOrEqual(1);                                        // the sound opt-in works
  expect(await page.evaluate(() => (window as any).__notes.length)).toBe(0);                                                   // but no notification without permission
});

test('stale clears the toast; several new events in one payload give ONE toast (with the count), one sound and one notification per BUY/SELL', async ({ page, request }) => {
  await page.addInitScript(SPY);
  const c = await candles(request, 'M1');
  const f = await useFixture(page, payload({}));
  await page.goto('/');
  await page.getByTestId('alert-sound').click();
  await page.getByTestId('alert-notify').click();
  await expect(page.getByTestId('alert-notify')).toHaveAttribute('aria-pressed', 'true');
  const beeps0 = await page.evaluate(() => (window as any).__beeps);
  const a = ev({ decision_id: 'A|BLOCKED|RISK:RR_TOO_LOW', setup_id: 'A', action: 'BLOCKED', direction: 'BUY', published_at: c[c.length - 4].time + 1, primary_reason: 'RISK:RR_TOO_LOW', gates: ['RISK:RR_TOO_LOW'] });
  const b = ev({ decision_id: 'B|BUY', setup_id: 'B', action: 'BUY', direction: 'BUY', published_at: c[c.length - 3].time + 1 });
  const d = ev({ decision_id: 'D|SELL', setup_id: 'D', action: 'SELL', direction: 'SELL', published_at: c[c.length - 2].time + 1 });
  f.set(payload({ events: [a, b, d], current: 'D|SELL' }));
  await expect(page.getByTestId('toast')).toBeVisible();
  const t = await page.getByTestId('toast').innerText();
  expect(t).toContain('V1 BUY · RESEARCH'); expect(t).toContain('+2 more');                                                    // one toast: the first BUY/SELL, and the count of the others
  expect((await page.evaluate(() => (window as any).__beeps)) - beeps0).toBe(1);                                               // one sound
  expect(await page.evaluate(() => (window as any).__notes.length)).toBe(2);                                                   // BUY and SELL notified, BLOCKED not
  await page.evaluate(() => (window as any).__layers.onStale());
  await expect(page.getByTestId('toast')).toBeHidden();                                                                         // a stale feed removes the toast too
});

test('M1 agreement: H4 opposing is a conflict, H4 without a direction is said, a missing shadow section clears the lines', async ({ page, request }) => {
  const c = await candles(request, 'M1');
  const bt = c[c.length - 10].time;
  const mkt = (h1: string, h4: string) => ({ direction_tf: 'H1', direction: h1, conflict_tf: 'H4', conflict_direction: h4, conflict: false, regime: {}, history: 'OK' });
  const f = await useFixture(page, payload({ shadow: shadow('SELL', ['M1_REJECTION'], bt), market: mkt('DOWN', 'DOWN') }));
  await page.goto('/');
  await expect(page.getByTestId('m1-agree')).toContainText('AGREES (H1 and H4)');
  f.set(payload({ shadow: shadow('SELL', ['M1_REJECTION'], bt), market: mkt('DOWN', 'UP') }));
  await expect(page.getByTestId('m1-agree')).toContainText('CONFLICT (H4 opposes)');
  f.set(payload({ shadow: shadow('SELL', ['M1_REJECTION'], bt), market: mkt('DOWN', 'NONE') }));
  await expect(page.getByTestId('m1-agree')).toContainText('H1 agrees; H4 has no direction');
  await expect(page.getByTestId('m1-agree')).not.toContainText('AGREES (');
  f.set(payload({ shadow: shadow('BUY', ['M1_REJECTION'], bt), market: mkt('DOWN', 'DOWN') }));
  await expect(page.getByTestId('m1-agree')).toContainText('CONFLICT (H1 does not support this side)');
  f.set(payload({ shadow: null, market: mkt('DOWN', 'DOWN') }));
  await expect(page.getByTestId('m1-stage')).toContainText('shadow layer unavailable');
  expect(await page.getByTestId('m1-agree').innerText()).toBe('');                                                              // no stale AGREES under "unavailable"
  expect(await page.getByTestId('m1-momentum').innerText()).toBe('');
});

test('a notification needs the CURRENT permission: revoking it after opting in silences notifications', async ({ page, request }) => {
  await page.addInitScript(SPY);
  const c = await candles(request, 'M1');
  const f = await useFixture(page, payload({}));
  await page.goto('/');
  await page.getByTestId('alert-notify').click();
  await expect(page.getByTestId('alert-notify')).toHaveAttribute('aria-pressed', 'true');
  await page.evaluate(() => { (window as any).Notification.permission = 'denied'; });                                       // the user revokes the permission in the browser
  f.set(payload({ events: [ev({ decision_id: 'R|BUY', setup_id: 'R', action: 'BUY', direction: 'BUY', published_at: c[c.length - 3].time + 1 })], current: 'R|BUY' }));
  await expect(page.getByTestId('toast')).toBeVisible();
  expect(await page.evaluate(() => (window as any).__notes.length)).toBe(0);
});
