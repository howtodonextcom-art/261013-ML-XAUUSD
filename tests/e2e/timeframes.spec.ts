import { test, expect } from '@playwright/test';
import * as fs from 'fs';

const ART = 'qa-artifacts/timeframes';
fs.mkdirSync(ART, { recursive: true });
const SEC: Record<string, number> = { M1: 60, M5: 300, M15: 900, H1: 3600, H4: 14400 };
const MIN_HISTORY: Record<string, number> = { M1: 1000, M5: 1000, M15: 500, H1: 500, H4: 250 };

async function chartData(page) {
  return page.evaluate(() => (window as any).__qa.data().map((d: any) => ({ t: d.time, o: d.open, h: d.high, l: d.low, c: d.close })));
}

test.describe('F3 timeframe switching shows the real timeframe', () => {
  for (const tf of Object.keys(SEC)) {
    test(`click ${tf}: chart bars are ${tf} bars with real history, equal to backend`, async ({ page, request }) => {
      await page.goto('/');
      await page.getByTestId('tf-M1').waitFor();
      await page.getByTestId(`tf-${tf}`).click();
      await expect.poll(() => page.evaluate(() => (window as any).__qa.dataTf()), { timeout: 10_000 }).toBe(tf);
      await expect(page.getByTestId(`tf-${tf}`)).toHaveAttribute('aria-pressed', 'true');
      for (const other of Object.keys(SEC).filter((x) => x !== tf)) await expect(page.getByTestId(`tf-${other}`)).toHaveAttribute('aria-pressed', 'false');

      const d = await chartData(page);
      expect(d.length).toBeGreaterThanOrEqual(MIN_HISTORY[tf]);        // history, not just bars since gateway start
      for (const b of d) expect(b.t % SEC[tf]).toBe(0);                 // every bar is on this timeframe's bucket grid
      const gaps = d.slice(1).map((b: any, i: number) => b.t - d[i].t);
      expect(Math.min(...gaps)).toBeGreaterThanOrEqual(SEC[tf]);        // no bar is shorter than the timeframe, no duplicates
      const sorted = [...gaps].sort((a: number, b: number) => a - b);
      expect(sorted[Math.floor(sorted.length / 2)]).toBe(SEC[tf]);      // median spacing EXACTLY the timeframe: a coarser TF under a finer label fails too
      for (const b of d) { expect(b.h).toBeGreaterThanOrEqual(Math.max(b.o, b.c)); expect(b.l).toBeLessThanOrEqual(Math.min(b.o, b.c)); }

      // UI data == backend data (sampled from the last 50 closed bars; the forming bar may move)
      const api = await (await request.get(`/api/candles/${tf}?limit=2000`)).json();
      const apiBy = new Map(api.candles.map((c: any) => [c.time, c]));
      const sample = d.slice(-52, -2);
      for (const b of sample) { const a: any = apiBy.get(b.t); expect(a, `bar ${b.t} missing in API`).toBeTruthy(); expect([a.open, a.high, a.low, a.close]).toEqual([b.o, b.h, b.l, b.c]); }
      await page.screenshot({ path: `${ART}/${tf}.png` });
    });
  }

  test('M1 then M5 then M1 does not leave M5 data under the M1 label', async ({ page }) => {
    await page.goto('/');
    await page.getByTestId('tf-M5').click();
    await expect.poll(() => page.evaluate(() => (window as any).__qa.dataTf())).toBe('M5');
    await page.getByTestId('tf-M1').click();
    await expect.poll(() => page.evaluate(() => (window as any).__qa.dataTf())).toBe('M1');
    const d = await chartData(page);
    const gaps = d.slice(1).map((b: any, i: number) => b.t - d[i].t);
    expect(Math.min(...gaps)).toBe(60);   // M1 spacing is back (5-minute data would have min gap 300)
  });

  test('rapid timeframe clicking ends on the last clicked timeframe with matching data (race)', async ({ page }) => {
    await page.goto('/');
    for (const tf of ['M5', 'H1', 'M15', 'H4', 'M1', 'H1', 'M5']) await page.getByTestId(`tf-${tf}`).click({ delay: 0 });
    await expect.poll(() => page.evaluate(() => (window as any).__qa.dataTf()), { timeout: 10_000 }).toBe('M5');
    const d = await chartData(page);
    for (const b of d) expect(b.t % 300).toBe(0);
    expect(Math.min(...d.slice(1).map((b: any, i: number) => b.t - d[i].t))).toBeGreaterThanOrEqual(300);
  });

  test('failed candle request clears the chart and shows an error (no stale data under the new label)', async ({ page }) => {
    await page.goto('/');
    await page.getByTestId('tf-M5').click();
    await expect.poll(() => page.evaluate(() => (window as any).__qa.dataTf())).toBe('M5');
    await page.route('**/api/candles/M15*', (r) => r.abort());
    await page.getByTestId('tf-M15').click();
    await expect(page.getByTestId('state-banner')).toContainText('Could not load M15');
    expect((await chartData(page)).length).toBe(0);
    expect(await page.evaluate(() => (window as any).__qa.dataTf())).toBeNull();
    await page.unroute('**/api/candles/M15*');
    await page.getByTestId('tf-M15').click();
    await expect.poll(() => page.evaluate(() => (window as any).__qa.dataTf())).toBe('M15');
    await expect(page.getByTestId('state-banner')).toBeHidden();
  });
});
