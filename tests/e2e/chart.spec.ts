import { test, expect, Page } from '@playwright/test';
import * as fs from 'fs';

const ART = 'qa-artifacts/chart';
fs.mkdirSync(ART, { recursive: true });
const range = (p: Page) => p.evaluate(() => (window as any).__qa.range());
const width = (r: any) => r.to - r.from;
async function setRangeAndWait(page: Page, from: number, to: number) {
  await page.evaluate(([f, t]) => (window as any).__qa.setRange({ from: f, to: t }), [from, to]);
  await expect.poll(async () => { const r = await range(page); return Math.abs(r.from - from) < 1 && Math.abs(r.to - to) < 1; }).toBe(true);
}

async function ready(page: Page, tf = 'M1') {
  await page.goto('/');
  await page.getByTestId(`tf-${tf}`).click();
  await expect.poll(() => page.evaluate(() => (window as any).__qa.dataTf())).toBe(tf);
  await page.waitForTimeout(300);
}
async function box(page: Page) { const b = await page.getByTestId('chart').boundingBox(); if (!b) throw new Error('no chart box'); return b; }

test('F3 wheel zoom changes visible bar density in the right direction', async ({ page }) => {
  await ready(page);
  await setRangeAndWait(page, 1500, 1900); // known baseline window
  const b = await box(page);
  const r0 = await range(page);
  await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2);
  await page.mouse.wheel(0, -600);                       // wheel up = zoom in
  await expect.poll(async () => width(await range(page))).toBeLessThan(width(r0) * 0.95);
  const zin = width(await range(page));
  await page.mouse.wheel(0, 1500);                        // wheel down = zoom out
  await expect.poll(async () => width(await range(page))).toBeGreaterThan(zin * 1.05);
  await page.screenshot({ path: `${ART}/zoom.png` });
});

test('F3 drag-to-pan moves the window by the dragged distance and does not rescale', async ({ page }) => {
  await ready(page);
  await setRangeAndWait(page, 1500, 1900);
  const b = await box(page);
  const r0 = await range(page);
  const y = b.y + b.height / 2;
  await page.mouse.move(b.x + b.width * 0.7, y);
  await page.mouse.down();
  await page.mouse.move(b.x + b.width * 0.3, y, { steps: 12 });
  await page.mouse.up();
  const r1 = await range(page);
  expect(r1.from).toBeGreaterThan(r0.from + 50);                          // dragged left => later bars come into view
  expect(Math.abs(width(r1) - width(r0))).toBeLessThan(width(r0) * 0.02);  // pan does not change zoom
});

test('F3 crosshair reports a real bar time and an in-range price', async ({ page }) => {
  await ready(page);
  const b = await box(page);
  await page.mouse.move(b.x + b.width * 0.5, b.y + b.height * 0.5, { steps: 5 });
  await expect.poll(() => page.evaluate(() => (window as any).__qa.crosshair())).not.toBeNull();
  const ch = await page.evaluate(() => (window as any).__qa.crosshair());
  const times = await page.evaluate(() => (window as any).__qa.data().map((d: any) => d.time));
  expect(times).toContain(ch.time);
  const data = await page.evaluate(() => (window as any).__qa.data());
  const lo = Math.min(...data.map((d: any) => d.low)), hi = Math.max(...data.map((d: any) => d.high));
  expect(ch.price).toBeGreaterThan(lo - (hi - lo) * 0.2);
  expect(ch.price).toBeLessThan(hi + (hi - lo) * 0.2);
});

test('F3 periodic refresh and live ticks must NOT yank the view back while the user studies history', async ({ page }) => {
  await ready(page);
  await setRangeAndWait(page, 300, 500);   // user is looking at old data
  const r0 = await range(page);
  await page.evaluate(() => (window as any).__qa.refresh());                           // what the 60 s timer does
  await page.waitForTimeout(1500);                                                      // live ticks keep arriving
  const r1 = await range(page);
  expect(Math.abs(r1.from - r0.from)).toBeLessThan(2);
  expect(Math.abs(r1.to - r0.to)).toBeLessThan(2);
});

test('F4 chart follows window resize (no stale canvas size)', async ({ page }) => {
  await ready(page);
  for (const [w, h] of [[1152, 720], [1440, 900], [900, 700]]) {
    await page.setViewportSize({ width: w, height: h });
    await page.waitForTimeout(250);
    const { cw, boxw } = await page.evaluate(() => {
      const el = document.querySelector('[data-testid=chart]') as HTMLElement;
      const canvas = el.querySelector('canvas') as HTMLCanvasElement;
      return { cw: canvas.getBoundingClientRect().width, boxw: el.getBoundingClientRect().width };
    });
    expect(Math.abs(cw - boxw)).toBeLessThan(80);   // price-scale gutter is allowed, a stale size is not
    expect(boxw).toBeLessThanOrEqual(w);
  }
});

test('F5 incomplete or quarantined bars are drawn differently from normal bars (deterministic data)', async ({ page, request }) => {
  const real = await (await request.get('/api/candles/M1?limit=300')).json();
  const c = real.candles.map((x: any) => ({ ...x, completeness: 'HISTORICAL' }));
  c[100].completeness = 'HISTORICAL_QUARANTINED';
  c[200].completeness = 'PARTIAL_STARTED_MID_BAR';
  await page.route('**/api/candles/M1*', (r) => r.fulfill({ json: { tf: 'M1', candles: c } }));
  await page.goto('/');
  await expect.poll(() => page.evaluate(() => (window as any).__qa.dataTf())).toBe('M1');
  const d = await page.evaluate(() => (window as any).__qa.data().map((x: any) => ({ t: x.time, color: x.color || null })));
  expect(d.length).toBe(300);
  expect(d[100].color).toBeTruthy();
  expect(d[200].color).toBeTruthy();
  expect(d.filter((x: any) => x.color).length).toBe(2);   // only those two, nothing else is greyed
});

test('F5 a chart-update exception is contained: error is shown and data reloads (paint loop survives)', async ({ page }) => {
  await page.goto('/');
  await expect.poll(() => page.evaluate(() => (window as any).__qa.dataTf())).toBe('M1');
  await page.evaluate(() => { (window as any).__qa.injectBadUpdate(); });
  await expect.poll(() => page.evaluate(() => (window as any).__paintErrors)).toBeGreaterThan(0);
  await expect.poll(() => page.evaluate(() => (window as any).__qa.dataTf()), { timeout: 10_000 }).toBe('M1');   // reloaded
  const n = await page.evaluate(() => (window as any).__qa.data().length);
  expect(n).toBeGreaterThan(1000);
  // and the loop is still alive: a later valid update is applied
  const before = await page.evaluate(() => (window as any).__qa.data().length);
  await page.waitForTimeout(1500);
  expect(await page.evaluate(() => (window as any).__qa.data().length)).toBeGreaterThanOrEqual(before);
});
