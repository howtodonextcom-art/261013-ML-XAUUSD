import { test, expect, Page } from '@playwright/test';

// Accessibility basics: landmarks, DOM order = reading order = visual order on narrow screens, keyboard order, visible focus, status announcements.
// (No automated axe audit is installed: colour contrast, screen-reader speech output and the chart canvas itself are NOT covered.)
const SETUP = { setup_id: 'M15-BUY-1', direction: 'BUY', state: 'ENTRY_ELIGIBLE', evidence: [], invalidation_level: 4099.8, entry_level: 4103.2, next_required_event: 'x', expires_at: 1_791_928_800 };
function p(action: string, primary: string, extra: any = {}) {
  return { type: 'intel', evaluated_at: 1_791_925_680, mode: 'READ_ONLY+SHADOW+PAPER_SIMULATION', bars: {}, status: {}, analysis: {}, zones: [], setup_events: [], m1_shadow: null,
    market: { direction_tf: 'H1', direction: 'UP', conflict_tf: 'H4', conflict_direction: 'NONE', conflict: false, regime: {}, history: 'OK' }, overlays: { zone: null, lines: [], direction: null },
    decision: { kind: 'RESEARCH_DECISION', execution_authorized: false, strategy_version: 'x', dataset_version: 'FIXTURE', action, primary_reason: primary, layer: 'strategy', strategy_eligible: action === 'BUY',
      reasons: { market: [], strategy: [primary], gate: [] }, setup: extra.setup ?? null, plan: extra.plan ?? null, risk: null, next_required: 'x' } };
}
async function fixture(page: Page, first: any) {
  let cur = first;
  let killed = false;
  await page.route('**/api/intel', (r) => r.fulfill({ json: cur }));
  await page.routeWebSocket(/\/ws$/, (ws) => {
    const server = ws.connectToServer();
    server.onMessage((m) => { try { if (JSON.parse(String(m)).type === 'intel') return; } catch { /* forward */ } if (!killed) ws.send(m); });
    const t = setInterval(() => { if (killed) { clearInterval(t); ws.close(); } else ws.send(JSON.stringify(cur)); }, 300);
  });
  return { set: (x: any) => { cur = x; }, kill: () => { killed = true; } };
}

test('F12 landmarks: banner, main, two named complementary regions, named region cards, a polite status region', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('banner')).toBeVisible();
  await expect(page.getByRole('main')).toBeVisible();
  await expect(page.getByRole('complementary', { name: 'Decision and risk' })).toBeVisible();
  await expect(page.getByRole('complementary', { name: /Market, M1 shadow, history/ })).toBeVisible();
  for (const name of [/Decision · research/, /Market intelligence/, /M1 entry intelligence/, /History & research/]) await expect(page.getByRole('region', { name })).toBeVisible();
  await expect(page.getByRole('application', { name: /Price chart/ })).toBeVisible();
  expect(await page.getByTestId('sr-status').getAttribute('aria-live')).toBe('polite');
  expect(await page.getByTestId('conn-status').getAttribute('role')).toBe('status');
});

test('F12 DOM order is the reading order (decision, chart, panels) and equals the visual order on a phone', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await page.getByTestId('decision-card').waitFor();
  const order = await page.evaluate(() => {
    const ids = ['decision-card', 'chart', 'market-card', 'm1-card', 'history-card'];
    const els = ids.map((i) => document.querySelector(`[data-testid=${i}]`)!) as HTMLElement[];
    const dom = els.every((e, i) => i === 0 || (els[i - 1].compareDocumentPosition(e) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0);
    const tops = els.map((e) => e.getBoundingClientRect().top + scrollY);
    return { dom, tops, visual: tops.every((t, i) => i === 0 || tops[i - 1] <= t) };
  });
  expect(order.dom).toBe(true);
  expect(order.visual).toBe(true);
});

test('F12 keyboard: Tab reaches the timeframes, the drawing tools and the layer toggles in that order, and every stop has a visible focus indicator', async ({ page }) => {
  await page.goto('/');
  await page.getByTestId('tf-M1').waitFor();
  await page.evaluate(() => (document.activeElement as HTMLElement)?.blur());
  const seen: string[] = [];
  const outlines: boolean[] = [];
  for (let i = 0; i < 34; i++) {
    await page.keyboard.press('Tab');
    const info = await page.evaluate(() => { const e = document.activeElement as HTMLElement; const cs = getComputedStyle(e); return { id: e.dataset?.testid ?? e.tagName, visible: cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) >= 1 }; });
    if (info.id === 'BODY') break;                                                               // Tab wrapped around: every focusable element of the page was visited
    seen.push(info.id); outlines.push(info.visible);
  }
  const pos = (id: string) => seen.indexOf(id);
  for (const id of ['tf-M1', 'tf-H4', 'draw-select', 'draw-hline', 'layer-ema20', 'layer-m1']) expect(pos(id), `${id} not reached by Tab`).toBeGreaterThanOrEqual(0);
  expect(pos('tf-M1')).toBeLessThan(pos('draw-select'));
  expect(pos('draw-select')).toBeLessThan(pos('layer-ema20'));
  expect(outlines.every(Boolean), `a focus stop without a visible outline: ${seen.filter((_, i) => !outlines[i]).join(', ')}`).toBe(true);
  // a toggle works from the keyboard
  await page.getByTestId('layer-structure').focus();
  const before = await page.getByTestId('layer-structure').getAttribute('aria-pressed');
  await page.keyboard.press('Enter');
  await expect(page.getByTestId('layer-structure')).toHaveAttribute('aria-pressed', before === 'true' ? 'false' : 'true');
  await page.keyboard.press('Space');
  await expect(page.getByTestId('layer-structure')).toHaveAttribute('aria-pressed', before!);
});

test('F12 decision changes are announced politely once per change (not on every refresh), and a stale decision is announced', async ({ page }) => {
  const f = await fixture(page, p('WAIT', 'AWAITING_PULLBACK'));
  await page.goto('/');
  await expect(page.getByTestId('sr-status')).toContainText('Research decision WAIT: AWAITING PULLBACK');
  await expect(page.getByTestId('sr-status')).toContainText('not an order');
  const changes = await page.evaluate(() => new Promise<number>((res) => { let n = 0; const mo = new MutationObserver(() => n++); mo.observe(document.querySelector('[data-testid=sr-status]')!, { childList: true, characterData: true, subtree: true }); setTimeout(() => { mo.disconnect(); res(n); }, 2500); }));
  expect(changes).toBe(0);                                                                       // the same decision resent every 300 ms does not re-announce
  f.set(p('BUY', 'ENTRY_ELIGIBLE', { setup: SETUP, plan: { direction: 'BUY', entry: 4103.2, stop_loss: 4099.8, take_profit: 4118.4, tp2_reference: 4110, net_rr: 3.4, gross_rr: 4, risk_fraction: 0.005, size_hidden: true } }));
  await expect(page.getByTestId('sr-status')).toContainText('Research decision BUY: ENTRY ELIGIBLE');
  f.kill();
  await expect(page.getByTestId('sr-status')).toContainText('STALE', { timeout: 8000 });
});
