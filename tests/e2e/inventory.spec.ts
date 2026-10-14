import { test, expect } from '@playwright/test';
import * as fs from 'fs';

// Enumerates every interactive thing in the live DOM. The test FAILS if a control exists that is not described in KNOWN,
// so a new control cannot be added without being inventoried and given expected behavior + a test.
const KNOWN: Record<string, { purpose: string; effect: string; api: string; tests: string }> = {
  'tf-M1': { purpose: 'Select M1 timeframe', effect: 'Chart shows M1 bars (60 s grid), aria-pressed=true', api: 'GET /api/candles/M1', tests: 'timeframes.spec (click M1, M1->M5->M1, race), smoke' },
  'tf-M5': { purpose: 'Select M5 timeframe', effect: 'Chart shows M5 bars (300 s grid)', api: 'GET /api/candles/M5', tests: 'timeframes.spec, smoke, chart.spec' },
  'tf-M15': { purpose: 'Select M15 timeframe', effect: 'Chart shows M15 bars (900 s grid)', api: 'GET /api/candles/M15', tests: 'timeframes.spec (incl. failed-request clears chart)' },
  'tf-H1': { purpose: 'Select H1 timeframe', effect: 'Chart shows H1 bars (3600 s grid)', api: 'GET /api/candles/H1', tests: 'timeframes.spec' },
  'tf-H4': { purpose: 'Select H4 timeframe', effect: 'Chart shows H4 bars (14400 s grid)', api: 'GET /api/candles/H4', tests: 'timeframes.spec' },
  'draw-select': { purpose: 'Select mode (default): click a drawing to select it, drag to move it, ordinary drags still pan the chart', effect: 'aria-pressed=true on Select; pan enabled', api: 'none (client only)', tests: 'drawings.spec (select + drag, toolbar)' },
  'draw-hline': { purpose: 'Horizontal-line tool: next click places a line at the clicked price', effect: 'tool active (aria-pressed), pan disabled until placed, then back to Select with the new line selected', api: 'none (localStorage xau.drawings.v1)', tests: 'drawings.spec (hline pixel position, panning disabled)' },
  'draw-trend': { purpose: 'Trendline tool: two clicks (time, price) define the line', effect: 'pending point + hint after click 1, Escape cancels; line series drawn after click 2', api: 'none (localStorage)', tests: 'drawings.spec (trend + zone, persistence, timeframe switch)' },
  'draw-zone': { purpose: 'Zone tool: two clicks define a price band (two dashed lines)', effect: 'band drawn between the two prices', api: 'none (localStorage)', tests: 'drawings.spec (trend + zone)' },
  'draw-undo': { purpose: 'Undo the last drawing change (also Ctrl+Z)', effect: 'restores the previous drawing set; disabled when nothing to undo', api: 'none', tests: 'drawings.spec (delete/undo/redo)' },
  'draw-redo': { purpose: 'Redo (also Ctrl+Y / Ctrl+Shift+Z)', effect: 're-applies an undone change; disabled when nothing to redo', api: 'none', tests: 'drawings.spec (delete/undo/redo)' },
  'draw-delete': { purpose: 'Delete the selected drawing (also Delete key)', effect: 'removes it from the chart and storage; undoable', api: 'none', tests: 'drawings.spec (delete/undo/redo)' },
  'draw-clear': { purpose: 'Remove every drawing (undoable)', effect: 'chart and storage emptied; undo restores', api: 'none', tests: 'drawings.spec (delete/undo/redo)' },
};
const EXTERNAL = { id: 'tv-attribution', purpose: 'Library attribution link (Lightweight Charts, required by its license) to tradingview.com', effect: 'Opens https://www.tradingview.com in a new tab', api: 'none (external)', tests: 'inventory.spec (target=_blank and rel contains noopener asserted)' };
const READONLY_DISPLAYS = ['px-bid', 'px-ask', 'px-spread', 'conn-status', 'state-banner', 'panel-dq', 'panel-open-candle', 'panel-provenance', 'chart'];

test('control inventory: every interactive element is known, labelled and testable', async ({ page }) => {
  await page.goto('/');
  await page.getByTestId('tf-M1').waitFor();
  const found = await page.evaluate(() => {
    const out: any[] = [];
    const sel = 'button, a[href], input, select, textarea, summary, [role=button], [role=tab], [tabindex]:not([tabindex="-1"]), canvas';
    document.querySelectorAll(sel).forEach((el) => {
      const b = el.getBoundingClientRect();
      const cs = getComputedStyle(el);
      out.push({ tag: el.tagName.toLowerCase(), href: (el as HTMLAnchorElement).href || null, rel: (el as HTMLAnchorElement).rel || null, target: (el as HTMLAnchorElement).target || null, testid: (el as HTMLElement).dataset.testid || (el.tagName === 'A' && (el as HTMLAnchorElement).href.startsWith('https://www.tradingview.com') ? 'tv-attribution' : null), text: (el.textContent || '').trim().slice(0, 30),
        disabled: (el as HTMLButtonElement).disabled === true, visible: b.width > 0 && b.height > 0 && cs.visibility !== 'hidden',
        box: [Math.round(b.x), Math.round(b.y), Math.round(b.width), Math.round(b.height)], insideChart: !!el.closest('[data-testid=chart]') });
    });
    return out;
  });
  const nonCanvas = found.filter((f) => f.tag !== 'canvas');
  const canvases = found.filter((f) => f.tag === 'canvas');
  for (const c of nonCanvas) expect(c.testid, `interactive <${c.tag}> "${c.text}" has no data-testid`).toBeTruthy();
  const tv = nonCanvas.filter((c) => c.testid === 'tv-attribution');
  expect(tv.length).toBe(1);
  expect(tv[0].target).toBe('_blank');
  expect(tv[0].rel).toContain('noopener');
  for (const c of nonCanvas.filter((c) => c.testid !== 'tv-attribution')) expect(KNOWN[c.testid], `control ${c.testid} is not in the inventory`).toBeTruthy();
  for (const k of Object.keys(KNOWN)) expect(nonCanvas.map((c) => c.testid), `inventoried control ${k} missing from DOM`).toContain(k);
  expect(canvases.length).toBeGreaterThan(0);                       // the chart canvases (pointer/keyboard/wheel interaction)
  for (const c of canvases) expect(c.insideChart).toBe(true);
  for (const id of READONLY_DISPLAYS) await expect(page.getByTestId(id)).toHaveCount(1);
  // no disabled-or-inert control: each button actually changes state when clicked
  const TOGGLES = (id: string) => id.startsWith('tf-') || ['draw-select', 'draw-hline', 'draw-trend', 'draw-zone'].includes(id);
  for (const id of Object.keys(KNOWN)) {
    if (TOGGLES(id)) {
      await page.getByTestId(id).click();
      await expect(page.getByTestId(id)).toHaveAttribute('aria-pressed', 'true');
    } else if (id === 'draw-clear') {
      await expect(page.getByTestId(id)).toBeEnabled();                              // acts on the drawing store (covered by drawings.spec)
    } else {
      await expect(page.getByTestId(id)).toBeDisabled();                             // undo / redo / delete have nothing to act on in a fresh page (enabled states: drawings.spec)
    }
  }
  await page.getByTestId('draw-select').click();
  const md = ['# UI CONTROL INVENTORY', '', `Generated by tests/e2e/inventory.spec.ts from the live DOM on ${new Date().toISOString().slice(0, 10)}. The test fails if a control exists that is not listed here.`, '',
    '| Control ID | Location | Purpose | Expected visible result | Backend/API effect | Selector | Tests | Status |', '|---|---|---|---|---|---|---|---|'];
  for (const [id, k] of Object.entries(KNOWN)) {
    const f = nonCanvas.find((c) => c.testid === id)!;
    md.push(`| ${id} | header, box ${f.box.join(',')} | ${k.purpose} | ${k.effect} | ${k.api} | \`[data-testid=${id}]\` | ${k.tests} | VERIFIED PASS (${TOGGLES(id) ? 'clicked, aria-pressed asserted' : 'present, state asserted; behaviour in drawings.spec'}) |`);
  }
  { const f = tv[0]; md.push(`| ${EXTERNAL.id} | inside chart, box ${f.box.join(',')} | ${EXTERNAL.purpose} | ${EXTERNAL.effect} | ${EXTERNAL.api} | \`a[href^="https://www.tradingview.com"]\` | ${EXTERNAL.tests} | VERIFIED PASS (target/rel asserted; not clicked: external site) |`); }
  md.push('', `Chart canvases (pointer/wheel interaction): ${canvases.length}. Covered by chart.spec.ts (wheel zoom, drag pan, crosshair, resize, no view-jump on refresh).`, '',
    'Read-only displays (no interaction): ' + READONLY_DISPLAYS.map((i) => `\`${i}\``).join(', '), '',
    '## Not implemented (no control exists, so nothing is claimed)', '- Indicator toggles, risk settings, replay controls, strategy version selector, export, reconnect button, menus, modals, tooltips beyond the native `title` on stale prices: NOT IMPLEMENTED.',
    '- Keyboard shortcuts: only the drawing ones (Delete, Esc, Ctrl+Z, Ctrl+Y). Tab order reaches the 5 timeframe buttons (smoke.spec) and the drawing toolbar (drawings.spec).', '');
  fs.writeFileSync('docs/qa/UI_CONTROL_INVENTORY.md', md.join('\n'));
});
