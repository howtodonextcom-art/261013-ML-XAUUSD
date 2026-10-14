// User drawing tools (P8): horizontal line, trendline, zone; select / drag / delete; undo / redo; persistence in localStorage.
// Drawings are the USER's own annotations: they never feed the decision, they are drawn in colours and with titles that cannot be confused with the
// backend overlays (ENTRY / SL / TP / ZONE hi-lo, which come from the decision record). Coordinates are (time, price), so they survive timeframe changes
// (a point between two bars of a coarser timeframe adds one extra slot to the time axis: known cosmetic limit).
(() => {
  const KEY = 'xau.drawings.v1';
  const el = document.getElementById('chart');
  const COL = { hline: '#e0b84c', trend: '#c084fc', zone: '#38bdf8', sel: '#ffffff' };
  let items = [], sel = null, tool = 'select', pending = null, undo = [], redo = [], drag = null, seq = 0;
  const refs = new Map();                              // id -> { lines: [priceLine], line: lineSeries }
  const q = (id) => document.getElementById(id);

  // stored items are UNTRUSTED input (localStorage can be poisoned): strict ranges and id format, so a poisoned value can neither break the first render
  // (killing the module on every page load) nor collide ids (select/delete hitting several items)
  const okP = (v) => Number.isFinite(v) && Math.abs(v) < 1e6;                                  // XAUUSD prices are in the thousands
  const okT = (v) => Number.isFinite(v) && v > 1e9 && v < 4e9;                                  // epoch seconds, 2001-2096
  const valid = (d) => !!d && typeof d === 'object' && ['hline', 'trend', 'zone'].includes(d.type) && typeof d.id === 'string' && /^d\d{1,9}$/.test(d.id) && !!d.p1 && okP(d.p1.p)
    && (d.type === 'hline' || (!!d.p2 && okP(d.p2.p) && okT(d.p1.t) && okT(d.p2.t) && (d.type === 'zone' || d.p1.t !== d.p2.t)));
  function load() { try { const raw = JSON.parse(localStorage.getItem(KEY) || '[]'); items = Array.isArray(raw) ? raw.filter(valid).slice(0, 500) : []; const seen = new Set(); items = items.filter((d) => !seen.has(d.id) && seen.add(d.id)); seq = items.reduce((m, d) => Math.max(m, +d.id.slice(1)), 0); } catch (e) { items = []; } }
  function save() { try { localStorage.setItem(KEY, JSON.stringify(items)); } catch (e) { /* private window: drawings simply do not persist */ } }
  function snap() { undo.push(JSON.stringify(items)); if (undo.length > 100) undo.shift(); redo = []; }
  const restore = (s) => { items = JSON.parse(s); if (!items.some((d) => d.id === sel)) sel = null; save(); render(); };

  function clearRefs() {
    for (const r of refs.values()) {
      (r.lines || []).forEach((l) => { try { series.removePriceLine(l); } catch (e) { /* already gone */ } });
      if (r.line) { try { chart.removeSeries(r.line); } catch (e) { /* already gone */ } }
    }
    refs.clear();
  }
  function render() {
    try { renderUnsafe(); } catch (e) { clearRefs(); items = items.slice(0, 0); status(); window.__draw_error = String(e && e.message || e); }      // a failing render never kills the page
  }
  function renderUnsafe() {
    clearRefs();
    for (const d of items) {
      const on = d.id === sel, col = on ? COL.sel : COL[d.type], r = { lines: [] };
      const pl = (price, title) => r.lines.push(series.createPriceLine({ price, color: col, lineWidth: on ? 2 : 1, lineStyle: d.type === 'trend' ? 0 : 3, axisLabelVisible: true, title }));
      if (d.type === 'hline') pl(d.p1.p, '✎ H-LINE');
      else if (d.type === 'zone') { pl(Math.max(d.p1.p, d.p2.p), '✎ ZONE hi'); pl(Math.min(d.p1.p, d.p2.p), '✎ ZONE lo'); }
      else if (d.p1.t !== d.p2.t) {
        const pts = [d.p1, d.p2].sort((a, b) => a.t - b.t).map((p) => ({ time: p.t, value: p.p }));
        r.line = chart.addSeries(LightweightCharts.LineSeries, { color: col, lineWidth: on ? 3 : 2, lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false });
        r.line.setData(pts);
      }
      refs.set(d.id, r);
    }
    status();
  }
  function status() {
    const n = items.length;
    q('draw-count').textContent = n ? `${n} drawing${n > 1 ? 's' : ''}` : '';
    q('draw-undo').disabled = !undo.length; q('draw-redo').disabled = !redo.length; q('draw-delete').disabled = !sel;
    document.querySelectorAll('[data-tool]').forEach((b) => b.setAttribute('aria-pressed', b.dataset.tool === tool ? 'true' : 'false'));
    q('draw-hint').textContent = pending ? 'click the second point (Esc cancels)' : tool === 'select' ? '' : tool === 'hline' ? 'click to place a horizontal line' : 'click the first point';
  }

  const rect = () => el.getBoundingClientRect();
  const toPoint = (cx, cy) => {
    const r = rect(), x = cx - r.left, y = cy - r.top;
    let t = chart.timeScale().coordinateToTime(x);
    if (t == null) { const d = series.data(); t = d.length ? d[d.length - 1].time : null; }       // whitespace right of the last bar: clamp to the last bar
    const p = series.coordinateToPrice(y);
    return t == null || p == null ? null : { t: Number(t), p: Number(p) };
  };
  const px = (pt) => { const x = chart.timeScale().timeToCoordinate(pt.t), y = series.priceToCoordinate(pt.p); return { x: x == null ? NaN : x, y: y == null ? NaN : y }; };
  const segDist = (x, y, a, b) => {
    const dx = b.x - a.x, dy = b.y - a.y, L = dx * dx + dy * dy;
    const t = L ? Math.max(0, Math.min(1, ((x - a.x) * dx + (y - a.y) * dy) / L)) : 0;
    return Math.hypot(x - (a.x + t * dx), y - (a.y + t * dy));
  };
  function dist(d, x, y) {
    if (d.type === 'hline') { const py = px(d.p1).y; return Number.isNaN(py) ? Infinity : Math.abs(y - py); }
    const a = px(d.p1), b = px(d.p2);
    if (d.type === 'trend') return [a, b].some((v) => Number.isNaN(v.x) || Number.isNaN(v.y)) ? Infinity : segDist(x, y, a, b);
    if ([a.y, b.y].some(Number.isNaN)) return Infinity;
    const top = Math.min(a.y, b.y), bot = Math.max(a.y, b.y);
    return y >= top && y <= bot ? 0 : Math.min(Math.abs(y - top), Math.abs(y - bot));
  }
  const hit = (cx, cy) => {
    const r = rect(), x = cx - r.left, y = cy - r.top;
    let best = null, bd = 8;
    for (const d of items) { const v = dist(d, x, y); if (v <= bd) { bd = v; best = d; } }
    return best;
  };

  function setTool(t) {
    tool = t; pending = null;
    chart.applyOptions({ handleScroll: t === 'select' });          // a drawing tool must not pan the chart while placing points
    el.style.cursor = t === 'select' ? '' : 'crosshair';
    status();
  }
  function add(d) { snap(); d.id = 'd' + (++seq); items.push(d); sel = d.id; save(); render(); }
  function remove() { if (!sel) return; snap(); items = items.filter((d) => d.id !== sel); sel = null; save(); render(); }

  el.addEventListener('click', (e) => {
    if (tool === 'select' || drag) return;
    const pt = toPoint(e.clientX, e.clientY);
    if (!pt) return;
    if (tool === 'hline') { add({ type: 'hline', p1: pt }); setTool('select'); return; }
    if (!pending) { pending = pt; status(); return; }
    if (tool === 'trend' && pt.t === pending.t) { q('draw-hint').textContent = 'pick a different bar for the second point (a trendline needs two different times)'; return; }
    add({ type: tool, p1: pending, p2: pt }); setTool('select');
  });
  el.addEventListener('mousedown', (e) => {
    if (tool !== 'select' || e.button !== 0) return;
    const d = hit(e.clientX, e.clientY);
    if (!d) { if (sel) { sel = null; render(); } return; }          // empty space: the chart pans as usual
    sel = d.id;
    let mode = 'move';
    if (d.type === 'trend') {
      const r = rect(), x = e.clientX - r.left, y = e.clientY - r.top;
      if (Math.hypot(x - px(d.p1).x, y - px(d.p1).y) < 10) mode = 'p1'; else if (Math.hypot(x - px(d.p2).x, y - px(d.p2).y) < 10) mode = 'p2';
    }
    drag = { id: d.id, mode, last: toPoint(e.clientX, e.clientY), moved: false };
    chart.applyOptions({ handleScroll: false });
    e.stopPropagation(); e.preventDefault();
    render();
  }, true);
  window.addEventListener('mousemove', (e) => {
    if (!drag) return;
    const d = items.find((v) => v.id === drag.id), cur = toPoint(e.clientX, e.clientY);
    if (!d || !cur) return;
    if (!drag.moved) { snap(); drag.moved = true; }
    if (d.type === 'hline') d.p1.p = cur.p;
    else if (drag.mode === 'p1') d.p1 = { t: cur.t, p: cur.p };
    else if (drag.mode === 'p2') d.p2 = { t: cur.t, p: cur.p };
    else if (drag.last) {
      const dp = cur.p - drag.last.p, dt = cur.t - drag.last.t;
      d.p1 = { t: d.p1.t + (d.type === 'trend' ? dt : 0), p: d.p1.p + dp }; d.p2 = { t: d.p2.t + (d.type === 'trend' ? dt : 0), p: d.p2.p + dp };
    }
    drag.last = cur;
    render();
  });
  window.addEventListener('mouseup', () => {
    if (!drag) return;
    const moved = drag.moved; drag = null;
    chart.applyOptions({ handleScroll: tool === 'select' });
    if (moved) save();
    setTimeout(() => { /* a click that ends a drag must not place a point */ }, 0);
  });
  window.addEventListener('keydown', (e) => {
    if (e.target && e.target.closest && e.target.closest('input, textarea, select, [contenteditable="true"]')) return;         // never hijack typing
    const k = e.key;
    if ((k === 'Delete' || k === 'Backspace') && sel) { remove(); e.preventDefault(); }
    else if (k === 'Escape') { pending = null; if (tool !== 'select') setTool('select'); else { sel = null; render(); } }
    else if ((e.ctrlKey || e.metaKey) && k.toLowerCase() === 'z' && !e.shiftKey) { doUndo(); e.preventDefault(); }
    else if ((e.ctrlKey || e.metaKey) && (k.toLowerCase() === 'y' || (k.toLowerCase() === 'z' && e.shiftKey))) { doRedo(); e.preventDefault(); }
  });
  function doUndo() { if (!undo.length) return; redo.push(JSON.stringify(items)); restore(undo.pop()); }
  function doRedo() { if (!redo.length) return; undo.push(JSON.stringify(items)); restore(redo.pop()); }

  const bar = q('draw-bar');
  bar.querySelectorAll('[data-tool]').forEach((b) => { b.onclick = () => setTool(b.dataset.tool); });
  q('draw-undo').onclick = doUndo; q('draw-redo').onclick = doRedo; q('draw-delete').onclick = remove;
  q('draw-clear').onclick = () => { if (!items.length) return; snap(); items = []; sel = null; save(); render(); };
  load(); render();
  window.__draw = { items: () => JSON.parse(JSON.stringify(items)), tool: () => tool, selected: () => sel, pending: () => pending,
    pixel: (id) => { const d = items.find((v) => v.id === id); return d ? { p1: px(d.p1), p2: d.p2 ? px(d.p2) : null } : null; }, storage: () => { try { return localStorage.getItem(KEY); } catch (e) { return null; } } };
})();
