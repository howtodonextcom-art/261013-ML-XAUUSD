// Intelligence panels and chart layers. EVERYTHING here is a display of backend data (/api/intel payload, /api/indicators, /api/research): nothing is computed
// from prices in the browser, nothing repaints (events carry the backend's `known_at`), and a stale or disconnected state clears every layer and panel.
(() => {
  const KEY = 'xau.layers.v1';
  const DEF = { ema20: false, ema50: false, ema200: false, zones: true, structure: false, setups: true, m1: true };
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
    return ans < 0 ? null : d[ans].time;
  }
  function markers() {
    const out = [];
    if (!intel) return out;
    if (layers.structure) {
      for (const tfk of ['M15', 'H1']) {
        const evs = ((intel.analysis || {})[tfk] || {}).events_recent || [];
        for (const e of evs) { const t = snapTime(e.bar_open_time ?? e.known_at); if (t != null) out.push({ time: t, position: 'aboveBar', color: '#9aa7bb', shape: 'circle', size: 1, text: String(e.event).includes('UP') ? '▲' : '▼', info: `${tfk} ${String(e.event).replace('_', ' ')}` }); }
      }
    }
    if (layers.setups) {
      for (const e of intel.setup_events || []) {
        const t = snapTime(e.known_at - 1);
        if (t == null) continue;
        const terminal = ['INVALIDATED', 'MISSED', 'EXPIRED'].includes(e.state);
        out.push({ time: t, position: e.direction === 'BUY' ? 'belowBar' : 'aboveBar', color: terminal ? '#f0b90b' : e.state === 'CONFIRMED' || e.state === 'ENTRY_ELIGIBLE' ? '#2ebd85' : '#7d8aa0',
                   shape: terminal ? 'square' : 'circle', size: 1, text: terminal ? ({ INVALIDATED: 'I', MISSED: 'M', EXPIRED: 'X' }[e.state]) : (e.state === 'CONFIRMED' ? 'C' : ''), info: `${e.direction[0]} ${e.state.replace('_', ' ')}` });
      }
    }
    if (layers.m1 && intel.m1_shadow) {
      for (const e of intel.m1_shadow.events_recent || []) {
        if (e.kind === 'WINDOW_STATE' || !['M1_TRIGGERED', 'M5_CONFIRMED_AWAITING_M1'].includes(e.stage)) continue;
        const t = snapTime(e.bar_time);
        if (t != null) out.push({ time: t, position: e.direction === 'BUY' ? 'belowBar' : 'aboveBar', color: '#38bdf8', shape: e.direction === 'BUY' ? 'arrowUp' : 'arrowDown', size: 1, text: '', info: `shadow ${e.kind === 'M5_CONFIRMED' ? 'M5 conf.' : e.kind.replace('M1_', '')}` });
      }
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
  function renderM1(p) {
    const v = p.m1_shadow;
    const set = (id, t) => { q(id).textContent = t; };
    if (!v) { for (const id of ['m1-context', 'm1-stage', 'm1-next', 'm1-trigger', 'm1-plan', 'm1-forming']) set(id, ''); q('m1-events').innerHTML = ''; set('m1-stage', 'shadow layer unavailable'); return; }
    const c = v.context || {};
    set('m1-context', `context H1 ${dirWord(c.direction)}${c.conflict ? ' · H4 CONFLICT' : ''}${v.primary ? ' · watching ' + v.primary : ' · no entry side'}`);
    const st = v.primary ? (v.directions || {})[v.primary] : null;
    set('m1-stage', st ? `${v.primary}: ${st.stage.replaceAll('_', ' ')}` : 'NO CONTEXT: nothing to watch');
    set('m1-next', st ? `Next required: ${st.next_required}` : 'Next required: a clear H1 direction without an H4 conflict');
    const tr = st && st.trigger;
    set('m1-trigger', tr ? `CONFIRMED (closed bar, research observation): ${tr.kind.replace('M1_', '')} at ${px2(tr.bar_close)} · known ${hhmm(tr.known_at)} · window ends ${hhmm(tr.window_ends_at)} · invalidation ${px2(tr.invalidation)}` : '');
    const pl = v.plan, ec = v.entry_check;
    set('m1-plan', pl ? `hypothetical (reference account, shadow): entry ${px2(pl.entry)} · SL ${px2(pl.stop_loss)} · TP ${px2(pl.take_profit)} · net R:R ${px2(pl.net_rr)} · ${ec && ec.research_entry_ready ? 'entry band OPEN' : 'outside the entry band'}`
      : ec ? `no plan: ${ec.plan_status}${/SL_TOO_CLOSE/.test(ec.plan_status || '') ? ' (the broker stops level makes this M1-scale stop unplaceable)' : ''}` : '');
    set('m1-forming', v.forming ? `FORMING (unconfirmed): ${v.forming.candidate.replaceAll('_', ' ')}: ${v.forming.note}` : '');
    const evs = (v.events_recent || []).filter((e) => e.kind !== 'WINDOW_STATE').slice(-5).reverse();
    q('m1-events').innerHTML = evs.length ? '<b>recent shadow events</b>' + evs.map((e) => `<div>${hhmm(e.known_at)} · ${E(e.direction)} · ${E(e.stage.replaceAll('_', ' '))}${e.kind && e.kind !== e.stage ? ' (' + E(e.kind) + ')' : ''}</div>`).join('') : '';
  }
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
    onIntel(p) { intel = p; renderMarket(p); renderM1(p); apply(false); loadResearch(); },
    inspect,
    onStale() {
      intel = null; clearAllLayers();
      for (const id of ['market-direction', 'market-regime', 'market-structure', 'market-indicators', 'market-zones', 'm1-context', 'm1-next', 'm1-trigger', 'm1-plan', 'm1-forming', 'm1-events']) q(id).textContent = '';
      q('m1-stage').textContent = 'stale: no shadow observation is shown';
      q('market-direction').textContent = 'stale: market intelligence is not shown';
    },
    onTf() { emaTf = null; apply(true); },
    state: () => ({ layers: { ...layers }, ema: Object.fromEntries(Object.entries(emaSeries).map(([k, s]) => [k, s.data().length])), zoneLines: zoneLines.length, markers: markers().length, highlight, error: window.__layer_error || null }),
    markers: () => markers(),
  };
  setLayerButtons();
  loadResearch();
})();
