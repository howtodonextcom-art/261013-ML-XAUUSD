# Setup event (F / C / X / I / M) forensics, Level 6.3

Written 2026-10-15. Reproduce: `.\.venv\Scripts\python.exe benchmarks\setup_event_trace.py` -> `results/v1/setup_event_trace.json` (stored bars, setup-1 policy, no threshold changed, no outcome computed, no performance claim; the markers are display only). Strategy `cand-1[setup-1+risk-1+gate-1]`.

## 1. Why the markers were few and vanished when panning
| Stage | Count | What happens |
|---|---|---|
| 1 backend events (state machine over the 2000 newest M15 bars the gateway holds, about 21 days) | 162 | all computed |
| 2 kept by the realtime payload (`recent_events = 12`) | 12 | 150 events (92.6%) were dropped before the browser ever saw them |
| 3 frontend candle window | newest 2000 candles of the chart timeframe | the 12 newest events cluster in the last hours; pan back and the chart shows candles without any marker |
| 4 mapped to a candle | `snapTime`: the candle that contains `known_at - 1` | correct, but returned the NEAREST EARLIER candle when the moment lay in a missing bar or after the last one (fixed in Level 6.2) |
| 5 drawn | one marker per event | intermediate states (pullback, zone, waiting, window, eligible) were drawn as unlabeled grey dots, only F/C/X/I/M carried a letter: uneven look |
Answers: **(1) cause:** the 12-event cap of the realtime payload (an API limit), plus unlabelled intermediate dots. **(2) algorithm error:** none in the emission of F/C/X/I/M: every event existed in `res.events` with a stable id and `known_at`. One consistency issue was found (section 3). **(3) API limit:** yes, the cap. **(4) mapping/render:** the mapping was correct for events inside the window; missing-bar and out-of-window events had no explanation and several events on one candle were separate overlapping markers.

## 2. Before and after (stored bars, newest 2000 candles per timeframe, canonical replay timeline of 2202 events)
| Chart | Drawn before (12 realtime events) | Drawn after (all loaded) | Marker groups after | Events sharing a candle and side | Max on one candle/side | Outside the candle window (counted with reason) |
|---|---|---|---|---|---|---|
| M1 | 12 | 19 | 12 | 11 | 3 | 2183 (older than the first M1 candle) |
| M5 | 12 | 42 | 27 | 23 | 3 | 2160 |
| M15 | 12 | 175 | 115 | 91 | 3 | 2027 |
| H1 | 12 | 793 | 290 | 678 | 9 | 1409 |
| H4 | 12 | 2202 | 489 | 2125 | 14 | 0 |
Live check in Chrome MCP on the final code (gateway, History on): M15 (150 newest candles) `Backend events 2202 · Loaded 311 · Visible 174 · Hidden 0 · Outside range 137 · Unmapped 0` (114 markers); H1 790 visible / 694 outside range; H4 2202 visible (489 markers). Before the change the same M15 view drew 12 events (8 markers; History off reproduces that exactly). Screenshots (not committed): `qa-artifacts/L63_before_M15_150.png`, `L63_after_M15_150.png`, `L63_before_M15_380.png`, `L63_after_M15_380.png`.

## 3. Consistency finding: the live engine and a replay disagree, even deep inside the live window
The live engine analyses only the newest 2000 bars; a replay over all stored bars starts the state machine earlier. On the newest window 134 of the 162 live events (83%) also appear in the replay and 33 replay events are absent from the live list; measured over ten window positions, 65 to 98% of the live engine's events also appear in the replay (about 75% in the first days of a window, 92 to 98% deeper in); the rest are setups that only one of the two computations builds, because zig-zag swings (and therefore setups) depend on where the state machine started (a replay over exactly the same 2000-bar window gives zero differences; shallower H1/H4 context adds further differences). Consequences and rule (code: `setup_history.compose`): the REPLAY (fixed start at the first stored bar, fed with every closed bar up to the newest one) is the canonical history: deterministic, causal, and an event of the past never changes when time passes. LIVE_ENGINE events are added only beyond what the replay reaches and never overwrite a replay event; the newest 12 live events still travel in the realtime payload (what the decision engine saw). Every event carries its provenance. Mixing both inside the live window would double count setups and make the past change as the window slides. This is the window-start dependence the P6 backtest already disclosed, not a defect of the rules.

## 4. Design
- Realtime payload stays light: newest 12 events plus `setup_events_total` and `setup_events_cap`.
- `GET /api/setup_events?from=&to=&limit=&cursor=` (server-time epoch seconds on `known_at`; `limit` is capped at 2000 and the page extends to the end of its last second, so a page can exceed the limit by a few events and a cursor never splits events sharing one second; events keep the state machine's emission order via `seq`; replay computed in a worker process and cached per store signature plus the newest bar per timeframe; a failed replay is remembered for 60 s). Event: `event_id = setup_id|state|known_at`, setup_id, direction, state, prev_state, reasons, known_at, event_time, policy_version, provenance.
- Frontend: one fetch for the viewed candle window (pan/zoom inside it never refetches; a response without a working replay is not marked as covered and is retried after 30 s; the server's timeline for a fetched period replaces the client's copy); events grouped per candle and side (several events = one marker, tooltip lists all); letters `B·F`, `S·X`... only when at most 300 candles are visible; layers Setups / History / V1 signals / M1 shadow; Event Inspector with the counters `Backend / Loaded / Visible / Hidden / Outside range / Unmapped`, reasons on hover, click-to-locate; intermediate states behind a filter (counted as hidden with the reason).
- Semantics: a setup event is placed on the candle that CLOSES when it became known (bar-close convention: `known_at - 1`); it never sits on an earlier candle. V1 BUY/SELL/BLOCKED markers (arrows and squares, publication time) stay a separate kind.
- Not done: older history than the 2000 loaded candles of a timeframe is reported as "outside range", not fetched; stored M15 history before 2025-10-14 does not exist.

## 5. Observation (not changed)
On 2026-10-14 the sharp fall of about 70 USD around 15:00-16:00 server time produced one SELL setup (M15-SELL-1791990900: pullback, zone touched, awaiting confirmation at 15:30) that EXPIRED at 15:45 as `SUPERSEDED_BY_CONTINUATION` (price kept falling without the closed confirming bar the rules require), and no entry window ever opened. That is the frozen policy working as specified; whether it should react to such moves is a research question, a momentum/breakout study would be a separate pre-registered proposal (docs/research/V1_SIGNAL_FORENSICS.md section 5).
