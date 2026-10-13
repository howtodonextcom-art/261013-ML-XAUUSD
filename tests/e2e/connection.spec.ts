import { test, expect } from '@playwright/test';
import { execSync, exec } from 'child_process';
import * as fs from 'fs';

const ART = 'qa-artifacts/connection';
fs.mkdirSync(ART, { recursive: true });

function gatewayPids(): string[] {
  const out = execSync('netstat -ano', { encoding: 'utf8' });
  return [...new Set(out.split('\n').filter((l) => /:8765\s+.*LISTENING/.test(l)).map((l) => l.trim().split(/\s+/).pop()!))];
}
function stopGateway() { for (const p of gatewayPids()) execSync(`taskkill /PID ${p} /F`, { stdio: 'ignore' }); }
// `start /B` through cmd.exe: a node-detached powershell exits immediately on Windows (verified), this one stays alive.
function startGateway() { exec('start "" /B powershell -NoProfile -WindowStyle Hidden -File scripts/windows/run_gateway.ps1', { shell: 'cmd.exe', windowsHide: true }, () => {}); }
const status = (page) => page.getByTestId('conn-status');

async function healthOk(): Promise<boolean> { try { return (await fetch('http://127.0.0.1:8765/api/health')).ok; } catch { return false; } }
async function ensureGateway() {
  if (await healthOk()) return;
  startGateway();
  for (let i = 0; i < 60 && !(await healthOk()); i++) await new Promise((r) => setTimeout(r, 1000));
  if (!(await healthOk())) throw new Error('gateway could not be (re)started');
}
test.describe.configure({ mode: 'serial' });
test.beforeAll(ensureGateway);
test.afterAll(ensureGateway);   // tests here kill the gateway on purpose: always leave it running
test.setTimeout(120_000);

test('F5 gateway stop -> DISCONNECTED, stale price is marked, no fake live; restart -> recovers with same-origin data', async ({ page, request }) => {
  await page.goto('/');
  await expect(status(page)).toHaveText('CONNECTED_ACTIVE', { timeout: 15_000 });
  await expect.poll(async () => await page.getByTestId('px-bid').textContent()).not.toBe('–');
  const lastBarBefore = await page.evaluate(() => { const d = (window as any).__qa.data(); return d[d.length - 1].time; });
  await page.screenshot({ path: `${ART}/1-connected.png` });

  stopGateway();
  await expect(status(page)).toHaveText('DISCONNECTED', { timeout: 15_000 });
  await expect(page.getByTestId('state-banner')).toBeVisible();
  await expect(page.getByTestId('state-banner')).toContainText('DISCONNECTED');
  // the last price stays on screen for reference but must be visibly flagged as not live
  await expect(page.getByTestId('px-bid')).toHaveAttribute('data-stale', 'true');
  const frozen = await page.getByTestId('px-bid').textContent();
  await page.waitForTimeout(2500);
  expect(await page.getByTestId('px-bid').textContent()).toBe(frozen);        // value is frozen, never invented or repeated as new
  expect(frozen).not.toBe('–');
  await page.screenshot({ path: `${ART}/2-disconnected.png` });

  startGateway();
  await expect.poll(async () => { try { return (await request.get('/api/health')).ok(); } catch { return false; } }, { timeout: 60_000, intervals: [1000] }).toBe(true);
  await expect(status(page)).toHaveText('CONNECTED_ACTIVE', { timeout: 40_000 });     // the page's own websocket reconnects
  await expect(page.getByTestId('px-bid')).not.toHaveAttribute('data-stale', 'true', { timeout: 15_000 });
  await expect(page.getByTestId('state-banner')).toBeHidden();
  // seam/sync after reconnect: chart reaches at least the previous last bar, history is intact
  await page.reload();
  await expect(status(page)).toHaveText('CONNECTED_ACTIVE', { timeout: 20_000 });
  await expect.poll(() => page.evaluate(() => (window as any).__qa.dataTf())).toBe('M1');
  const d = await page.evaluate(() => (window as any).__qa.data().map((x: any) => x.time));
  expect(d[d.length - 1]).toBeGreaterThanOrEqual(lastBarBefore);
  expect(d.length).toBeGreaterThan(1000);
  expect(new Set(d).size).toBe(d.length);           // no duplicate bars after the restart
  await page.screenshot({ path: `${ART}/3-recovered.png` });
});

test('F5 silent websocket (open but no frames, e.g. blackholed network) -> UI flags TRANSPORT_STALLED within seconds, then recovers', async ({ page }) => {
  let stall = false;
  await page.routeWebSocket(/\/ws$/, (ws) => {
    const server = ws.connectToServer();
    server.onMessage((m) => { if (!stall) ws.send(m); });   // forward server frames only while not stalled
    ws.onMessage((m) => server.send(m));
  });
  await page.goto('/');
  await expect(status(page)).toHaveText('CONNECTED_ACTIVE', { timeout: 20_000 });
  stall = true;
  const t0 = Date.now();
  await expect(status(page)).toHaveText('TRANSPORT_STALLED', { timeout: 10_000 });
  expect(Date.now() - t0).toBeLessThan(9_000);                       // heartbeat is 1 s; detection must be quick, not 60 s
  await expect(page.getByTestId('px-bid')).toHaveAttribute('data-stale', 'true');
  await expect(page.getByTestId('state-banner')).toContainText('TRANSPORT_STALLED');
  await page.screenshot({ path: `${ART}/4-transport-stalled.png` });
  stall = false;
  await expect(status(page)).toHaveText('CONNECTED_ACTIVE', { timeout: 10_000 });   // frames resume => state clears
  await expect(page.getByTestId('px-bid')).not.toHaveAttribute('data-stale', 'true');
});
