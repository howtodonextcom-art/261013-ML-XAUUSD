// SYNTHETIC FIXTURES for interactive MCP browser QA (Chrome DevTools MCP navigate_page `initScript`). NOT live data, NOT a trading signal.
// Usage: navigate to http://127.0.0.1:8765/?fx=S4 with this file as the initScript. The page's REAL websocket handler and renderer run; only the
// gateway's own `intel` frames and the initial /api/intel fetch are replaced by the scenario below (health/tick/candle frames stay live).
(() => {
  const fx = new URLSearchParams(location.search).get('fx');
  if (!fx) return;
  const SETUP = { setup_id: 'M15-BUY-1791920000-4100.00', direction: 'BUY', state: 'ENTRY_ELIGIBLE', evidence: ['CONTEXT:higher-timeframe BUY direction', 'ZONE:2 confirmed swings, [4101.10, 4102.40]', 'CONFIRMATION:bullish pattern bar closed at 4103.20'],
    invalidation_level: 4099.8, entry_level: 4103.2, expires_at: 1791928800, entry_window_ends_at: 1791926400, zone: { low: 4101.1, high: 4102.4 },
    next_required_event: 'entry decision (risk gate) while price stays inside the band and above the invalidation level' };
  const PLAN = { direction: 'BUY', entry: 4103.2, stop_loss: 4099.8, take_profit: 4118.4, tp2_reference: 4110.0, lot: 0.17, net_rr: 3.4, gross_rr: 4.1, risk_fraction: 0.005 };
  const ov = (dir, e, sl, tp) => ({ zone: { low: 4101.1, high: 4102.4 }, lines: [{ kind: 'ENTRY', price: e }, { kind: 'SL', price: sl }, { kind: 'TP', price: tp }], direction: dir });
  const base = (o) => ({ type: 'intel', seq: 1000, evaluated_at: 1791925680, mode: 'READ_ONLY+SHADOW+PAPER_SIMULATION', bars: { M15: 2000, H1: 2000, H4: 2000 }, status: {}, analysis: {}, setup_events: o.events || [],
    market: { direction_tf: 'H1', direction: o.dir || 'UP', conflict_tf: 'H4', conflict_direction: 'NONE', conflict: false, regime: { M15: 'TRANSITION', H1: 'TRENDING_UP', H4: 'TRANSITION' }, history: 'OK' },
    overlays: o.overlays || { zone: null, lines: [], direction: null },
    decision: { kind: 'RESEARCH_DECISION', execution_authorized: false, strategy_version: 'cand-1[setup-1+risk-1+gate-1]', dataset_version: 'SYNTHETIC-FIXTURE', action: o.action, primary_reason: o.primary,
      layer: o.layer || 'strategy', strategy_eligible: !!o.eligible, reasons: o.reasons || { market: [], strategy: [o.primary], gate: [] }, setup: o.setup || null, plan: o.plan || null, risk: null, next_required: o.next || null } });
  // scenarios (the index of the prompt's mandatory list): S1 no direction, S2 awaiting pullback, S3 awaiting confirmation, S4 BUY, S5 SELL, S6 eligible but BLOCKED, S7 INVALIDATED/MISSED, S8 stale
  const S = {
    S1: base({ action: 'WAIT', primary: 'NO_DIRECTION', layer: 'market', dir: 'NONE', reasons: { market: ['NO_DIRECTION'], strategy: [], gate: [] }, next: 'the higher timeframe (H1) structure and trend must agree on a direction' }),
    S2: base({ action: 'WAIT', primary: 'AWAITING_PULLBACK', setup: { ...SETUP, state: 'SETUP_FORMING', entry_level: null, invalidation_level: null, entry_window_ends_at: null, evidence: ['CONTEXT:higher-timeframe BUY direction', 'IMPULSE:2.1 ATR leg'], next_required_event: 'price retraces at least pullback_min ATR below the impulse high' }, next: 'price retraces at least pullback_min ATR below the impulse high' }),
    S3: base({ action: 'WAIT', primary: 'AWAITING_CONFIRMATION', setup: { ...SETUP, state: 'AWAITING_CONFIRMATION', entry_level: null, invalidation_level: null, entry_window_ends_at: null, next_required_event: 'a bullish confirmation bar (pin bar / engulfing / strong close) closes at the zone' }, overlays: { zone: { low: 4101.1, high: 4102.4 }, lines: [], direction: 'BUY' }, next: 'a bullish confirmation bar (pin bar / engulfing / strong close) closes at the zone' }),
    S4: base({ action: 'BUY', primary: 'ENTRY_ELIGIBLE', eligible: true, setup: SETUP, plan: PLAN, overlays: ov('BUY', 4103.2, 4099.8, 4118.4), next: SETUP.next_required_event }),
    S5: base({ action: 'SELL', primary: 'ENTRY_ELIGIBLE', eligible: true, dir: 'DOWN', setup: { ...SETUP, direction: 'SELL', setup_id: 'M15-SELL-1791920000-4200.00', entry_level: 4100.0, invalidation_level: 4106.0 }, plan: { ...PLAN, direction: 'SELL', entry: 4100.0, stop_loss: 4106.0, take_profit: 4082.0 }, overlays: ov('SELL', 4100.0, 4106.0, 4082.0), next: SETUP.next_required_event }),
    S6: base({ action: 'BLOCKED', primary: 'RISK:RR_TOO_LOW', layer: 'gate', eligible: true, setup: SETUP, plan: { direction: 'BUY', entry: 4103.2, stop_loss: 4099.8, take_profit: 4112.0, tp2_reference: 4110.0, net_rr: 1.2, gross_rr: 1.6, risk_fraction: 0.005 }, overlays: ov('BUY', 4103.2, 4099.8, 4112.0), reasons: { market: [], strategy: ['ENTRY_ELIGIBLE'], gate: ['RISK:RR_TOO_LOW'] } }),
    S7: base({ events: [{ setup_id: 'M15-SELL-1791890000-4150.00', direction: 'SELL', state: 'MISSED', prev_state: 'ENTRY_WINDOW', known_at: 1791915000, reasons: ['PRICE_RAN_AWAY'] }, { setup_id: 'M15-BUY-1791900000-4090.00', direction: 'BUY', state: 'INVALIDATED', prev_state: 'AWAITING_CONFIRMATION', known_at: 1791924900, reasons: ['ZONE_FAILED'] }], action: 'WAIT', primary: 'AWAITING_PULLBACK', next: 'an impulse leg in the H1 direction, then a pullback of at least 0.5 ATR from its extreme', reasons: { market: [], strategy: ['AWAITING_PULLBACK'], gate: [] } }),
    S8: base({ action: 'WAIT', primary: 'DATA_STALE', layer: 'gate', reasons: { market: [], strategy: [], gate: ['DATA_STALE', 'INTEL_ENGINE_STALLED'] } }),
  };
  window.__SCEN = S;
  window.__FIX_NAME = fx;
  window.__FIX = S[fx];
  const nf = window.fetch.bind(window);
  window.fetch = (u, ...a) => (String(u).includes('/api/intel') ? Promise.resolve(new Response(JSON.stringify(window.__FIX), { headers: { 'content-type': 'application/json' } })) : nf(u, ...a));
  const NativeWS = window.WebSocket;
  window.WebSocket = function (url, p) {
    const ws = new NativeWS(url, p);
    let h = null;
    Object.defineProperty(ws, 'onmessage', { configurable: true, get: () => h, set: (fn) => { h = fn; ws.addEventListener('message', (e) => { try { if (JSON.parse(e.data).type === 'intel') return; } catch (_) { /* forward */ } fn(e); }); } });
    setInterval(() => { if (h && ws.readyState === 1 && window.__FIX) h({ data: JSON.stringify({ ...window.__FIX, seq: (window.__FIX.seq || 0) + 1 }) }); }, 400);
    return ws;
  };
  window.WebSocket.prototype = NativeWS.prototype;
})();
