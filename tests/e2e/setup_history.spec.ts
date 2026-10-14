import { test, expect, Page } from '@playwright/test';
import * as fs from 'fs';

// Level 6.3: F/C/X/I/M setup events. The realtime payload carries only the newest 12; the history comes from /api/setup_events for the viewed period. Fixtures are SYNTHETIC
// and labelled; candles come from the live gateway. Every event is a setup observation placed on the candle that closes when it became known (known_at - 1).
const ART = 'qa-artifacts/setup_history';
fs.mkdirSync(ART, { recursive: true });
const SEC: Record<string, number> = { M1: 60, M5: 300, M15: 900, H1: 3600, H4: 14400 };
const STATES = ['SETUP_FORMING', 'CONFIRMED', 'EXPIRED', 'INVALIDATED', 'MISSED', 'PULLBACK_IN_PROGRESS', 'AT_RELEVANT_ZONE', 'ENTRY_WINDOW'];

async function candles(request: any, tf: string, n = 2000) { return (await (await request.get(`/api/candles/${tf}?limit=${n}`)).json()).candles as any[]; }
const mk = (i: number, state: string, direction: string, known: number, prov = 'REPLAY') => ({ event_id: `M15-${direction}-${i}|${state}|${known}`, setup_id: `M15-${direction}-${i}`, direction, setup_timeframe: 'M15', state, prev_state: null, event_time: known - 900,
  known_at: known, reasons: ['FIXTURE'], entry_level: null, invalidation_level: null, policy_version: 'setup-1', expires_at: null, provenance: prov });

function payload(realtime: any[], total: number) {
  return {
    type: 'intel', evaluated_at: 1_791_925_680, setup_bar_time: 1, bars: {}, mode: 'READ_ONLY+SHADOW+PAPER_SIMULATION', status: {}, analysis: {}, zones: [],
    market: { direction_tf: 'H1', direction: 'DOWN', conflict_tf: 'H4', conflict_direction: 'DOWN', conflict: false, regime: {}, history: 'OK' },
    setup_events: realtime, setup_events_total: total, setup_events_cap: 12, overlays: { zone: null, lines: [], direction: null }, v1_events: [], v1_current_id: null,
    decision: { kind: 'RESEARCH_DECISION', execution_authorized: false, strategy_version: 'cand-1', dataset_version: 'FIXTURE', action: 'WAIT', primary_reason: 'NO_VALID_IMPULSE', layer: 'strategy', strategy_eligible: false,
      reasons: { market: [], strategy: [], gate: [] }, setup: null, plan: null, risk: null, next_required: 'x', sizing: 'REFERENCE_ACCOUNT' }, m1_shadow: null,
  };
}

// 50 events: spread over the newest 450 M15 candles, five of them sharing one candle and side. Returns the events and the candle index of each.
function build(c: any[]) {
  const evs: any[] = [];
  const base = c.length - 450;
  for (let i = 0; i < 45; i++) {
    const idx = base + i * 10;
    evs.push(mk(i, STATES[i % STATES.length], i % 2 ? 'BUY' : 'SELL', c[idx].time + 900));
  }
  const share = base + 5;                                                                          // five events on ONE candle and ONE side
  for (let j = 0; j < 5; j++) evs.push(mk(100 + j, STATES[j], 'BUY', c[share].time + 900));
  return evs.sort((a, b) => a.known_at - b.known_at);
}
async function useFixture(page: Page, request: any, tf = 'M15') {
  const c = await candles(request, 'M15');
  const evs = build(c);
  const calls: string[] = [];
  const f = { realtime: evs.slice(-12) };
  await page.route('**/api/intel', (r) => r.fulfill({ json: payload(f.realtime.map((e) => ({ ...e, provenance: 'LIVE_ENGINE' })), evs.length) }));
  await page.routeWebSocket(/\/ws$/, (ws) => {
    const server = ws.connectToServer();
    server.onMessage((m) => { try { if (JSON.parse(String(m)).type === 'intel') return; } catch { /* forward */ } ws.send(m); });
    const t = setInterval(() => ws.send(JSON.stringify(payload(f.realtime.map((e) => ({ ...e, provenance: 'LIVE_ENGINE' })), evs.length))), 400);
    ws.onClose(() => clearInterval(t));
  });
  await page.route('**/api/setup_events*', (r) => {
    const u = new URL(r.request().url());
    calls.push(u.search);
    const from = Number(u.searchParams.get('from') ?? -Infinity), to = Number(u.searchParams.get('to') ?? Infinity);
    const sel = evs.filter((e) => e.known_at >= from && e.known_at <= to);
    r.fulfill({ json: { kind: 'SETUP_EVENTS', total_events: evs.length, live_engine_events: 12, replay_events: evs.length, replay_error: null, setup_version: 'setup-1', events: sel, total_in_range: sel.length, returned: sel.length, truncated: false, next_cursor: null } });
  });
  return { c, evs, calls };
}
const L = (page: Page) => page.evaluate(() => (window as any).__layers.events());
const marks = (page: Page) => page.evaluate(() => (window as any).__layers.markers());
const setup = (ms: any[]) => ms.filter((m) => !/BUY ·|SELL ·|V2|BLOCKED/.test(m.text) && ['circle', 'square'].includes(m.shape));
const zoomTo = (page: Page, idxFrom: number, idxTo: number) => page.evaluate(([a, b]) => (window as any).__qa.setRange({ from: a, to: b }), [idxFrom, idxTo]);
const dataTimes = (page: Page) => page.evaluate(() => (window as any).__qa.data().map((d: any) => d.time));

test('50 backend events: all 50 are loaded for the viewed period (a 12-event payload would have lost 38) and every one is accounted for', async ({ page, request }) => {
  const fx = await useFixture(page, request);
  await page.goto('/');
  await page.getByTestId('tf-M15').click();
  await expect.poll(() => page.evaluate(() => (window as any).__qa.dataTf())).toBe('M15');
  const n = (await dataTimes(page)).length;
  await zoomTo(page, n - 470, n + 2);
  await expect.poll(async () => (await L(page)).hist, { timeout: 8000 }).toBeGreaterThanOrEqual(38);
  const e = await L(page);
  const total = e.stats.visible.length + e.stats.hidden.length + e.stats.outside.length + e.stats.unmapped.length;
  expect(total).toBe(50);                                                                          // loaded = 50: nothing vanished silently
  expect(e.stats.outside.length).toBe(0); expect(e.stats.unmapped.length).toBe(0);
  const stats = await page.getByTestId('event-stats').innerText();
  expect(stats).toContain('Backend events 50'); expect(stats).toContain('Loaded 50');
  // default filter hides the intermediate states: they are COUNTED as hidden, with a reason
  const mid = fx.evs.filter((x) => !['SETUP_FORMING', 'CONFIRMED', 'EXPIRED', 'INVALIDATED', 'MISSED'].includes(x.state)).length;
  expect(e.stats.hidden.length).toBe(mid);
  expect(e.stats.hidden.every((h: any) => /intermediate/.test(h.why))).toBe(true);
  await page.getByTestId('event-mid').check();
  await expect.poll(async () => (await L(page)).stats.visible.length).toBe(50);
  await page.screenshot({ path: `${ART}/all-50.png` });
});

test('letters and sides: F C X I M on the right candle, BUY-side below and SELL-side above; the five events on one candle are one marker whose tooltip lists all five', async ({ page, request }) => {
  const fx = await useFixture(page, request);
  await page.goto('/');
  await page.getByTestId('tf-M15').click();
  await expect.poll(() => page.evaluate(() => (window as any).__qa.dataTf())).toBe('M15');
  const n = (await dataTimes(page)).length;
  await zoomTo(page, n - 100, n + 2);                                                             // zoomed in: letters are shown
  await page.getByTestId('event-mid').check();
  await expect.poll(async () => (await L(page)).hist, { timeout: 8000 }).toBeGreaterThan(30);
  const ms = setup(await marks(page));
  const times = await dataTimes(page);
  const sharedCandle = fx.c[fx.c.length - 450 + 5].time;
  const grp = ms.filter((m) => m.time === sharedCandle && m.position === 'belowBar');
  expect(grp.length).toBe(1);                                                                      // ONE marker for five BUY-side events on that candle
  expect(grp[0].text).toMatch(/^B·/);
  expect(grp[0].text).toContain('F'); expect(grp[0].text).toContain('C'); expect(grp[0].text).toContain('X'); expect(grp[0].text).toContain('I'); expect(grp[0].text).toContain('M');
  for (const m of ms) { expect(times).toContain(m.time); expect(['belowBar', 'aboveBar']).toContain(m.position); if (/^S/.test(m.text)) expect(m.position).toBe('aboveBar'); if (/^B/.test(m.text)) expect(m.position).toBe('belowBar'); }
  expect(ms.some((m) => /^S·[FCXIM]/.test(m.text))).toBe(true);
  for (const m of ms.filter((x) => /[XIM]/.test(x.text))) expect(m.shape).toBe('square');         // terminal states are squares, never arrows
  expect(ms.every((m) => !['arrowUp', 'arrowDown'].includes(m.shape))).toBe(true);                // a setup marker never looks like a V1 BUY/SELL decision
  // hover the shared candle: the tooltip lists all five events
  const idx = times.indexOf(sharedCandle);
  await page.evaluate(([a, b]) => (window as any).__qa.setRange({ from: a, to: b }), [idx - 12, idx + 12]);
  await page.waitForTimeout(400);
  const box = (await page.getByTestId('chart').boundingBox())!;
  const x = await page.evaluate((t) => (window as any).__qa.timeX(t), sharedCandle);
  let hit = false;
  for (let dx = -10; dx <= 10 && !hit; dx++) {
    await page.mouse.move(box.x + x + dx, box.y + box.height / 2);
    await page.mouse.move(box.x + x + dx + 0.5, box.y + box.height / 2 + 2);
    hit = (await page.evaluate(() => (window as any).__crosshair?.time)) === sharedCandle;
  }
  expect(hit).toBe(true);
  const tip = await page.getByTestId('marker-tooltip').innerText();
  expect(tip).toContain('5 setup events on this candle'); expect(tip).toContain('BUY-side'); expect(tip).toContain('NOT decisions');
  for (const w of ['forming', 'confirmed', 'expired', 'invalidated', 'missed']) expect(tip).toContain(w);
  await page.screenshot({ path: `${ART}/five-on-one-candle.png` });
});

test('pan and zoom: the viewed candle window is fetched once, zooming far out hides the letters but keeps every marker, panning never loses or refetches events', async ({ page, request }) => {
  const fx = await useFixture(page, request);
  await page.goto('/');
  await page.getByTestId('tf-M15').click();
  await expect.poll(() => page.evaluate(() => (window as any).__qa.dataTf())).toBe('M15');
  await page.getByTestId('event-mid').check();
  const n = (await dataTimes(page)).length;
  await expect.poll(async () => (await L(page)).hist, { timeout: 8000 }).toBe(50);                // the first view covers the whole loaded window: all 50 are fetched at once
  const calls = fx.calls.length;
  expect(calls).toBeGreaterThan(0);
  await zoomTo(page, n - 60, n + 2);                                                              // zoom in on the newest candles
  await page.waitForTimeout(500);
  const newest = setup(await marks(page));
  expect(newest.some((m) => m.text !== '')).toBe(true);                                           // zoomed in: letters
  await zoomTo(page, n - 460, n - 330);                                                           // pan far back
  await page.waitForTimeout(500);
  const e = await L(page);
  expect(e.stats.visible.length).toBe(50);                                                        // every loaded event is still drawn (no marker disappears when the view moves)
  const near = setup(await marks(page));
  expect(near.some((m) => m.text !== '')).toBe(true);
  await zoomTo(page, n - 600, n + 2);                                                             // zoom out: > 300 bars
  await page.waitForTimeout(500);
  const far = setup(await marks(page));
  expect(far.length).toBe(near.length);                                                           // the same markers, shapes only
  expect(far.every((m) => m.text === '')).toBe(true);
  await zoomTo(page, n - 100, n + 2);
  await page.waitForTimeout(500);
  expect(setup(await marks(page)).length).toBe(near.length);
  expect(fx.calls.length).toBe(calls);                                                            // panning and zooming inside the loaded window never refetched
  await page.screenshot({ path: `${ART}/zoomed-in.png` });
});

test('timeframe switch: the same events map to the right candle of H1 / M5 / M1 and the ones without a candle are counted with a reason', async ({ page, request }) => {
  const fx = await useFixture(page, request);
  await page.goto('/');
  await page.getByTestId('event-mid').check();
  for (const tf of ['M15', 'H1', 'M5', 'M1']) {
    await page.getByTestId(`tf-${tf}`).click();
    await expect.poll(() => page.evaluate(() => (window as any).__qa.dataTf())).toBe(tf);
    const n = (await dataTimes(page)).length;
    await zoomTo(page, 0, n + 2);                                                                 // the whole loaded window of this timeframe
    await expect.poll(async () => { const s = (await L(page)).stats; return s.visible.length + s.hidden.length + s.outside.length + s.unmapped.length; }, { timeout: 10000 }).toBe(50);
    const times = await dataTimes(page);
    const s = (await L(page)).stats;
    for (const v of s.visible) { expect(times).toContain(v.time); expect(v.time).toBeLessThanOrEqual(v.e.known_at - 1); expect(v.e.known_at - 1).toBeLessThan(v.time + SEC[tf]); }   // on the candle that contains known_at - 1
    for (const o of s.outside) expect(o.why).toMatch(/older than the first loaded candle|after the last loaded candle/);
    if (tf === 'M1') expect(s.outside.length).toBeGreaterThan(0);                                  // the 2000-candle window of M1 (about 33 h) is shorter than the 450 M15 candles the events span
    const st = await page.getByTestId('event-stats').innerText();
    expect(st).toContain(`Outside range ${s.outside.length}`);
  }
});

test('layers: History off keeps only the realtime events, Setups off hides all with a reason, the choice survives a reload', async ({ page, request }) => {
  const fx = await useFixture(page, request);
  await page.goto('/');
  await page.getByTestId('tf-M15').click();
  await expect.poll(() => page.evaluate(() => (window as any).__qa.dataTf())).toBe('M15');
  await page.getByTestId('event-mid').check();
  const n = (await dataTimes(page)).length;
  await zoomTo(page, n - 470, n + 2);
  await expect.poll(async () => (await L(page)).stats.visible.length).toBe(50);
  await page.getByTestId('layer-history').click();
  await expect.poll(async () => (await L(page)).stats.visible.length).toBe(12);                   // the newest 12 (realtime) stay
  expect((await L(page)).stats.hidden.every((h: any) => /History/.test(h.why))).toBe(true);
  await page.getByTestId('layer-setups').click();
  await expect.poll(async () => (await L(page)).stats.visible.length).toBe(0);
  expect((await L(page)).stats.hidden.length).toBe(50);
  await page.reload();
  await expect(page.getByTestId('layer-history')).toHaveAttribute('aria-pressed', 'false');
  await expect(page.getByTestId('layer-setups')).toHaveAttribute('aria-pressed', 'false');
  expect(await page.getByTestId('event-mid').isChecked()).toBe(true);                             // the filter choice persisted too
  await page.getByTestId('layer-setups').click();
  await page.getByTestId('layer-history').click();
});

test('the inspector locates an event on the chart; stale clears markers and the list; a missing candle is reported as unmapped', async ({ page, request }) => {
  const fx = await useFixture(page, request);
  const real = await candles(request, 'M15');
  const target = fx.evs[20];
  const missing = fx.evs.find((e) => e.event_id !== target.event_id)!;
  const gapTime = Math.floor((missing.known_at - 1) / 900) * 900;
  await page.route('**/api/candles/M15*', (r) => r.fulfill({ json: { tf: 'M15', candles: real.filter((c: any) => c.time !== gapTime) } }));            // one candle is missing from the data
  await page.goto('/');
  await page.getByTestId('tf-M15').click();
  await page.getByTestId('event-mid').check();
  await expect.poll(() => page.evaluate(() => (window as any).__qa.dataTf())).toBe('M15');
  const n = (await dataTimes(page)).length;
  await zoomTo(page, n - 470, n + 2);
  await expect.poll(async () => (await L(page)).stats.unmapped.length).toBeGreaterThanOrEqual(1);
  const um = (await L(page)).stats.unmapped.find((x: any) => x.e.event_id === missing.event_id);
  expect(um.why).toContain('missing bar');                                                          // accounted for, with the reason
  await zoomTo(page, n - 40, n + 2);
  await page.waitForTimeout(500);
  await expect(page.getByTestId('ev-row').first()).toBeVisible({ timeout: 8000 });
  await zoomTo(page, n - 470, n - 400);
  await page.waitForTimeout(600);
  await page.getByTestId('ev-row').first().click();
  await page.waitForTimeout(400);
  const rng = await page.evaluate(() => (window as any).__qa.range());
  expect(rng.to - rng.from).toBeLessThan(120);                                                      // the chart was moved to a ~80-candle window around the event
  await page.evaluate(() => (window as any).__layers.onStale());
  expect((await marks(page)).length).toBe(0);
  expect(await page.getByTestId('event-stats').innerText()).toBe('');
  expect(await page.getByTestId('ev-row').count()).toBe(0);
});

test('a failed replay is not marked as covered: the card says so, the live events stay, and the history is fetched again until it works', async ({ page, request }) => {
  const c = await candles(request, 'M15');
  const evs = build(c);
  let n = 0;
  await page.addInitScript(() => { (window as any).__histRetryMs = 400; });
  await page.route('**/api/intel', (r) => r.fulfill({ json: payload(evs.slice(-12).map((e) => ({ ...e, provenance: 'LIVE_ENGINE' })), evs.length) }));
  await page.routeWebSocket(/\/ws$/, (ws) => {
    const server = ws.connectToServer();
    server.onMessage((m) => { try { if (JSON.parse(String(m)).type === 'intel') return; } catch { /* forward */ } ws.send(m); });
    const t = setInterval(() => ws.send(JSON.stringify(payload(evs.slice(-12).map((e) => ({ ...e, provenance: 'LIVE_ENGINE' })), evs.length))), 300);
    ws.onClose(() => clearInterval(t));
  });
  await page.route('**/api/setup_events*', (r) => {
    n++;
    const failing = n === 1;
    const sel = failing ? evs.slice(-12) : evs;
    r.fulfill({ json: { kind: 'SETUP_EVENTS', total_events: evs.length, live_engine_events: 12, replay_events: failing ? 0 : evs.length, replay_error: failing ? 'TimeoutError' : null, setup_version: 'setup-1', events: sel, total_in_range: sel.length, returned: sel.length, truncated: false, next_cursor: null } });
  });
  await page.goto('/');
  await page.getByTestId('tf-M15').click();
  await expect.poll(() => page.evaluate(() => (window as any).__qa.dataTf())).toBe('M15');
  await page.getByTestId('event-mid').check();
  await expect(page.getByTestId('event-stats')).toContainText('replay unavailable', { timeout: 8000 });
  await expect.poll(async () => (await L(page)).hist, { timeout: 15000 }).toBe(50);              // the second fetch (after the retry delay) brought the full timeline
  await expect(page.getByTestId('event-stats')).not.toContainText('replay unavailable');
  expect(n).toBeGreaterThanOrEqual(2);
});
