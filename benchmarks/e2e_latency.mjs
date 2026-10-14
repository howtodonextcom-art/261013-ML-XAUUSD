// End-to-end latency benchmark in REAL Chrome against the live gateway (Level 5.1 P3).
//   node benchmarks/e2e_latency.mjs [secondsPerScenario=40]
// Per tick frame (from window.__lat in the dashboard): gateway = receipt-to-publish inside the gateway (monotonic clock);
// delivery = browser receipt minus gateway publish wall clock (SAME host clock, no skew); render = next paint minus browser receipt;
// market = gateway receipt minus the tick's server stamp converted with the measured server UTC offset (includes terminal/network time AND any skew
// between the broker clock and this PC's clock, so it is an upper-level indication, not a pure latency). Scenarios: foreground, background tab,
// 100 drawings, CPU load (busy processes). Output: results/p3/e2e_latency.json. Sample sizes and stalls are reported; nothing is extrapolated.
import { chromium, request } from '@playwright/test';
import { spawn } from 'node:child_process';
import fs from 'node:fs';

const SECS = Number(process.argv[2] ?? 40);
const base = process.env.XAU_BASE_URL ?? 'http://127.0.0.1:8765';
const token = (process.env.XAU_API_TOKEN ?? fs.readFileSync('configs/api_token', 'utf8')).trim();
const pct = (a, q) => { if (!a.length) return null; const s = [...a].sort((x, y) => x - y); return +s[Math.min(s.length - 1, Math.floor((q / 100) * s.length))].toFixed(3); };
const stats = (a) => ({ n: a.length, p50: pct(a, 50), p95: pct(a, 95), p99: pct(a, 99), max: a.length ? +Math.max(...a).toFixed(3) : null });

const api = await request.newContext({ baseURL: base, extraHTTPHeaders: { authorization: 'Bearer ' + token } });
const health = await (await api.get('/api/health')).json();
const offsetS = health.detail.server_utc_offset_s;
await api.get('/?token=' + encodeURIComponent(token), { maxRedirects: 0 }).catch(() => {});
const browser = await chromium.launch({ channel: 'chrome', headless: false });
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const r = await ctx.request.get(base + '/?token=' + encodeURIComponent(token), { maxRedirects: 0 });
if (r.status() !== 303 && r.status() !== 200) throw new Error('login failed ' + r.status());

async function collect(page, ms, warmMs = 0) {
  if (warmMs) await new Promise((res) => setTimeout(res, warmMs));          // let the page settle after a reload (history fetch, drawings) before measuring steady state
  await page.evaluate(() => { window.__lat.samples.length = 0; });
  await new Promise((res) => setTimeout(res, ms));
  const s = await page.evaluate(() => window.__lat.samples.slice());
  const recv = s.map((x) => x.recv).filter((v) => v).sort((a, b) => a - b);
  let maxGap = 0; for (let i = 1; i < recv.length; i++) maxGap = Math.max(maxGap, recv[i] - recv[i - 1]);
  return { frames: s.length, frames_per_s: +(s.length / (ms / 1000)).toFixed(2), max_gap_between_frames_ms: +maxGap.toFixed(0),
    gateway_ms: stats(s.map((x) => x.gw)), delivery_ms: stats(s.map((x) => x.deliver)), render_ms: stats(s.map((x) => x.render)),
    market_ms_incl_clock_skew: stats(s.map((x) => x.recv - (x.tick - offsetS * 1000))), hidden_fraction: +(s.filter((x) => x.hidden).length / Math.max(1, s.length)).toFixed(2) };
}
const out = { at: new Date().toISOString(), chrome: browser.version(), seconds_per_scenario: SECS, server_utc_offset_s: offsetS, scenarios: {} };
const page = await ctx.newPage();
await page.goto(base + '/');
await page.getByTestId('conn-status').waitFor();
await page.waitForFunction(() => window.__lat.samples.length > 3, null, { timeout: 60000 });

console.log('foreground...');
out.scenarios.foreground = await collect(page, SECS * 1000);

console.log('background tab...');
const other = await ctx.newPage(); await other.goto('about:blank'); await other.bringToFront();
out.scenarios.background_tab = await collect(page, SECS * 1000);
await page.bringToFront(); await other.close();

console.log('100 drawings...');
await page.evaluate(() => { const items = []; for (let i = 0; i < 100; i++) items.push({ id: 'd' + i, type: i % 3 === 0 ? 'hline' : i % 3 === 1 ? 'zone' : 'trend', p1: { t: 1791900000 + i * 600, p: 4100 + (i % 20) * 3 }, p2: { t: 1791910000 + i * 600, p: 4110 + (i % 20) * 3 } }); localStorage.setItem('xau.drawings.v1', JSON.stringify(items)); });
await page.reload(); await page.getByTestId('conn-status').waitFor();
await page.waitForFunction(() => window.__lat.samples.length > 3, null, { timeout: 60000 });
out.drawings_loaded = await page.evaluate(() => window.__draw.items().length);
out.scenarios.drawings_100_after_reload = await collect(page, 6000, 0);
out.scenarios.drawings_100 = await collect(page, SECS * 1000, 10000);
await page.evaluate(() => localStorage.removeItem('xau.drawings.v1')); await page.reload();
await page.waitForFunction(() => window.__lat.samples.length > 3, null, { timeout: 60000 });

console.log('CPU load...');
const cores = (await import('node:os')).cpus().length;
const burners = Array.from({ length: Math.max(1, Math.floor(cores / 2)) }, () => spawn('python', ['-c', 'while True: pass'], { stdio: 'ignore' }));
out.cpu_burners = burners.length; out.cpu_cores = cores;
try { out.scenarios.cpu_load = await collect(page, SECS * 1000); } finally { burners.forEach((b) => b.kill()); }

const h2 = await (await api.get('/api/health')).json();
out.gateway_health_latency_after = h2.gateway_latency_ms;
out.console_errors = 0;
fs.mkdirSync('results/p3', { recursive: true });
fs.writeFileSync('results/p3/e2e_latency.json', JSON.stringify(out, null, 1));
console.log(JSON.stringify(Object.fromEntries(Object.entries(out.scenarios).map(([k, v]) => [k, { frames: v.frames, gw: v.gateway_ms.p99, delivery: v.delivery_ms.p99, render: v.render_ms.p99, gap: v.max_gap_between_frames_ms }])), null, 1));
await browser.close();
