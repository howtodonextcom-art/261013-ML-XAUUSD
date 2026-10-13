import { test, expect } from '@playwright/test';
import * as fs from 'fs';

const ART = 'qa-artifacts/responsive';
fs.mkdirSync(ART, { recursive: true });

// Browser zoom z on a 1440x900 window == CSS viewport (1440/z x 900/z) at devicePixelRatio z. Chrome's native Ctrl +/- cannot be
// delivered through CDP, so zoom is emulated this way (same layout viewport and DPR the page sees). Documented in BROWSER_TEST_MATRIX.
const ZOOMS = [0.67, 0.8, 1, 1.25, 1.5, 2];
const VIEWPORTS: [string, number, number, number][] = [
  ['desktop-1440x900', 1440, 900, 1], ['laptop-1152x720', 1152, 720, 1], ['fhd-1920x1080', 1920, 1080, 1],
  ['mobile-390x844', 390, 844, 2], ['desktop-1440x900@dpr2', 1440, 900, 2],
];
const cases: [string, number, number, number][] = [
  ...ZOOMS.map((z) => [`zoom-${Math.round(z * 100)}%`, Math.round(1440 / z), Math.round(900 / z), z] as [string, number, number, number]),
  ...VIEWPORTS,
];

for (const [name, w, h, dpr] of cases) {
  test(`F4 layout ${name} (${w}x${h} @dpr${dpr})`, async ({ browser }) => {
    const ctx = await browser.newContext({ viewport: { width: w, height: h }, deviceScaleFactor: dpr });
    const page = await ctx.newPage();
    await page.goto('/');
    await expect(page.getByTestId('conn-status')).toHaveText('CONNECTED_ACTIVE', { timeout: 15_000 });
    await expect.poll(() => page.evaluate(() => (window as any).__qa.dataTf())).toBe('M1');
    await page.waitForTimeout(400);
    const m = await page.evaluate(() => {
      const r = (sel: string) => document.querySelector(sel)!.getBoundingClientRect();
      const vis = (el: Element) => { const b = el.getBoundingClientRect(); return b.width > 0 && b.height > 0 && b.right > 0 && b.left < innerWidth; };
      const tfs = [...document.querySelectorAll('[data-testid^=tf-]')];
      const clipped: string[] = [];
      for (const el of document.querySelectorAll('header *, aside td, .card h3')) {
        const e = el as HTMLElement;
        if (e.children.length === 0 && e.scrollWidth > e.clientWidth + 1 && getComputedStyle(e).overflow !== 'visible') clipped.push(e.textContent || '');
      }
      const chart = r('[data-testid=chart]');
      const aside = document.querySelector('aside')!.getBoundingClientRect();
      const overlap = !(chart.right <= aside.left + 1 || aside.right <= chart.left + 1 || chart.bottom <= aside.top + 1 || aside.bottom <= chart.top + 1);
      return {
        innerWidth, scrollW: document.documentElement.scrollWidth, dpr: devicePixelRatio,
        tfAllVisible: tfs.length === 5 && tfs.every(vis), tfMinSize: Math.min(...tfs.map((e) => Math.min(e.getBoundingClientRect().width, e.getBoundingClientRect().height))),
        statusVisible: vis(document.querySelector('[data-testid=conn-status]')!), bidVisible: vis(document.querySelector('[data-testid=px-bid]')!),
        chartW: chart.width, chartH: chart.height, chartRight: chart.right, overlap, clipped,
      };
    });
    await page.screenshot({ path: `${ART}/${name}.png` });
    expect(m.dpr).toBeCloseTo(dpr, 1);                         // zoom/DPR really applied
    expect(m.innerWidth).toBe(w);
    expect(m.scrollW, 'horizontal overflow').toBeLessThanOrEqual(w + 1);
    expect(m.tfAllVisible, 'timeframe buttons reachable').toBe(true);
    expect(m.tfMinSize, 'tap target >= 20 CSS px').toBeGreaterThanOrEqual(20);
    expect(m.statusVisible && m.bidVisible).toBe(true);
    expect(m.chartRight).toBeLessThanOrEqual(w + 1);
    expect(m.chartW).toBeGreaterThan(Math.min(250, w * 0.6));
    expect(m.chartH).toBeGreaterThan(Math.min(240, h * 0.35));
    expect(m.overlap, 'sidebar overlaps chart').toBe(false);
    expect(m.clipped, 'clipped text').toEqual([]);
    await ctx.close();
  });
}
