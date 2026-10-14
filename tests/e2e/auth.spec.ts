import { test, expect } from '@playwright/test';

// A browser WITHOUT the session cookie: nothing with data may be reachable (real Chrome, real gateway).
test.use({ storageState: { cookies: [], origins: [] } });

test('F8 without the session cookie the dashboard, the API and the WebSocket are refused', async ({ page, request }) => {
  const r = await page.goto('/');
  expect(r!.status()).toBe(401);
  await expect(page.locator('body')).toContainText('Authentication required');
  expect((await request.get('/api/intel')).status()).toBe(401);
  expect((await request.get('/api/health')).status()).toBe(401);
  expect((await request.get('/api/candles/M1')).status()).toBe(401);
  const ws = await page.evaluate(() => new Promise<string>((res) => {
    const w = new WebSocket(`ws://${location.host}/ws`);
    w.onmessage = () => res('DATA');
    w.onclose = () => res('CLOSED');
    w.onerror = () => res('ERROR');
    setTimeout(() => res('TIMEOUT'), 4000);
  }));
  expect(['CLOSED', 'ERROR']).toContain(ws);
});

test('F8 a wrong token is refused and sets no cookie; a page on another origin cannot read the stream', async ({ page, context, request }) => {
  const r = await request.get('/?token=definitely-wrong', { maxRedirects: 0 });
  expect(r.status()).toBe(401);
  expect((await context.cookies()).length).toBe(0);
  // cross-origin page (a data: URL has the opaque origin 'null') trying to open the WebSocket: refused by the Origin check
  await page.goto('data:text/html,<title>evil</title>');
  const res = await page.evaluate(() => new Promise<string>((resolve) => {
    const w = new WebSocket('ws://127.0.0.1:8765/ws');
    w.onmessage = () => resolve('DATA');
    w.onclose = () => resolve('CLOSED');
    w.onerror = () => resolve('ERROR');
    setTimeout(() => resolve('TIMEOUT'), 4000);
  }));
  expect(['CLOSED', 'ERROR']).toContain(res);
});

test('F8 the one-time token URL logs the browser in, redirects to a clean URL and keeps the session on reload', async ({ page }) => {
  const fs = await import('fs');
  const token = (process.env.XAU_API_TOKEN ?? fs.readFileSync('configs/api_token', 'utf8')).trim();
  await page.goto('/?token=' + encodeURIComponent(token));
  await expect(page).toHaveURL(/\/$/);                                   // the token is not left in the address bar
  expect(page.url()).not.toContain('token');
  await expect(page.getByTestId('conn-status')).toBeVisible();
  await page.reload();
  await expect(page.getByTestId('conn-status')).toBeVisible();
  const c = (await page.context().cookies()).find((k) => k.name === 'xau_session')!;
  expect(c.httpOnly).toBe(true);
  expect(c.sameSite).toBe('Strict');
  expect(c.value).not.toBe(token);
});
