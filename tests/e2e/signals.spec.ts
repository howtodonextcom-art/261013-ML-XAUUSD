import { test, expect, Page } from '@playwright/test';
import * as fs from 'fs';

// Level 6.2: V1 research decision markers, market bias, setup progress, tooltips. Fixtures are SYNTHETIC and labelled; candles come from the live gateway. The markers are a display
// of backend decision events (payload.v1_events): placed on the candle that contains the PUBLICATION time, never earlier, never repainted.
const ART = 'qa-artifacts/signals';
fs.mkdirSync(ART, { recursive: true });
const SEC: Record<string, number> = { M1: 60, M5: 300, M15: 900, H1: 3600, H4: 14400 };

async function candles(request: any, tf: string, n = 400) { return (await (await request.get(`/api/candles/${tf}?limit=${n}`)).json()).candles as any[]; }
const PLAN = { direction: 'BUY', entry: 4103.2, stop_loss: 4099.8, take_profit: 4118.4, net_rr: 3.4, gross_rr: 4.1, size_hidden: true, risk_fraction: 0.005 };
const ev = (o: any) => ({ log_schema: 1, kind: 'RESEARCH_DECISION_EVENT', execution_authorized: false, source_timeframe: 'M15', strategy_version: 'cand-1', dataset_version: 'FIXTURE', primary_reason: 'ENTRY_ELIGIBLE', risk_status: 'OK', gates: [], plan: PLAN,
  valid: { expires_at: o.published_at + 7200, invalidation_level: 4099.8 }, price: 4103.2, evaluated_at: o.published_at, known_at: o.published_at - 5, publish_latency_s: 5, ...o });

function payload(o: { px: number; events?: any[]; current?: string | null; market?: any; decision?: any; setupEvents?: any[]; shadow?: any }) {
  return {
    type: 'intel', evaluated_at: 1_791_925_680, setup_bar_time: 1_791_924_900, bars: {}, mode: 'READ_ONLY+SHADOW+PAPER_SIMULATION', status: {}, analysis: {}, zones: [],
    market: o.market ?? { direction_tf: 'H1', direction: 'DOWN', conflict_tf: 'H4', conflict_direction: 'DOWN', conflict: false, regime: { M15: 'TRANSITION', H1: 'TRENDING_DOWN', H4: 'TRENDING_DOWN' }, history: 'OK' },
    setup_events: o.setupEvents ?? [], overlays: { zone: null, lines: [], direction: null }, v1_events: o.events ?? [], v1_current_id: o.current ?? null,
    decision: o.decision ?? { kind: 'RESEARCH_DECISION', execution_authorized: false, strategy_version: 'cand-1', dataset_version: 'FIXTURE', action: 'WAIT', primary_reason: 'NO_VALID_IMPULSE', layer: 'strategy', strategy_eligible: false,
      reasons: { market: [], strategy: ['NO_VALID_IMPULSE'], gate: [] }, setup: null, plan: null, risk: null, next_required: 'an impulse leg must form first', sizing: 'REFERENCE_ACCOUNT' },
    m1_shadow: o.shadow ?? null,
  };
}
async function useFixture(page: Page, first: any) {
  let current = first;
  await page.route('**/api/intel', (r) => r.fulfill({ json: current }));
  await page.route('**/api/setup_events*', (r) => r.fulfill({ json: { kind: 'SETUP_EVENTS', total_events: 0, live_engine_events: 0, replay_events: 0, replay_error: null, setup_version: 'setup-1', events: [], total_in_range: 0, returned: 0, truncated: false, next_cursor: null } }));       // fixtures own the marker set: no real history leaks in
  await page.routeWebSocket(/\/ws$/, (ws) => {
    const server = ws.connectToServer();
    server.onMessage((m) => { try { if (JSON.parse(String(m)).type === 'intel') return; } catch { /* forward */ } ws.send(m); });
    const t = setInterval(() => ws.send(JSON.stringify(current)), 300);
    ws.onClose(() => clearInterval(t));
  });
  return { set: (p: any) => { current = p; } };
}
const marks = (page: Page) => page.evaluate(() => (window as any).__layers.markers());
const v1 = (ms: any[]) => ms.filter((m) => /BUY|SELL|BLOCKED/.test(m.text) && !/V2/.test(m.text));

test('V1 BUY / SELL / BLOCKED markers sit on the candle that contains the publication time, with text and distinct shapes (no colour-only coding)', async ({ page, request }) => {
  const c = await candles(request, 'M1');
  const k = c.length - 60;
  const buyAt = c[k].time + 17, sellAt = c[k + 20].time + 41, blkAt = c[k + 35].time + 5;
  await useFixture(page, payload({ px: c[c.length - 1].close, events: [ev({ decision_id: 'S1|BUY', setup_id: 'S1', action: 'BUY', direction: 'BUY', published_at: buyAt }),
    ev({ decision_id: 'S2|SELL', setup_id: 'S2', action: 'SELL', direction: 'SELL', published_at: sellAt }),
    ev({ decision_id: 'S3|BLOCKED|RISK:RR_TOO_LOW', setup_id: 'S3', action: 'BLOCKED', direction: 'BUY', published_at: blkAt, primary_reason: 'RISK:RR_TOO_LOW', risk_status: 'RR_TOO_LOW', gates: ['RISK:RR_TOO_LOW'] })] }));
  await page.goto('/');
  await expect.poll(async () => v1(await marks(page)).length).toBe(3);
  const m = v1(await marks(page));
  const by = (t: string) => m.find((x) => x.text.startsWith(t))!;
  expect(by('BUY').time).toBe(c[k].time); expect(by('BUY').position).toBe('belowBar'); expect(by('BUY').shape).toBe('arrowUp'); expect(by('BUY').text).toBe('BUY · RESEARCH');
  expect(by('SELL').time).toBe(c[k + 20].time); expect(by('SELL').position).toBe('aboveBar'); expect(by('SELL').shape).toBe('arrowDown'); expect(by('SELL').text).toBe('SELL · RESEARCH');
  expect(by('BLOCKED').time).toBe(c[k + 35].time); expect(by('BLOCKED').shape).toBe('square'); expect(by('BLOCKED').color).not.toBe(by('BUY').color); expect(by('BLOCKED').color).not.toBe(by('SELL').color);
  expect(new Set(m.map((x) => x.shape)).size).toBe(3);                                           // three different shapes: BUY, SELL and BLOCKED never differ by colour alone
  for (const x of m) expect(x.text).not.toMatch(/NOW/);                                          // none of them is current: they are history
  await page.screenshot({ path: `${ART}/markers-m1.png` });
});

test('the same events land on the right candle of every timeframe (publication time, never the bar open) and a published time is never moved earlier', async ({ page, request }) => {
  const c1 = await candles(request, 'M1');
  const pub = c1[c1.length - 200].time + 59;                                                       // the last second of an M1 candle
  await useFixture(page, payload({ px: 1, events: [ev({ decision_id: 'S1|SELL', setup_id: 'S1', action: 'SELL', direction: 'SELL', published_at: pub })] }));
  await page.goto('/');
  for (const tf of ['M1', 'M5', 'M15', 'H1', 'H4']) {
    await page.getByTestId(`tf-${tf}`).click();
    await expect.poll(() => page.evaluate(() => (window as any).__qa.dataTf())).toBe(tf);
    await expect.poll(async () => v1(await marks(page)).length, { timeout: 8000 }).toBe(1);
    const t = v1(await marks(page))[0].time;
    expect(t).toBe(Math.floor(pub / SEC[tf]) * SEC[tf]);
    expect(t).toBeLessThanOrEqual(pub);
  }
});

test('the NOW tag exists only for the current decision; a repeated frame never duplicates a marker; stale clears every marker', async ({ page, request }) => {
  const c = await candles(request, 'M1');
  const at = c[c.length - 10].time + 3;
  const e = ev({ decision_id: 'S9|BUY', setup_id: 'S9', action: 'BUY', direction: 'BUY', published_at: at });
  const f = await useFixture(page, payload({ px: 1, events: [e], current: 'S9|BUY' }));
  await page.goto('/');
  await expect.poll(async () => v1(await marks(page)).map((x) => x.text)).toEqual(['BUY · RESEARCH · NOW']);
  await page.waitForTimeout(1500);                                                                // ~5 identical frames
  expect(v1(await marks(page)).length).toBe(1);
  f.set(payload({ px: 1, events: [e], current: null }));                                          // the decision is no longer current (WAIT again): history stays, NOW goes
  await expect.poll(async () => v1(await marks(page)).map((x) => x.text)).toEqual(['BUY · RESEARCH']);
  await page.evaluate(() => (window as any).__layers.onStale());                                  // stale / disconnected: every marker is removed, nothing stays actionable
  expect((await marks(page)).length).toBe(0);
});

test('reload restores the historical events from the backend payload without making them current', async ({ page, request }) => {
  const c = await candles(request, 'M1');
  const e = ev({ decision_id: 'S5|SELL', setup_id: 'S5', action: 'SELL', direction: 'SELL', published_at: c[c.length - 30].time + 2 });
  await useFixture(page, payload({ px: 1, events: [e], current: null }));
  await page.goto('/');
  await expect.poll(async () => v1(await marks(page)).length).toBe(1);
  await page.reload();
  await expect.poll(async () => v1(await marks(page)).length).toBe(1);
  expect(v1(await marks(page))[0].text).toBe('SELL · RESEARCH');                                   // historical after the reload, not current
  await expect(page.getByTestId('decision-action')).toHaveText('WAIT');
});

test('V2 shadow markers are labelled V2 SHADOW and never look like V1 BUY/SELL', async ({ page, request }) => {
  const c = await candles(request, 'M1');
  const bt = c[c.length - 12].time;
  const shadow = { version: 'm1v2-1', kind: 'SHADOW_OBSERVATION', execution_authorized: false, context: { direction: 'DOWN', conflict: false }, primary: 'SELL', directions: { SELL: { direction: 'SELL', stage: 'M1_TRIGGERED', next_required: 'x' } },
    events_recent: [{ event_id: 'E1', direction: 'SELL', stage: 'M1_TRIGGERED', kind: 'M1_REJECTION', bar_time: bt, known_at: bt + 60 }], funnel: {}, plan: null, entry_check: null, forming: null };
  await useFixture(page, payload({ px: 1, shadow, events: [ev({ decision_id: 'S1|BUY', setup_id: 'S1', action: 'BUY', direction: 'BUY', published_at: c[c.length - 40].time + 1 })] }));
  await page.goto('/');
  await expect.poll(async () => (await marks(page)).some((x) => x.text === 'V2 SHADOW')).toBe(true);
  const ms = await marks(page);
  const v2 = ms.find((x) => x.text === 'V2 SHADOW')!, b = ms.find((x) => x.text.startsWith('BUY'))!;
  expect(v2.color).not.toBe(b.color);
  expect(v2.text).not.toMatch(/BUY|SELL/);
  await expect(page.getByTestId('decision-action')).toHaveText('WAIT');                          // a V2 SELL shadow while V1 is WAIT
});

test('hovering a marker shows its tooltip: publication time, setup id, reason, levels and HISTORICAL', async ({ page, request }) => {
  const c = await candles(request, 'M1');
  const k = c.length - 50;
  await useFixture(page, payload({ px: 1, events: [ev({ decision_id: 'S1|BUY', setup_id: 'S1', action: 'BUY', direction: 'BUY', published_at: c[k].time + 17 })] }));
  await page.goto('/');
  await expect.poll(async () => v1(await marks(page)).length).toBe(1);
  await page.evaluate((t) => { const q = (window as any).__qa; const i = q.data().findIndex((d: any) => d.time === t); q.setRange({ from: i - 12, to: i + 12 }); }, c[k].time);   // zoom in: bars become wide enough to hover
  await page.waitForTimeout(300);
  const box = (await page.getByTestId('chart').boundingBox())!;
  const x = await page.evaluate((t) => (window as any).__qa.timeX(t), c[k].time);
  let hit = false;                                                                                // bars are only a few pixels wide: find the pixel whose crosshair bar IS the marker's bar
  for (let dx = -8; dx <= 8 && !hit; dx++) {
    await page.mouse.move(box.x + x + dx, box.y + box.height / 2);
    await page.mouse.move(box.x + x + dx + 0.5, box.y + box.height / 2 + 2);
    hit = (await page.evaluate(() => (window as any).__crosshair?.time)) === c[k].time;
  }
  expect(hit).toBe(true);
  const tip = page.getByTestId('marker-tooltip');
  await expect(tip).toBeVisible();
  const t = await tip.innerText();
  expect(t).toContain('V1 BUY · RESEARCH'); expect(t).toContain('HISTORICAL, not a current signal'); expect(t).toContain('published'); expect(t).toContain('S1'); expect(t).toContain('entry 4103.20'); expect(t).toContain('not an order');
  await page.screenshot({ path: `${ART}/tooltip.png` });
});

test('market bias and setup progress follow the backend: no impulse, eligible, blocked, conflict', async ({ page }) => {
  const f = await useFixture(page, payload({ px: 1 }));
  await page.goto('/');
  await expect(page.getByTestId('market-bias')).toContainText('BEARISH');
  await expect(page.getByTestId('market-bias')).toContainText('not a prediction');
  const li = await page.getByTestId('setup-progress').locator('li').allInnerTexts();
  expect(li[0]).toContain('Context: DONE'); expect(li[1]).toContain('Impulse: WAITING'); expect(li[2]).toContain('Pullback: NOT EVALUATED'); expect(li[6]).toContain('Risk: NOT EVALUATED');
  const setup = { setup_id: 'M15-BUY-1', direction: 'BUY', state: 'ENTRY_ELIGIBLE', evidence: ['x'], invalidation_level: 4099.8, entry_level: 4103.2, expires_at: 2, entry_window_ends_at: 1, known_at: 1, zone: null };
  const base = { kind: 'RESEARCH_DECISION', execution_authorized: false, strategy_version: 'cand-1', dataset_version: 'FIXTURE', layer: 'strategy', strategy_eligible: true, setup, plan: PLAN, risk: { status: 'OK' }, next_required: 'x', sizing: 'REFERENCE_ACCOUNT' };
  f.set(payload({ px: 1, market: { direction_tf: 'H1', direction: 'UP', conflict_tf: 'H4', conflict_direction: 'NONE', conflict: false, regime: {}, history: 'OK' }, decision: { ...base, action: 'BUY', primary_reason: 'ENTRY_ELIGIBLE', reasons: { market: [], strategy: ['ENTRY_ELIGIBLE'], gate: [] } } }));
  await expect(page.getByTestId('market-bias')).toContainText('BULLISH');
  await expect.poll(async () => (await page.getByTestId('setup-progress').locator('li').allInnerTexts())[6]).toContain('Risk: DONE');
  f.set(payload({ px: 1, decision: { ...base, action: 'BLOCKED', primary_reason: 'RISK:RR_TOO_LOW', layer: 'gate', reasons: { market: [], strategy: ['ENTRY_ELIGIBLE'], gate: ['RISK:RR_TOO_LOW'] } } }));
  await expect.poll(async () => (await page.getByTestId('setup-progress').locator('li').allInnerTexts())[6]).toContain('Risk: FAILED (RR_TOO_LOW)');
  f.set(payload({ px: 1, market: { direction_tf: 'H1', direction: 'UP', conflict_tf: 'H4', conflict_direction: 'DOWN', conflict: true, regime: {}, history: 'OK' } }));
  await expect(page.getByTestId('market-bias')).toContainText('NEUTRAL');
  await expect.poll(async () => (await page.getByTestId('setup-progress').locator('li').allInnerTexts())[0]).toContain('Context: FAILED');
  await page.screenshot({ path: `${ART}/hero.png` });
});

test('a moment that lies after the last loaded candle or inside a missing one is NOT drawn on an earlier candle', async ({ page, request }) => {
  const c = await candles(request, 'M1');
  const last = c[c.length - 1].time;
  await useFixture(page, payload({ px: 1, events: [ev({ decision_id: 'F1|BUY', setup_id: 'F1', action: 'BUY', direction: 'BUY', published_at: last + 3600 }),
    ev({ decision_id: 'F2|SELL', setup_id: 'F2', action: 'SELL', direction: 'SELL', published_at: c[c.length - 20].time + 5 })] }));
  await page.goto('/');
  await expect.poll(async () => v1(await marks(page)).length).toBe(1);                            // only the SELL inside the data: the BUY one hour after the last candle has no candle yet
  expect(v1(await marks(page))[0].text).toBe('SELL · RESEARCH');
});

test('two conflicting setups: the stepper agrees with the SIGNAL_CONFLICT headline; a history-log error is shown on the card', async ({ page }) => {
  const setup = { setup_id: 'M15-BUY-1', direction: 'BUY', state: 'ENTRY_WINDOW', evidence: ['x'], invalidation_level: 1, entry_level: 2, expires_at: 2, entry_window_ends_at: 1, known_at: 1, zone: null };
  const dec = { kind: 'RESEARCH_DECISION', execution_authorized: false, strategy_version: 'cand-1', dataset_version: 'FIXTURE', action: 'WAIT', primary_reason: 'SIGNAL_CONFLICT', layer: 'strategy', strategy_eligible: false,
    reasons: { market: [], strategy: ['SIGNAL_CONFLICT'], gate: [] }, setup, plan: null, risk: null, next_required: 'the conflicting directions must resolve', sizing: 'REFERENCE_ACCOUNT' };
  const p: any = payload({ px: 1, decision: dec });
  p.v1_log_error = 'OSError';
  await useFixture(page, p);
  await page.goto('/');
  await expect(page.getByTestId('decision-primary')).toContainText('SIGNAL_CONFLICT');
  const li = await page.getByTestId('setup-progress').locator('li').allInnerTexts();
  expect(li[0]).toContain('Context: FAILED'); expect(li[5]).toContain('Entry: NOT EVALUATED'); expect(li[6]).toContain('Risk: NOT EVALUATED');
  await expect(page.getByTestId('decision-meta')).toContainText('DECISION HISTORY LOG ERROR (OSError)');
});
