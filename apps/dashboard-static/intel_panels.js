// Intelligence panels and chart layers. EVERYTHING here is a display of backend data (/api/intel payload, /api/indicators, /api/research): nothing is computed
// from prices in the browser, nothing repaints (events carry the backend's `known_at`), and a stale or disconnected state clears every layer and panel.
(() => {
  const KEY = 'xau.layers.v1';
  const DEF = { ema20: false, ema50: false, ema200: false, zones: true, structure: false, setups: true, m1: true, c2: true, decisions: true, history: true, mid: false };
  const COLORS = { ema20: '#4aa3ff', ema50: '#f0b90b', ema200: '#c084fc' };
  const SEC = { M1: 60, M5: 300, M15: 900, H1: 3600, H4: 14400 };
  let layers = { ...DEF }, emaSeries = {}, zoneLines = [], markersApi = null, intel = null, highlight = null, emaTf = null, emaLastFetch = 0;
  try { layers = { ...DEF, ...JSON.parse(localStorage.getItem(KEY) || '{}') }; } catch (e) { /* defaults */ }
  const save = () => { try { localStorage.setItem(KEY, JSON.stringify(layers)); } catch (e) { /* ignore */ } };
  const q = (id) => document.getElementById(id);
  const hhmm = (s) => (s == null ? '–' : new Date(s * 1000).toISOString().slice(11, 16));
  const px2 = (v) => (v == null || Number.isNaN(Number(v)) ? '–' : Number(v).toFixed(2));
  const E = (s) => String(s ?? '').replace(/[&<>"']/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));

  // ------------------------------------------------------------------ chart layers
  function snapTime(t) {                                              // the bar of the CURRENT timeframe that contains time t (binary search in the shown data)
    const d = series.data();
    if (!d.length) return null;
    const bar = Math.floor(t / SEC[tf]) * SEC[tf];
    let lo = 0, hi = d.length - 1, ans = -1;
    while (lo <= hi) { const m = (lo + hi) >> 1; if (d[m].time <= bar) { ans = m; lo = m + 1; } else hi = m - 1; }
    return ans < 0 || t >= d[ans].time + SEC[tf] ? null : d[ans].time;      // never the nearest EARLIER candle when the moment lies in a missing bar or after the last one (round 15)
  }
  let markerInfo = new Map();                                         // bar time -> lines of tooltip text (rebuilt with the markers; shown on crosshair hover)
  const clock = (s) => (s == null ? '–' : new Date(s * 1000).toISOString().slice(11, 19));
  function v1Info(e, current) {
    const pl = e.plan || {};
    const lines = [`${e.action === 'BLOCKED' ? 'V1 BLOCKED (research)' : `V1 ${e.action} · RESEARCH`}${current ? ' · CURRENT' : ' · HISTORICAL, not a current signal'}`,
      `published ${clock(e.published_at)} server time · setup known ${clock(e.known_at)}${e.publish_latency_s != null ? ` (+${e.publish_latency_s}s)` : ''}`,
      `setup ${e.setup_id} · ${e.primary_reason}`];
    if (pl.entry != null) lines.push(`entry ${px2(pl.entry)} · SL ${px2(pl.stop_loss)} · TP ${px2(pl.take_profit)} · net R:R ${px2(pl.net_rr)}${e.action === 'BLOCKED' ? ' (hypothetical: blocked)' : ''}`);
    if (e.valid && e.valid.invalidation_level != null) lines.push(`invalidation ${px2(e.valid.invalidation_level)} · expires ~${hhmm(e.valid.expires_at)}`);
    lines.push(`${e.strategy_version} · ${e.dataset_version} · not an order`);
    return lines;
  }
  function note(t, lines) { markerInfo.set(t, (markerInfo.get(t) || []).concat([lines])); }
  function mapEvent(t) {                                              // {time, reason}: the candle of the CURRENT timeframe that contains t, or WHY there is none
    const d = series.data();
    if (!d.length) return { time: null, reason: 'NO_CANDLES' };
    const bar = Math.floor(t / SEC[tf]) * SEC[tf];
    let lo = 0, hi = d.length - 1, ans = -1;
    while (lo <= hi) { const m = (lo + hi) >> 1; if (d[m].time <= bar) { ans = m; lo = m + 1; } else hi = m - 1; }
    if (ans < 0) return { time: null, reason: 'BEFORE_FIRST_CANDLE' };
    if (t >= d[ans].time + SEC[tf]) return { time: null, reason: ans === d.length - 1 ? 'AFTER_LAST_CANDLE' : 'MISSING_BAR' };
    return { time: d[ans].time, reason: 'OK' };
  }
  // ---------------------------------------------------------------- setup events: realtime (newest 12) + history from /api/setup_events, merged by stable id
  const LETTER = { SETUP_FORMING: 'F', CONFIRMED: 'C', EXPIRED: 'X', INVALIDATED: 'I', MISSED: 'M' };
  const NAME = { F: 'forming (impulse found)', C: 'confirmed by a closed bar', X: 'expired', I: 'invalidated', M: 'missed (price ran away)' };
  const TERMINAL = new Set(['INVALIDATED', 'MISSED', 'EXPIRED']);
  const hist = new Map(), ranges = []; let histMeta = null, loading = false, histErr = null, rangeTimer = null, retryAt = 0;
  const RETRY_MS = () => window.__histRetryMs ?? 30000;
  const evId = (e) => e.event_id || `${e.setup_id}|${e.state}|${e.known_at}`;
  function allEvents() {                                              // history first, then the realtime events (LIVE wins a duplicate)
    const m = new Map(hist);
    for (const e of (intel && intel.setup_events) || []) m.set(evId(e), { ...e, event_id: evId(e), provenance: e.provenance || 'LIVE_ENGINE', realtime: true });
    return [...m.values()].sort((a, b) => a.known_at - b.known_at);
  }
  function visibleSpan() {
    const d = series.data(), r = chart.timeScale().getVisibleLogicalRange();
    if (!d.length || !r) return null;
    const i0 = Math.max(0, Math.floor(r.from)), i1 = Math.min(d.length - 1, Math.ceil(r.to));
    return { t0: d[i0].time, t1: d[i1].time + SEC[tf], bars: Math.max(1, Math.round(r.to - r.from)) };
  }
  const covered = (a, b) => ranges.some(([x, y]) => x <= a && y >= b);
  async function ensureLoaded() {
    if (loading || !intel || Date.now() < retryAt) return;
    const v = visibleSpan();
    if (!v) return;
    const pad = Math.max(v.t1 - v.t0, SEC[tf] * 50);
    const a = v.t0 - pad, b = v.t1 + pad;
    if (covered(a, b)) return;
    loading = true;
    try {
      let cursor = null, replayFailed = false;
      const fresh = new Map();
      for (let page = 0; page < 8; page++) {
        const r = await fetch(`/api/setup_events?from=${Math.floor(a)}&to=${Math.ceil(b)}&limit=2000${cursor != null ? `&cursor=${cursor}` : ''}`);
        if (!r.ok) throw new Error('HTTP ' + r.status);
        const j = await r.json();
        histMeta = { total: j.total_events, live: j.live_engine_events, replay: j.replay_events, error: j.replay_error, version: j.setup_version };
        for (const e of j.events) fresh.set(e.event_id, e);
        replayFailed = replayFailed || !!j.replay_error;
        if (!j.truncated) break;
        cursor = j.next_cursor;
      }
      for (const [id, e] of [...hist]) if (e.known_at >= a && e.known_at <= b && !fresh.has(id)) hist.delete(id);     // the server's timeline for this period replaces ours (no stale leftovers)
      for (const [id, e] of fresh) hist.set(id, e);
      if (replayFailed) { retryAt = Date.now() + RETRY_MS(); histErr = 'replay unavailable (' + (histMeta && histMeta.error) + '): showing the live engine events only, retrying'; }
      else { ranges.push([a, b]); histErr = null; }
    } catch (e) { histErr = String(e.message || e); }
    loading = false;
    drawMarkers(); renderInspector();
  }
  function onRange() { clearTimeout(rangeTimer); rangeTimer = setTimeout(() => { drawMarkers(); renderInspector(); ensureLoaded(); }, 200); }
  chart.timeScale().subscribeVisibleLogicalRangeChange(onRange);
  function visibleSetupEvents() {                                     // classify EVERY loaded event: drawn, or the reason it is not
    const out = { visible: [], hidden: [], outside: [], unmapped: [] };
    for (const e of allEvents()) {
      const mid = !LETTER[e.state];
      const hiddenWhy = !layers.setups ? 'layer "Setups" is off' : (!e.realtime && !layers.history) ? 'layer "History" is off' : (mid && !layers.mid) ? 'intermediate states are filtered out' : null;
      const mp = mapEvent(e.known_at - 1);
      if (mp.reason === 'BEFORE_FIRST_CANDLE' || mp.reason === 'AFTER_LAST_CANDLE') out.outside.push({ e, why: mp.reason === 'BEFORE_FIRST_CANDLE' ? 'older than the first loaded candle of this timeframe' : 'after the last loaded candle' });
      else if (mp.reason !== 'OK') out.unmapped.push({ e, why: mp.reason === 'MISSING_BAR' ? 'no candle at that time (missing bar)' : 'no candles loaded' });
      else if (hiddenWhy) out.hidden.push({ e, why: hiddenWhy, time: mp.time });
      else out.visible.push({ e, time: mp.time });
    }
    return out;
  }
  function setupMarkers(out) {
    const vs = visibleSetupEvents();
    const sp = visibleSpan();
    const zoomedOut = !sp || sp.bars > 300;                           // far out: shapes only; the tooltip and the inspector keep every detail
    const groups = new Map();                                         // (candle, side) -> events: several events on one candle are ONE marker whose tooltip lists all of them
    for (const x of vs.visible) { const k = `${x.time}|${x.e.direction}`; if (!groups.has(k)) groups.set(k, { time: x.time, side: x.e.direction, evs: [] }); groups.get(k).evs.push(x.e); }
    for (const g of groups.values()) {
      const rank = (e) => (TERMINAL.has(e.state) ? 3 : e.state === 'CONFIRMED' ? 2 : e.state === 'SETUP_FORMING' ? 1 : 0);
      const top = g.evs.reduce((a, b) => (rank(b) > rank(a) ? b : a));
      const letters = [...new Set(g.evs.map((e) => LETTER[e.state]).filter(Boolean))];
      const sideCh = g.side === 'BUY' ? 'B' : 'S';
      const term = TERMINAL.has(top.state);
      out.push({ time: g.time, position: g.side === 'BUY' ? 'belowBar' : 'aboveBar', color: term ? '#f0b90b' : top.state === 'CONFIRMED' ? '#2ebd85' : '#7d8aa0', shape: term ? 'square' : 'circle', size: 1,
                 text: zoomedOut || !letters.length ? '' : `${sideCh}·${letters.join('·')}`, info: g.evs.map((e) => e.state).join(',') });
      const lines = [`${g.evs.length} setup event${g.evs.length > 1 ? 's' : ''} on this candle · ${g.side}-side setup${g.evs.length > 1 ? 's' : ''} (observations, NOT decisions)`];
      for (const e of g.evs) lines.push(`${LETTER[e.state] ? LETTER[e.state] + ' ' + NAME[LETTER[e.state]] : e.state.replaceAll('_', ' ').toLowerCase()} · known ${clock(e.known_at)} · ${(e.reasons || []).join(', ') || '–'} · ${e.provenance === 'REPLAY' ? 'REPLAY of stored bars' : 'LIVE engine'} · ${e.setup_id}`);
      lines.push('marker on the candle that closes when the event became known (bar-close convention)');
      note(g.time, lines);
    }
    return vs;
  }
  function inspectorStats(vs) {
    const s = histMeta ? histMeta.total : (intel && intel.setup_events_total) || 0;
    return `Backend events ${s} · Loaded ${allEvents().length} · Visible ${vs.visible.length} · Hidden ${vs.hidden.length} · Outside range ${vs.outside.length} · Unmapped ${vs.unmapped.length}`;
  }
  function renderInspector() {
    const box = q('ev-stats');
    if (!box) return;
    if (!intel) { box.textContent = ''; q('ev-list').replaceChildren(); return; }
    const vs = visibleSetupEvents();
    box.textContent = inspectorStats(vs) + (loading ? ' · loading…' : '') + (histErr ? ` · history error: ${histErr}` : '');
    box.title = 'Backend = all setup events the backend knows. Loaded = fetched for the viewed period. Visible = drawn. Hidden = loaded but a layer/filter is off. Outside range = before the first / after the last loaded candle of this timeframe. Unmapped = no candle at that time (missing bar).';
    const sp = visibleSpan();
    const rows = [...vs.visible, ...vs.hidden].filter((x) => sp && x.time >= sp.t0 - SEC[tf] && x.time <= sp.t1).sort((a, b) => b.e.known_at - a.e.known_at);
    const list = q('ev-list');
    list.replaceChildren(...rows.slice(0, 60).map((x) => {
      const b = document.createElement('button');
      b.className = 'linkish'; b.dataset.testid = 'ev-row'; b.title = 'Locate this event on the chart (no recompute, no repaint)';
      b.textContent = `${new Date(x.e.known_at * 1000).toISOString().slice(5, 16).replace('T', ' ')} · ${x.e.direction}-side · ${LETTER[x.e.state] || '·'} ${x.e.state.replaceAll('_', ' ').toLowerCase()} · ${x.e.provenance === 'REPLAY' ? 'replay' : 'live'}${x.why ? ' · hidden: ' + x.why : ''}`;
      b.onclick = () => inspect(x.e.known_at - 1);
      const d = document.createElement('div'); d.appendChild(b); return d;
    }));
    if (rows.length > 60) { const m = document.createElement('div'); m.className = 'small'; m.textContent = `showing the newest 60 of ${rows.length} events in view: zoom in for the rest`; list.appendChild(m); }
    if (!rows.length) { const m = document.createElement('div'); m.className = 'small'; m.textContent = 'no setup event in the viewed period'; list.appendChild(m); }
  }
  function markers() {
    const out = [];
    markerInfo = new Map();
    if (!intel) return out;
    if (layers.decisions) {
      for (const e of intel.v1_events || []) {                        // BACKEND decision events: placed on the candle that contains the PUBLICATION time (never earlier)
        const t = snapTime(e.published_at);
        if (t == null) continue;
        const cur = e.decision_id === intel.v1_current_id;
        const buy = e.action === 'BUY', sell = e.action === 'SELL';
        out.push({ time: t, position: buy ? 'belowBar' : 'aboveBar', color: buy ? '#2ebd85' : sell ? '#ff6b7f' : '#ff9f1c', shape: buy ? 'arrowUp' : sell ? 'arrowDown' : 'square', size: cur ? 2 : 1,
                   text: buy ? (cur ? 'BUY · RESEARCH · NOW' : 'BUY · RESEARCH') : sell ? (cur ? 'SELL · RESEARCH · NOW' : 'SELL · RESEARCH') : 'BLOCKED', info: v1Info(e, cur).join(' | ') });
        note(t, v1Info(e, cur));
      }
    }
    if (layers.structure) {
      for (const tfk of ['M15', 'H1']) {
        const evs = ((intel.analysis || {})[tfk] || {}).events_recent || [];
        for (const e of evs) { const t = snapTime(e.bar_open_time ?? e.known_at); if (t != null) out.push({ time: t, position: 'aboveBar', color: '#9aa7bb', shape: 'circle', size: 1, text: String(e.event).includes('UP') ? '▲' : '▼', info: `${tfk} ${String(e.event).replace('_', ' ')}` }); }
      }
    }
    setupMarkers(out);
    if (layers.m1 && intel.m1_shadow) {
      for (const e of intel.m1_shadow.events_recent || []) {
        if (e.kind === 'WINDOW_STATE' || !['M1_TRIGGERED', 'M5_CONFIRMED_AWAITING_M1'].includes(e.stage)) continue;
        const t = snapTime(e.bar_time);
        if (t != null) out.push({ time: t, position: e.direction === 'BUY' ? 'belowBar' : 'aboveBar', color: '#38bdf8', shape: e.direction === 'BUY' ? 'arrowUp' : 'arrowDown', size: 1, text: e.stage === 'M1_TRIGGERED' ? 'V2 SHADOW' : '', info: `shadow ${e.kind === 'M5_CONFIRMED' ? 'M5 conf.' : e.kind.replace('M1_', '')}` });
      }
    }
    if (layers.c2 && intel.scalp_c2) {
      for (const e of intel.scalp_c2.events_recent || []) {
        if (e.stage !== 'M1_TRIGGERED' || e.kind === 'WINDOW_STATE') continue;
        const t = snapTime(e.bar_time);
        if (t != null) out.push({ time: t, position: e.direction === 'BUY' ? 'belowBar' : 'aboveBar', color: '#a855f7', shape: e.direction === 'BUY' ? 'arrowUp' : 'arrowDown', size: 1, text: 'C2 ' + e.direction, info: `scalp-c2 ${String(e.kind).replace('M1_', '')} (${e.alignment || '?'} to H1) research only` });
      }
      const cs = intel.scalp_c2;
      if (cs.signal === 'BLOCKED' && cs.trigger) { const t = snapTime(cs.trigger.known_at - 60); if (t != null) out.push({ time: t, position: cs.side === 'BUY' ? 'belowBar' : 'aboveBar', color: '#a855f7', shape: 'square', size: 1, text: 'C2 BLOCKED', info: `scalp-c2 BLOCKED: ${(cs.block_reasons || []).join(', ')}` }); }
    }
    if (highlight != null) { const t = snapTime(highlight); if (t != null) out.push({ time: t, position: 'inBar', color: '#ffffff', shape: 'circle', size: 2, text: '', info: 'inspected' }); }
    out.sort((a, b) => a.time - b.time);
    return out;
  }
  function drawMarkers() {
    try {
      if (!markersApi) markersApi = LightweightCharts.createSeriesMarkers(series, []);
      markersApi.setMarkers(markers());
    } catch (e) { window.__layer_error = String(e.message || e); }
  }
  function clearZoneLines() { zoneLines.forEach((l) => { try { series.removePriceLine(l); } catch (e) { /* gone */ } }); zoneLines = []; }
  function drawZones() {
    clearZoneLines();
    if (!layers.zones || !intel) return;
    for (const z of (intel.zones || []).slice(0, 3)) {                  // the three nearest zones only: the chart stays readable (the panel lists them too)
      const col = z.side === 'SUPPORT' ? '#2a9d8f' : z.side === 'RESISTANCE' ? '#c0392b' : '#8a8f98';
      zoneLines.push(series.createPriceLine({ price: z.high, color: col, lineWidth: 1, lineStyle: 1, axisLabelVisible: false, title: `${z.side[0]}${z.touches}` }));
      zoneLines.push(series.createPriceLine({ price: z.low, color: col, lineWidth: 1, lineStyle: 1, axisLabelVisible: false, title: '' }));
    }
  }
  async function loadEma(force) {
    const need = ['ema20', 'ema50', 'ema200'].filter((k) => layers[k]);
    for (const k of Object.keys(emaSeries)) emaSeries[k].applyOptions({ visible: !!layers[k] });
    if (!need.length) return;
    const now = Date.now();
    if (!force && emaTf === tf && now - emaLastFetch < 20000 && need.every((k) => emaSeries[k])) return;
    const req = tf;
    try {
      const r = await fetch(`/api/indicators/${req}?limit=1500`);
      if (!r.ok || req !== tf) return;                                // a newer timeframe click won the race: never paint another timeframe's EMA
      const d = await r.json();
      for (const k of need) {
        if (!emaSeries[k]) emaSeries[k] = chart.addSeries(LightweightCharts.LineSeries, { color: COLORS[k], lineWidth: 1, lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false });
        emaSeries[k].setData(d.time.map((t, i) => ({ time: t, value: d[k][i] })).filter((x) => x.value != null));
        emaSeries[k].applyOptions({ visible: true });
      }
      emaTf = req; emaLastFetch = now;
      drawMarkers();
    } catch (e) { /* the layer simply stays as it was */ }
  }
  function clearAllLayers() {
    clearZoneLines();
    for (const k of Object.keys(emaSeries)) emaSeries[k].applyOptions({ visible: false });
    try { if (markersApi) markersApi.setMarkers([]); } catch (e) { /* ignore */ }
  }

  // ------------------------------------------------------------------ panels
  const dirWord = (d) => ({ UP: 'UP', DOWN: 'DOWN', NONE: 'no direction', UNKNOWN: 'unknown' }[d] || d || '?');
  function renderMarket(p) {
    const m = p.market || {}, a = p.analysis || {};
    const reg = m.regime || {};
    q('market-direction').textContent = `${m.direction_tf || 'H1'} ${dirWord(m.direction)} · ${m.conflict_tf || 'H4'} ${dirWord(m.conflict_direction)}${m.conflict ? ' · CONFLICT' : ''}`;
    q('market-regime').textContent = ['H4', 'H1', 'M15'].map((t) => `${t}: ${reg[t] || '–'}`).join(' · ');
    q('market-structure').textContent = ['H4', 'H1', 'M15', 'M5', 'M1'].filter((t) => a[t]).map((t) => `${t} ${a[t].structure_trend || '–'}/${a[t].ema_alignment || '–'}`).join(' · ');
    const i15 = a.M15 || {}, i1h = a.H1 || {};
    q('market-indicators').textContent = `RSI M15 ${px2(i15.rsi)} · H1 ${px2(i1h.rsi)} · ATR M15 ${px2(i15.atr)} · H1 ${px2(i1h.atr)}`;
    const z = (p.zones || []).slice(0, 3);
    q('market-zones').innerHTML = z.length ? z.map((x) => `<div>${E(x.side)} ${px2(x.low)}–${px2(x.high)} <span class="small">(${x.touches} swings)</span></div>`).join('') : '<span class="small">no confirmed zone yet</span>';
  }
  function renderC2(p) {
    const v = p.scalp_c2, set = (id, t) => { const el = q(id); if (el) el.textContent = t; };
    if (!v) { for (const id of ['c2-tfs', 'c2-align', 'c2-missing', 'c2-plan', 'c2-forming']) set(id, ''); set('c2-state', 'scalping layer unavailable'); return; }
    const hh = v.h1_h4 || {}, m15 = v.m15 || {};
    set('c2-tfs', `M1 momentum ${v.m1_momentum || 'UNKNOWN'} (display only) · M5 structure ${v.m5_structure || 'UNKNOWN'} · M15 ATR ${px2(m15.atr)}`);
    set('c2-align', !v.side ? `H1 ${dirWord(hh.h1)} · H4 ${dirWord(hh.h4)} (no scalping side while M5 structure is not UP/DOWN)` : `H1/H4 vs ${v.side}: ${hh.alignment === 'ALIGNED' ? 'ALIGNED' : hh.alignment === 'COUNTERTREND' ? 'COUNTERTREND' : hh.alignment === 'NEUTRAL' ? 'NEUTRAL (H1 has no direction)' : 'UNKNOWN'} · H1 ${dirWord(hh.h1)} · H4 ${dirWord(hh.h4)}${hh.conflict ? ' · H4 CONFLICT' : ''}`);
    const word = v.signal ? `${v.signal} (research signal, closed M1 bar${v.signal === 'BLOCKED' ? '' : ', paper'})` : v.candidate;
    set('c2-state', `${word}${v.zone ? ` · zone ${px2(v.zone.low)}–${px2(v.zone.high)}` : ''}${v.expires_at ? ` · expires ${hhmm(v.expires_at)}` : ''}`);
    set('c2-missing', `Missing: ${v.missing || 'n/a'}`);
    const pl = v.plan;
    set('c2-plan', pl ? `paper plan (reference account): entry ${px2(pl.entry)} · SL ${px2(pl.stop_loss)} · TP ${px2(pl.take_profit)} · net R:R ${px2(pl.net_rr)}${v.signal === 'BLOCKED' ? ' · BLOCKED: ' + (v.block_reasons || []).join(', ') : ''}` : v.signal === 'BLOCKED' ? `BLOCKED: ${(v.block_reasons || []).join(', ')}` : '');
    set('c2-forming', v.display_only_forming ? `forming M1 candle (unconfirmed, display only): close ${px2(v.display_only_forming.close)}` : '');
  }
  function renderM1(p) {
    const v = p.m1_shadow;
    const set = (id, t) => { q(id).textContent = t; };
    if (!v) { for (const id of ['m1-context', 'm1-agree', 'm1-momentum', 'm1-stage', 'm1-next', 'm1-trigger', 'm1-plan', 'm1-forming']) set(id, ''); q('m1-events').innerHTML = ''; set('m1-stage', 'shadow layer unavailable'); return; }
    const c = v.context || {};
    set('m1-context', `context H1 ${dirWord(c.direction)}${c.conflict ? ' · H4 CONFLICT' : ''}${v.primary ? ' · watching ' + v.primary : ' · no entry side'}`);
    const st = v.primary ? (v.directions || {})[v.primary] : null;
    { const mk = (p.market || {}), side = v.primary, h1 = mk.direction, h4 = mk.conflict_direction, want = side === 'BUY' ? 'UP' : 'DOWN';
      const opp = want === 'UP' ? 'DOWN' : 'UP', verdict = h1 !== want ? 'CONFLICT (H1 does not support this side)' : h4 === opp ? 'CONFLICT (H4 opposes)' : h4 === want ? 'AGREES (H1 and H4)' : 'H1 agrees; H4 has no direction';
      set('m1-agree', !side ? 'M1 side: none (no entry side while H1 has no clear direction)' : `M1 shadow side ${side} vs H1 ${dirWord(h1)} · H4 ${dirWord(h4)}: ${verdict}`);
      const tr0 = st && st.trigger; set('m1-momentum', tr0 ? `Closed-bar flags: ${(tr0.flags || []).map((f) => f.replace('M1_', '').replaceAll('_', ' ').toLowerCase()).join(', ')}${(tr0.flags || []).includes('M1_MOMENTUM_SHIFT') ? ' (momentum shift on a CLOSED bar)' : ' (no momentum-shift flag)'}` : 'Closed-bar trigger: none yet'); }
    set('m1-stage', st ? `${v.primary}: ${st.stage.replaceAll('_', ' ')}` : 'NO CONTEXT: nothing to watch');
    set('m1-next', st ? `Next required: ${st.next_required}` : 'Next required: a clear H1 direction without an H4 conflict');
    const tr = st && st.trigger;
    set('m1-trigger', tr ? `TRIGGER BAR CLOSED (confirmed, research observation): ${tr.kind.replace('M1_', '')} at ${px2(tr.bar_close)} · known ${hhmm(tr.known_at)} · window ends ${hhmm(tr.window_ends_at)} · invalidation ${px2(tr.invalidation)}` : '');
    const pl = v.plan, ec = v.entry_check;
    set('m1-plan', pl ? `hypothetical (reference account, shadow): entry ${px2(pl.entry)} · SL ${px2(pl.stop_loss)} · TP ${px2(pl.take_profit)} · net R:R ${px2(pl.net_rr)} · ${ec && ec.research_entry_ready ? 'entry band OPEN' : 'outside the entry band'}`
      : ec ? `no plan: ${ec.plan_status}${/SL_TOO_CLOSE/.test(ec.plan_status || '') ? ' (the broker stops level makes this M1-scale stop unplaceable)' : ''}` : '');
    set('m1-forming', v.forming ? `FORMING (unconfirmed): ${v.forming.candidate.replaceAll('_', ' ')}: ${v.forming.note}` : '');
    const evs = (v.events_recent || []).filter((e) => e.kind !== 'WINDOW_STATE').slice(-5).reverse();
    q('m1-events').innerHTML = evs.length ? '<b>recent shadow events</b>' + evs.map((e) => `<div>${hhmm(e.known_at)} · ${E(e.direction)} · ${E(e.stage.replaceAll('_', ' '))}${e.kind && e.kind !== e.stage ? ' (' + E(e.kind) + ')' : ''}</div>`).join('') : '';
  }
  // ---------------------------------------------------------------- alerts (visual toast always; sound and desktop notification are opt-in) and the analysis clock
  const AKEY = 'xau.alerts.v1';
  let alertPrefs = { sound: false, notify: false };
  try { alertPrefs = { ...alertPrefs, ...JSON.parse(localStorage.getItem(AKEY) || '{}') }; } catch (e) { /* defaults */ }
  let seenV1 = null, audio = null, toastTimer = null, lastIntelWall = 0, lastEvalAt = null;
  const saveAlerts = () => { try { localStorage.setItem(AKEY, JSON.stringify(alertPrefs)); } catch (e) { /* ignore */ } };
  function beep() {
    try { audio = audio || new (window.AudioContext || window.webkitAudioContext)(); const o = audio.createOscillator(), g = audio.createGain(); o.frequency.value = 880; g.gain.value = 0.05; o.connect(g); g.connect(audio.destination); o.start(); o.stop(audio.currentTime + 0.15); } catch (e) { /* no audio */ }
  }
  function toast(kind, text) {
    const t = q('toast');
    if (!t) return;
    t.dataset.kind = kind;
    t.replaceChildren(document.createTextNode(text));
    const b = document.createElement('button'); b.textContent = 'Dismiss'; b.dataset.testid = 'toast-close'; b.onclick = () => { t.style.display = 'none'; };
    t.appendChild(b);
    t.style.display = 'block';
    clearTimeout(toastTimer); toastTimer = setTimeout(() => { t.style.display = 'none'; }, 20000);
  }
  function notifyDesktop(e) {
    const act = `V1 ${e.action} · RESEARCH`;
    try { if (alertPrefs.notify && window.Notification && Notification.permission === 'granted') new Notification(act, { body: `setup ${e.setup_id} · published ${clock(e.published_at)} (server time) · research only`, tag: e.decision_id, silent: true }); } catch (err) { /* ignore */ }
  }
  function announceEvent(e, more, many) {
    const act = e.action === 'BLOCKED' ? 'V1 BLOCKED (research)' : `V1 ${e.action} · RESEARCH`;
    const text = `${act} published ${clock(e.published_at)} server time · setup ${e.setup_id} · ${e.primary_reason}.${many ? ` (+${more} more new decision event${more > 1 ? 's' : ''}: see the chart and the history)` : ''} A research observation under the frozen rules: not an order, not advice.`;
    toast(e.action, text);
    if (e.action !== 'BLOCKED') {
      if (alertPrefs.sound) beep();
      notifyDesktop(e);
    }
  }
  function handleAlerts(p) {                                          // only events that are NEW since this page loaded: history is never announced
    const evs = p.v1_events || [];
    if (seenV1 === null) { seenV1 = new Set(evs.map((e) => e.decision_id)); return; }
    const fresh = evs.filter((e) => !seenV1.has(e.decision_id));
    for (const e of fresh) seenV1.add(e.decision_id);
    if (!fresh.length) return;
    const top = fresh.find((e) => e.action !== 'BLOCKED') || fresh[fresh.length - 1];       // several new events in one payload: one toast (the most important one) and a count, one sound, one notification per BUY/SELL
    announceEvent(top, fresh.length - 1, fresh.length > 1);
    for (const e of fresh) if (e !== top && e.action !== 'BLOCKED') notifyDesktop(e);
  }
  function setAlertButtons() {
    const s = q('al-sound'), n = q('al-notify');
    if (s) s.setAttribute('aria-pressed', alertPrefs.sound ? 'true' : 'false');
    if (n) { const ok = !!(window.Notification && Notification.permission === 'granted'); n.setAttribute('aria-pressed', alertPrefs.notify && ok ? 'true' : 'false'); n.title = window.Notification && Notification.permission === 'denied' ? 'Desktop notifications are blocked in this browser' : n.title; }
  }
  const sbtn = q('al-sound'), nbtn = q('al-notify'), tbtn = q('sb-toggle');
  if (sbtn) sbtn.onclick = () => { alertPrefs.sound = !alertPrefs.sound; saveAlerts(); setAlertButtons(); if (alertPrefs.sound) beep(); };
  if (nbtn) nbtn.onclick = async () => {
    alertPrefs.notify = !alertPrefs.notify;
    if (alertPrefs.notify && window.Notification && Notification.permission === 'default') { try { await Notification.requestPermission(); } catch (e) { /* ignore */ } }
    if (alertPrefs.notify && !(window.Notification && Notification.permission === 'granted')) alertPrefs.notify = false;       // never stored as ON while the browser has not granted it (no silent switch-on later)
    saveAlerts(); setAlertButtons();
  };
  const SBKEY = 'xau.sidebar';
  function applySidebar(show) { document.body.classList.toggle('nosidebar', !show); if (tbtn) tbtn.setAttribute('aria-pressed', show ? 'true' : 'false'); try { localStorage.setItem(SBKEY, show ? '1' : '0'); } catch (e) { /* ignore */ } setTimeout(() => { window.dispatchEvent(new Event('resize')); }, 50); }
  if (tbtn) { let show = true; try { show = localStorage.getItem(SBKEY) !== '0'; } catch (e) { /* default */ } applySidebar(show); tbtn.onclick = () => applySidebar(document.body.classList.contains('nosidebar')); }
  { const more = q('more'); if (more) { try { more.open = localStorage.getItem('xau.more') === '1'; } catch (e) { /* closed */ } more.addEventListener('toggle', () => { try { localStorage.setItem('xau.more', more.open ? '1' : '0'); } catch (e) { /* ignore */ } }); } }
  setAlertButtons();
  setInterval(() => {
    const el = q('hdr2');
    if (!el) return;
    el.textContent = lastEvalAt == null ? '' : `analysis ${clock(lastEvalAt)} server time · received ${Math.max(0, Math.round((Date.now() - lastIntelWall) / 1000))} s ago`;
  }, 1000);
  function renderChips(p) {
    const d = p.decision || {};
    const cur = (p.v1_events || []).find((e) => e.decision_id === p.v1_current_id);
    const el = q('d-chips');
    if (!el) return;
    const chips = [[`Strategy eligible: ${d.strategy_eligible ? 'YES' : 'NO'}`, d.strategy_eligible ? 'eligible-yes' : 'eligible-no']];
    if (cur) chips.push([`Signal CURRENT · age ${Math.max(0, (p.evaluated_at || cur.published_at) - cur.published_at)} s · published ${clock(cur.published_at)} · setup expires ~${hhmm(cur.valid && cur.valid.expires_at)}`, 'signal-current']);
    else if (d.action === 'BUY' || d.action === 'SELL') chips.push(['Signal CURRENT · publication time not in the event list yet', 'signal-current']);
    else chips.push([d.action === 'BLOCKED' ? 'No actionable signal: blocked by a risk/safety gate' : 'No current signal', 'signal-none']);
    el.replaceChildren(...chips.map(([t, k]) => { const s = document.createElement('span'); s.textContent = t; s.dataset.k = k; return s; }));
  }
  // ---------------------------------------------------------------- decision hero: market bias and setup progress (a display of backend fields only)
  const STEPS = ['Context', 'Impulse', 'Pullback', 'Zone', 'Confirmation', 'Entry', 'Risk'];
  function bias(p) {
    const m = p.market || {};
    const d = m.direction, c4 = m.conflict_direction;
    let word = 'UNKNOWN', why = 'not enough backend analysis';
    if (m.history === 'INSUFFICIENT_HISTORY') { word = 'UNKNOWN'; why = 'not enough stored bars'; }
    else if (m.conflict) { word = 'NEUTRAL'; why = `H1 ${dirWord(d)} conflicts with H4 ${dirWord(c4)}`; }
    else if (d === 'UP') { word = 'BULLISH'; why = `H1 UP${c4 === 'UP' ? ' · H4 UP' : ' · H4 not opposed'}`; }
    else if (d === 'DOWN') { word = 'BEARISH'; why = `H1 DOWN${c4 === 'DOWN' ? ' · H4 DOWN' : ' · H4 not opposed'}`; }
    else if (d === 'NONE') { word = 'NEUTRAL'; why = 'H1 shows no direction'; }
    return { word, why };
  }
  function progress(p) {
    const d = p.decision || {}, m = p.market || {}, s = d.setup;
    const st = STEPS.map(() => 'NOT EVALUATED'), nt = STEPS.map(() => '');
    const sigConflict = d.primary_reason === 'SIGNAL_CONFLICT';
    const ctxOk = (m.direction === 'UP' || m.direction === 'DOWN') && !m.conflict && !sigConflict;
    if (!ctxOk) { st[0] = (m.conflict || sigConflict) ? 'FAILED' : 'WAITING'; nt[0] = sigConflict ? 'conflicting setups or timeframes' : m.conflict ? 'H1/H4 conflict' : 'no H1 direction'; return STEPS.map((n, i) => ({ n, s: st[i], note: nt[i] })); }
    st[0] = 'DONE';
    if (!s) { st[1] = 'WAITING'; nt[1] = 'no qualifying impulse yet'; return STEPS.map((n, i) => ({ n, s: st[i], note: nt[i] })); }
    st[1] = 'DONE';
    const sn = s.state;
    if (sn === 'SETUP_FORMING') { st[2] = 'ACTIVE'; nt[2] = 'waiting for the pullback'; }
    else if (sn === 'PULLBACK_IN_PROGRESS') { st[2] = 'ACTIVE'; nt[2] = 'in progress'; st[3] = 'WAITING'; nt[3] = d.primary_reason === 'NO_RELEVANT_ZONE' ? 'no confirmed zone nearby' : 'not at a zone yet'; }
    else if (sn === 'AT_RELEVANT_ZONE' || sn === 'AWAITING_CONFIRMATION') { st[2] = 'DONE'; st[3] = 'DONE'; st[4] = 'ACTIVE'; nt[4] = 'waiting for a closed confirming bar'; }
    else if (sn === 'CONFIRMED' || sn === 'ENTRY_WINDOW') { st[2] = st[3] = st[4] = 'DONE'; st[5] = 'ACTIVE'; nt[5] = 'entry window not open / not eligible yet'; }
    else if (sn === 'ENTRY_ELIGIBLE') {
      st[2] = st[3] = st[4] = st[5] = 'DONE';
      if (d.action === 'BUY' || d.action === 'SELL') { st[6] = 'DONE'; nt[6] = 'risk and gates pass'; }
      else if (d.action === 'BLOCKED') { st[6] = 'FAILED'; nt[6] = String(d.primary_reason || '').replace('RISK:', '').split('(')[0].trim(); }
      else { st[6] = 'WAITING'; nt[6] = String(d.primary_reason || '').replaceAll('_', ' ').toLowerCase(); }
    }
    return STEPS.map((n, i) => ({ n, s: st[i], note: nt[i] }));
  }
  function renderHero(p) {
    const b = bias(p);
    const el = q('bias');
    if (el) { el.textContent = `Market bias: ${b.word} · ${b.why} (higher-timeframe direction, not a prediction)`; el.dataset.bias = b.word; }
    const ol = q('progress');
    if (ol) {
      ol.replaceChildren(...progress(p).map((x) => {
        const li = document.createElement('li');
        li.dataset.status = x.s;
        li.textContent = `${x.n}: ${x.s}${x.note ? ' (' + x.note + ')' : ''}`;
        return li;
      }));
    }
  }
  function clearHero() { const el = q('bias'); if (el) { el.textContent = ''; el.dataset.bias = ''; } const ol = q('progress'); if (ol) ol.replaceChildren(); const tip = q('mk-tip'); if (tip) tip.style.display = 'none'; }
  chart.subscribeCrosshairMove((param) => {
    const tip = q('mk-tip');
    if (!tip) return;
    const lines = param && param.time != null ? markerInfo.get(param.time) : null;
    if (!lines || !lines.length || !param.point) { tip.style.display = 'none'; return; }
    tip.replaceChildren(...lines.flat().map((t, i) => { const d = document.createElement('div'); d.textContent = t; if (i === 0) d.style.fontWeight = '700'; return d; }));
    tip.style.display = 'block';
    const box = q('chart').getBoundingClientRect();
    tip.style.left = Math.min(Math.max(param.point.x + 12, 4), Math.max(box.width - 330, 4)) + 'px';
    tip.style.top = Math.max(param.point.y - 10, 4) + 'px';
  });
  function inspect(t) {
    highlight = t;
    const sec = SEC[tf], from = t - sec * 40, to = t + sec * 40;
    try { chart.timeScale().setVisibleRange({ from, to }); } catch (e) { /* range outside data: keep the view */ }
    drawMarkers();
  }
  let researchAt = 0;
  async function loadResearch() {
    if (Date.now() - researchAt < 300000) return;
    researchAt = Date.now();
    try {
      const r = await (await fetch('/api/research')).json();
      q('research-status').innerHTML = [
        `V1 backtest: <b>${E(r.v1_backtest.verdict)}</b> (${r.v1_backtest.validation_trades} validation trades, holdout ${E(r.v1_backtest.holdout)})`,
        `ML shadow: <b>${E(r.ml_shadow.verdict)}</b> (AUC ${r.ml_shadow.validation_auc == null ? '–' : r.ml_shadow.validation_auc.toFixed(3)}, feeds no decision)`,
        `M1 entry V2: <b>${E(r.m1_entry_v2.status)}</b>, performance claim ${E(r.m1_entry_v2.performance_claim)}; evaluation needs ${E(r.m1_entry_v2.evaluation_rule)}`,
        `MT5 live checks: ${E(r.mt5_live.mode_ab)}, ${E(r.mt5_live.indicator_parity)}`, `<b>${E(r.release)}</b>`].map((x) => `<div>${x}</div>`).join('');
    } catch (e) { researchAt = 0; }
  }

  // ------------------------------------------------------------------ wiring
  function setLayerButtons() {
    document.querySelectorAll('[data-layer]').forEach((b) => b.setAttribute('aria-pressed', layers[b.dataset.layer] ? 'true' : 'false'));
  }
  document.querySelectorAll('[data-layer]').forEach((b) => {
    b.onclick = () => { layers[b.dataset.layer] = !layers[b.dataset.layer]; save(); setLayerButtons(); apply(true); };
  });
  function apply(forceEma) { loadEma(forceEma); drawZones(); drawMarkers(); }
  window.__layers = {
    onIntel(p) { intel = p; lastIntelWall = Date.now() - Math.max(0, Number(p.intel_age_s) || 0) * 1000; lastEvalAt = p.evaluated_at; handleAlerts(p); renderChips(p); renderMarket(p); renderM1(p); renderC2(p); renderHero(p); apply(false); loadResearch(); renderInspector(); ensureLoaded(); },
    inspect,
    onStale() {
      intel = null; lastEvalAt = null; clearAllLayers(); clearHero(); renderInspector(); { const tt = q('toast'); if (tt) tt.style.display = 'none'; clearTimeout(toastTimer); } { const c = q('d-chips'); if (c) c.replaceChildren(); }
      for (const id of ['market-direction', 'market-regime', 'market-structure', 'market-indicators', 'market-zones', 'm1-context', 'm1-agree', 'm1-momentum', 'm1-next', 'm1-trigger', 'm1-plan', 'm1-forming', 'm1-events']) q(id).textContent = '';
      q('m1-stage').textContent = 'stale: no shadow observation is shown';
      for (const id of ['c2-tfs', 'c2-align', 'c2-missing', 'c2-plan', 'c2-forming']) q(id).textContent = '';
      q('c2-state').textContent = 'stale: no scalping observation is shown';
      q('market-direction').textContent = 'stale: market intelligence is not shown';
    },
    onTf() { emaTf = null; apply(true); renderInspector(); ensureLoaded(); },
    state: () => ({ layers: { ...layers }, ema: Object.fromEntries(Object.entries(emaSeries).map(([k, s]) => [k, s.data().length])), zoneLines: zoneLines.length, markers: markers().length, markerTexts: markers().map((m) => m.text), highlight, error: window.__layer_error || null }),
    markers: () => markers(),
    events: () => ({ stats: visibleSetupEvents(), hist: hist.size, ranges: ranges.length, meta: histMeta }),
  };
  const midBox = q('ev-mid');
  if (midBox) { midBox.checked = !!layers.mid; midBox.onchange = () => { layers.mid = midBox.checked; save(); apply(false); renderInspector(); }; }
  setLayerButtons();
  loadResearch();
})();
