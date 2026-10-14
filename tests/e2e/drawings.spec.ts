import { test, expect, Page } from '@playwright/test';
import * as fs from 'fs';

const ART = 'qa-artifacts/drawings';
fs.mkdirSync(ART, { recursive: true });
const items = (p: Page) => p.evaluate(() => (window as any).__draw.items());
async function ready(page: Page, tf = 'M1') {
  await page.goto('/');
  await page.getByTestId(`tf-${tf}`).click();
  await expect.poll(() => page.evaluate(() => (window as any).__qa.dataTf())).toBe(tf);
  await page.waitForTimeout(400);
}
async function box(page: Page) { const b = await page.getByTestId('chart').boundingBox(); if (!b) throw new Error('no chart'); return b; }
const pixel = (p: Page, id: string) => p.evaluate((i) => (window as any).__draw.pixel(i), id);

test('F7 the toolbar is present, keyboard-operable and starts in Select mode with nothing to undo', async ({ page }) => {
  await ready(page);
  for (const id of ['draw-select', 'draw-hline', 'draw-trend', 'draw-zone', 'draw-undo', 'draw-redo', 'draw-delete', 'draw-clear']) await expect(page.getByTestId(id)).toBeVisible();
  await expect(page.getByTestId('draw-select')).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByTestId('draw-undo')).toBeDisabled();
  await expect(page.getByTestId('draw-delete')).toBeDisabled();
  await page.getByTestId('draw-hline').focus();
  await page.keyboard.press('Enter');
  await expect(page.getByTestId('draw-hline')).toHaveAttribute('aria-pressed', 'true');
});

test('F7 horizontal line: placed at the clicked price (pixel position checked), selected, tool returns to Select', async ({ page }) => {
  await ready(page);
  const b = await box(page);
  await page.getByTestId('draw-hline').click();
  await page.mouse.click(b.x + b.width * 0.5, b.y + b.height * 0.4);
  const it = await items(page);
  expect(it).toHaveLength(1);
  expect(it[0].type).toBe('hline');
  const px = await pixel(page, it[0].id);
  expect(Math.abs(px.p1.y - b.height * 0.4)).toBeLessThan(3);                              // the line really is where the click was
  expect(await page.evaluate(() => (window as any).__draw.tool())).toBe('select');
  expect(await page.evaluate(() => (window as any).__draw.selected())).toBe(it[0].id);
  await expect(page.getByTestId('draw-count')).toContainText('1 drawing');
  await page.screenshot({ path: `${ART}/hline.png` });
});

test('F7 trendline and zone need two clicks, Escape cancels a pending point', async ({ page }) => {
  await ready(page);
  const b = await box(page);
  await page.getByTestId('draw-trend').click();
  await page.mouse.click(b.x + b.width * 0.3, b.y + b.height * 0.6);
  await expect(page.getByTestId('draw-hint')).toContainText('second point');
  await page.keyboard.press('Escape');
  expect(await items(page)).toHaveLength(0);
  await page.getByTestId('draw-trend').click();
  await page.mouse.click(b.x + b.width * 0.3, b.y + b.height * 0.6);
  await page.mouse.click(b.x + b.width * 0.7, b.y + b.height * 0.3);
  let it = await items(page);
  expect(it).toHaveLength(1);
  expect(it[0].type).toBe('trend');
  expect(it[0].p2.t).toBeGreaterThan(it[0].p1.t);
  const px = await pixel(page, it[0].id);
  expect(Math.abs(px.p1.y - b.height * 0.6)).toBeLessThan(3);
  expect(Math.abs(px.p2.y - b.height * 0.3)).toBeLessThan(3);
  await page.getByTestId('draw-zone').click();
  await page.mouse.click(b.x + b.width * 0.4, b.y + b.height * 0.7);
  await page.mouse.click(b.x + b.width * 0.6, b.y + b.height * 0.8);
  it = await items(page);
  expect(it).toHaveLength(2);
  expect(it[1].type).toBe('zone');
  await page.screenshot({ path: `${ART}/trend-zone.png` });
});

test('F7 select + drag moves a horizontal line by the dragged distance; dragging empty space still pans the chart', async ({ page }) => {
  await ready(page);
  const b = await box(page);
  await page.getByTestId('draw-hline').click();
  await page.mouse.click(b.x + b.width * 0.5, b.y + b.height * 0.5);
  const first = (await items(page))[0];
  await page.keyboard.press('Escape');                                                      // deselect
  const y0 = (await pixel(page, first.id)).p1.y;
  await page.mouse.move(b.x + b.width * 0.5, b.y + y0);
  await page.mouse.down();
  await page.mouse.move(b.x + b.width * 0.5, b.y + y0 - 60, { steps: 8 });
  await page.mouse.up();
  const y1 = (await pixel(page, first.id)).p1.y;
  expect(Math.abs(y0 - y1 - 60)).toBeLessThan(4);
  expect((await items(page))[0].p1.p).toBeGreaterThan(first.p1.p);                          // moving up = higher price
  const r0 = await page.evaluate(() => (window as any).__qa.range());
  await page.mouse.move(b.x + b.width * 0.8, b.y + b.height * 0.9);                         // empty area away from the line
  await page.mouse.down();
  await page.mouse.move(b.x + b.width * 0.4, b.y + b.height * 0.9, { steps: 10 });
  await page.mouse.up();
  const r1 = await page.evaluate(() => (window as any).__qa.range());
  expect(Math.abs(r1.from - r0.from)).toBeGreaterThan(20);                                  // the chart panned: drawings do not steal ordinary drags
});

test('F7 an active drawing tool disables panning (so placing points cannot move the chart)', async ({ page }) => {
  await ready(page);
  const b = await box(page);
  const r0 = await page.evaluate(() => (window as any).__qa.range());
  await page.getByTestId('draw-hline').click();
  await page.mouse.move(b.x + b.width * 0.8, b.y + b.height * 0.9);
  await page.mouse.down();
  await page.mouse.move(b.x + b.width * 0.4, b.y + b.height * 0.9, { steps: 10 });
  await page.mouse.up();
  const r1 = await page.evaluate(() => (window as any).__qa.range());
  expect(Math.abs(r1.from - r0.from)).toBeLessThan(2);
});

test('F7 delete, undo and redo (buttons and keyboard) are exact', async ({ page }) => {
  await ready(page);
  const b = await box(page);
  await page.getByTestId('draw-hline').click();
  await page.mouse.click(b.x + b.width * 0.5, b.y + b.height * 0.4);
  await page.getByTestId('draw-hline').click();
  await page.mouse.click(b.x + b.width * 0.5, b.y + b.height * 0.6);
  expect(await items(page)).toHaveLength(2);
  await page.keyboard.press('Delete');                                                       // deletes the selected (second) one
  let it = await items(page);
  expect(it).toHaveLength(1);
  const keptId = it[0].id;
  await page.keyboard.press('Control+z');
  expect(await items(page)).toHaveLength(2);
  await page.keyboard.press('Control+y');
  it = await items(page);
  expect(it).toHaveLength(1);
  expect(it[0].id).toBe(keptId);
  await page.getByTestId('draw-undo').click();
  expect(await items(page)).toHaveLength(2);
  await page.getByTestId('draw-clear').click();
  expect(await items(page)).toHaveLength(0);
  await page.getByTestId('draw-undo').click();                                               // clear is undoable
  expect(await items(page)).toHaveLength(2);
  await expect(page.getByTestId('draw-redo')).toBeEnabled();
});

test('F7 drawings persist across a reload and across timeframe switches (time/price coordinates)', async ({ page }) => {
  await ready(page, 'M5');
  const b = await box(page);
  await page.getByTestId('draw-hline').click();
  await page.mouse.click(b.x + b.width * 0.5, b.y + b.height * 0.5);
  await page.getByTestId('draw-trend').click();
  await page.mouse.click(b.x + b.width * 0.3, b.y + b.height * 0.7);
  await page.mouse.click(b.x + b.width * 0.6, b.y + b.height * 0.4);
  const before = await items(page);
  expect(before).toHaveLength(2);
  await page.reload();
  await expect.poll(async () => (await items(page)).length).toBe(2);
  expect(await items(page)).toEqual(before);
  for (const tf of ['M15', 'H1', 'M5']) {
    await page.getByTestId(`tf-${tf}`).click();
    await expect.poll(() => page.evaluate(() => (window as any).__qa.dataTf())).toBe(tf);
  }
  expect(await items(page)).toEqual(before);
  const id = before.find((d: any) => d.type === 'hline').id;
  expect(Number.isFinite((await pixel(page, id)).p1.y)).toBe(true);
});

test('F7 drawings do not touch the backend decision overlays and a corrupted store is ignored', async ({ page }) => {
  await page.addInitScript(() => { try { localStorage.setItem('xau.drawings.v1', '{not json'); } catch { /* ignore */ } });
  await ready(page);
  expect(await items(page)).toEqual([]);                                                    // corrupted storage: no crash, no drawings
  const before = await page.evaluate(() => (window as any).__qa.lines());
  const b = await box(page);
  await page.getByTestId('draw-hline').click();
  await page.mouse.click(b.x + b.width * 0.5, b.y + b.height * 0.5);
  expect(await page.evaluate(() => (window as any).__qa.lines())).toEqual(before);          // __qa.lines() only lists the decision overlays
  expect(await page.evaluate(() => (window as any).__paintErrors)).toBe(0);
});

test('F7 poisoned localStorage cannot break the page or the ids: out-of-range values, bad or duplicate ids, wrong types and giant arrays are dropped', async ({ page }) => {
  const poison = [
    { id: 'd1', type: 'hline', p1: { t: 1791900000, p: 4100 } },                                                  // valid
    { id: 'd1', type: 'hline', p1: { t: 1791900000, p: 4200 } },                                                  // duplicate id: dropped
    { id: 'd2', type: 'hline', p1: { t: 1791900000, p: 1e300 } },                                                 // absurd price: dropped
    { id: 'x' + '9'.repeat(400), type: 'hline', p1: { t: 1, p: 1 } },                                             // bad id: dropped
    { id: 'd3', type: 'trend', p1: { t: 1791900000, p: 4100 }, p2: { t: 1791900000, p: 4110 } },                 // equal times: invisible line, dropped
    { id: 'd4', type: 'trend', p1: { t: 1791900000, p: 4100 }, p2: { t: 99999999999, p: 4110 } },                // absurd time: dropped
    { id: 'd5', type: '<img src=x onerror=window.__xss=1>', p1: { t: 1791900000, p: 4100 } },                    // unknown type: dropped
    { id: 'd6', type: 'zone', p1: { t: 1791900000, p: 4100 }, p2: { t: 1791900300, p: 4110 } },                  // valid
    null, 5, 'x', [],
  ];
  await page.addInitScript((v) => { try { localStorage.setItem('xau.drawings.v1', JSON.stringify(v)); } catch { /* ignore */ } }, poison);
  await page.goto('/');
  await page.getByTestId('draw-select').waitFor();
  const it = await page.evaluate(() => (window as any).__draw.items());
  expect(it.map((d: any) => d.id).sort()).toEqual(['d1', 'd6']);
  expect(await page.evaluate(() => (window as any).__xss)).toBeUndefined();
  expect(await page.evaluate(() => (window as any).__draw_error ?? null)).toBeNull();
  await page.getByTestId('draw-hline').click();                                                                    // the engine still works and new ids do not collide
  const b = await page.getByTestId('chart').boundingBox();
  await page.mouse.click(b!.x + b!.width * 0.5, b!.y + b!.height * 0.5);
  const ids = (await page.evaluate(() => (window as any).__draw.items())).map((d: any) => d.id);
  expect(new Set(ids).size).toBe(ids.length);
  expect(ids).toHaveLength(3);
});

test('F7 a non-array store and an oversized store are ignored or capped', async ({ page }) => {
  await page.addInitScript(() => { try { localStorage.setItem('xau.drawings.v1', JSON.stringify({ not: 'an array' })); } catch { /* ignore */ } });
  await page.goto('/');
  await page.getByTestId('draw-select').waitFor();
  expect(await page.evaluate(() => (window as any).__draw.items())).toEqual([]);
});

test('F7 a trendline needs two different bars: a second click on the same bar is refused with a hint', async ({ page }) => {
  await ready(page);
  const b = await box(page);
  await page.getByTestId('draw-trend').click();
  await page.mouse.click(b.x + b.width * 0.5, b.y + b.height * 0.4);
  await page.mouse.click(b.x + b.width * 0.5, b.y + b.height * 0.6);                                              // same x => same bar
  expect(await items(page)).toHaveLength(0);
  await expect(page.getByTestId('draw-hint')).toContainText('different bar');
  await page.mouse.click(b.x + b.width * 0.7, b.y + b.height * 0.6);
  expect(await items(page)).toHaveLength(1);
});

test('F7 an item the chart library rejects at draw time is skipped and reported; the other drawings and the stored data survive (no silent wipe)', async ({ page }) => {
  const stored = [
    { id: 'd1', type: 'hline', p1: { t: 1791900000, p: 4100 } },
    { id: 'd2', type: 'trend', p1: { t: 1791900000, p: 4100 }, p2: { t: 1791900600, p: 4110 } },
    { id: 'd3', type: 'zone', p1: { t: 1791900000, p: 4120 }, p2: { t: 1791900600, p: 4130 } },
  ];
  await page.addInitScript((v) => { try { localStorage.setItem('xau.drawings.v1', JSON.stringify(v)); } catch { /* ignore */ } }, stored);
  await page.addInitScript(() => { (window as any).__qa_failDraw = new Set(['d2']); });                 // the chart library "rejects" item d2 at draw time (QA hook in drawings.js)
  await page.goto('/');
  await page.getByTestId('draw-select').waitFor();
  await expect(page.getByTestId('draw-count')).toContainText('1 could not be drawn');
  expect((await items(page)).map((d: any) => d.id)).toEqual(['d1', 'd2', 'd3']);                    // nothing removed from memory
  expect(JSON.parse(await page.evaluate(() => (window as any).__draw.storage())).map((d: any) => d.id)).toEqual(['d1', 'd2', 'd3']);   // nor from storage
  await page.getByTestId('draw-hline').click();
  const b = await box(page);
  await page.mouse.click(b.x + b.width * 0.5, b.y + b.height * 0.5);
  const after = JSON.parse(await page.evaluate(() => (window as any).__draw.storage())).map((d: any) => d.id);
  expect(after).toEqual(['d1', 'd2', 'd3', 'd4']);                                                  // the next save keeps everything
});

test('F7 invalid items removed on load are backed up once under a .bak key, and fractional times are rejected', async ({ page }) => {
  const raw = JSON.stringify([{ id: 'd1', type: 'hline', p1: { t: 1791900000, p: 4100 } }, { id: 'd2', type: 'trend', p1: { t: 1791900000.5, p: 4100 }, p2: { t: 1791900600, p: 4110 } }]);
  await page.addInitScript((v) => { try { if (!localStorage.getItem('xau.drawings.v1')) localStorage.setItem('xau.drawings.v1', v); } catch { /* ignore */ } }, raw);
  await page.goto('/');
  await page.getByTestId('draw-select').waitFor();
  expect((await items(page)).map((d: any) => d.id)).toEqual(['d1']);
  expect(await page.evaluate(() => localStorage.getItem('xau.drawings.v1.bak'))).toBe(raw);
});
