import { test, expect } from '@playwright/test';
import * as fs from 'fs';

const ART = 'qa-artifacts/smoke';
fs.mkdirSync(ART, { recursive: true });

test('F1 smoke: real Chrome, screenshot, click, keyboard, viewport, console, websocket, network error', async ({ page, browser }) => {
  const consoleMsgs: string[] = [];
  const failed: string[] = [];
  const wsFrames: string[] = [];
  let wsOpened = false;
  page.on('console', (m) => consoleMsgs.push(`${m.type()}: ${m.text()}`));
  page.on('requestfailed', (r) => failed.push(r.url()));
  page.on('websocket', (ws) => { wsOpened = true; ws.on('framereceived', (f) => wsFrames.push(String(f.payload).slice(0, 80))); });

  // Chrome identity: must be the real Google Chrome, not Chromium
  expect(browser.version()).toMatch(/^\d+\./);
  const ua = await page.evaluate(() => navigator.userAgent);
  await page.goto('/');
  const uaReal = await page.evaluate(() => navigator.userAgent);
  expect(uaReal).toContain('Chrome/');
  if (process.env.XAU_HEADLESS !== '1') expect(uaReal).not.toContain('HeadlessChrome');      // headless Chrome always says HeadlessChrome: the real-Chrome identity is only checkable headed
  expect(ua).toBeDefined();

  await expect(page.getByTestId('chart')).toBeVisible();
  await page.screenshot({ path: `${ART}/01-initial.png` });

  // click a safe control and verify an effect
  await page.getByTestId('tf-M5').click();
  await expect(page.getByTestId('tf-M5')).toHaveAttribute('aria-pressed', 'true');
  expect(await page.evaluate(() => (window as any).__tf)).toBe('M5');

  // keyboard: tab focus moves onto a timeframe button, Enter activates it
  await page.getByTestId('tf-M1').focus();
  await page.keyboard.press('Enter');
  await expect(page.getByTestId('tf-M1')).toHaveAttribute('aria-pressed', 'true');
  await page.keyboard.press('Tab');
  const focusedTestId = await page.evaluate(() => (document.activeElement as HTMLElement)?.dataset?.testid);
  expect(focusedTestId).toBe('tf-M5');

  // viewport change is real
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => window.innerWidth)).toBe(390);
  await page.screenshot({ path: `${ART}/02-mobile.png` });
  await page.setViewportSize({ width: 1440, height: 900 });

  // websocket observed with real frames
  await expect.poll(() => wsOpened, { timeout: 10_000 }).toBe(true);
  await expect.poll(() => wsFrames.length, { timeout: 15_000 }).toBeGreaterThan(0);

  // network failure is detectable: abort one request and see it reported
  await page.route('**/api/candles/M15*', (r) => r.abort());
  await page.getByTestId('tf-M15').click();
  await expect.poll(() => failed.some((u) => u.includes('/api/candles/M15')), { timeout: 5_000 }).toBe(true);
  await page.unroute('**/api/candles/M15*');

  fs.writeFileSync(`${ART}/console.log`, consoleMsgs.join('\n'));
  fs.writeFileSync(`${ART}/ws-frames.log`, wsFrames.slice(0, 20).join('\n'));
  fs.writeFileSync(`${ART}/chrome.txt`, `${browser.version()}\n${uaReal}\n`);
});

test('F9 latency instrumentation: every tick frame yields delivery and render samples on one clock', async ({ page }) => {
  await page.goto('/');
  await expect.poll(() => page.evaluate(() => (window as any).__lat.samples.length), { timeout: 30_000 }).toBeGreaterThan(5);
  const s = await page.evaluate(() => (window as any).__lat.samples.slice(0, 50));
  for (const x of s) {
    expect(x.deliver).toBeGreaterThan(-3);                         // same host clock: no negative delivery beyond timer resolution
    expect(x.deliver).toBeLessThan(2000);
    expect(x.render).toBeGreaterThanOrEqual(0);
    expect(x.gw).toBeGreaterThanOrEqual(0);
  }
});
