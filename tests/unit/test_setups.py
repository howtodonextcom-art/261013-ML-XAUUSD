import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "intelligence"))
sys.path.insert(0, str(Path(__file__).parent))
from xau_intel.indicators import atr  # noqa: E402
from xau_intel.setups.machine import POLICY, SetupPolicy, current_status, run_setups  # noqa: E402
from xau_intel.setups.patterns import candle_patterns  # noqa: E402
from xau_intel.setups.trend_series import align_to, direction_series, structure_trend_series  # noqa: E402
from xau_intel.setups.zones import build_zones  # noqa: E402
from xau_intel.structure import Swing, zigzag_swings  # noqa: E402
from test_intel import walk  # noqa: E402

T0 = 1_700_006_400
SEC = 900


# ====================================================================== candle patterns (policy pa-1)
def one(o, h, l, c, atr_v=1.0):
    r = candle_patterns([o], [h], [l], [c], [atr_v])
    return {k: bool(v[0]) for k, v in r.items()}


def test_bullish_pin_bar_geometry():
    assert one(103.4, 103.7, 102.7, 103.6)["pin_bull"]                    # lower wick 70%, body 20%, close at 90% of range
    assert not one(103.4, 103.7, 102.7, 103.0)["pin_bull"]                # close in the lower part
    assert not one(103.0, 103.7, 102.7, 103.6)["pin_bull"]                # body 60% of range: too big for a pin
    assert not one(103.4, 103.45, 103.15, 103.35, atr_v=1.0)["pin_bull"]  # range 0.3 < 0.5 ATR: ignored as noise


def test_engulfing_requires_prior_opposite_bar_and_body_cover():
    r = candle_patterns([104.0, 102.9], [104.1, 104.6], [102.8, 102.8], [103.0, 104.5], [1.0, 1.0])
    assert bool(r["engulf_bull"][1]) and not bool(r["engulf_bear"][1])
    r = candle_patterns([104.0, 103.2], [104.1, 104.6], [102.8, 103.1], [103.0, 104.5], [1.0, 1.0])   # body does not cover prev open
    assert not bool(r["engulf_bull"][1])
    r = candle_patterns([103.0, 102.9], [104.1, 104.6], [102.8, 102.8], [104.0, 104.5], [1.0, 1.0])   # previous bar is bullish
    assert not bool(r["engulf_bull"][1])


def test_strong_close():
    assert one(102.0, 103.0, 101.9, 102.95, atr_v=1.0)["strong_bull"]
    assert not one(102.0, 103.0, 101.9, 102.5, atr_v=1.0)["strong_bull"]       # close not near the high
    assert not one(102.0, 102.4, 101.95, 102.38, atr_v=1.0)["strong_bull"]     # range < 0.8 ATR


def test_bearish_patterns_are_the_exact_mirror_and_nan_atr_never_matches():
    rng = np.random.default_rng(3)
    o = 100 + rng.normal(0, 1, 400); c = o + rng.normal(0, 1, 400)
    h = np.maximum(o, c) + rng.uniform(0, 1.2, 400); l = np.minimum(o, c) - rng.uniform(0, 1.2, 400)
    a = np.full(400, 1.0)
    p = candle_patterns(o, h, l, c, a); m = candle_patterns(-o, -l, -h, -c, a)
    for k in ("pin", "engulf", "strong"):
        assert (p[f"{k}_bull"] == m[f"{k}_bear"]).all() and (p[f"{k}_bear"] == m[f"{k}_bull"]).all()
    assert any(p["any_bull"]) and any(p["any_bear"])                       # the property is not vacuous
    nan = candle_patterns(o, h, l, c, np.full(400, np.nan))
    assert not any(nan["any_bull"]) and not any(nan["any_bear"])


# ====================================================================== zones
def sw(kind, idx, price, known=None):
    return Swing(kind, idx, idx + 2 if known is None else known, price, T0 + idx * SEC, T0 + (idx + 3) * SEC, "M15")


def test_zone_clusters_confirmed_swings_pads_them_and_keeps_known_at():
    zs = build_zones([sw("H", 3, 103.1), sw("L", 8, 102.9), sw("H", 15, 110.0)], atr_value=1.0, min_touches=2)
    assert len(zs) == 1
    z = zs[0]
    assert z.touches == 2 and z.low == pytest.approx(102.9 - 0.25) and z.high == pytest.approx(103.1 + 0.25)
    assert z.known_at == T0 + 11 * SEC                                      # the latest known_at of its swings: not before both were confirmed


def test_zone_min_touches_and_artifacts_and_invalid_atr():
    s = [sw("H", 3, 103.1), sw("L", 8, 102.9)]
    assert build_zones(s, 1.0, min_touches=3) == []
    art = Swing("H", 1, 3, 103.0, 0, 1, "M15", True)
    assert build_zones(s + [art], 1.0, min_touches=3) == []                 # an artifact swing is not a touch
    assert build_zones(s, float("nan")) == [] and build_zones(s, 0.0) == []


# ====================================================================== trend / direction context
def test_structure_trend_series_is_causal_and_align_uses_only_closed_higher_bars():
    t, o, h, l, c = walk(800, seed=3, vol=1.4, sec=900)
    full = structure_trend_series(h, l, c, t, "M15")
    for cut in (200, 400, 799):
        assert (structure_trend_series(h[:cut], l[:cut], c[:cut], t[:cut], "M15") == full[:cut]).all()
    hi_t = np.array([T0, T0 + 3600, T0 + 7200]); vals = np.array(["UP", "DOWN", "NONE"], dtype=object)
    low_t = np.array([T0, T0 + 2700, T0 + 3600 + 2700, T0 + 7200 + 2700])        # bar opens; closes at +900
    out = align_to(low_t, "M15", hi_t, "H1", vals)
    # a 15m bar closing at T0+900 has no closed H1 yet; the one closing at T0+3600 sees the first H1 bar (closed at T0+3600)
    assert out[0] == "UNKNOWN" and out[1] == "UP" and out[2] == "DOWN" and out[3] == "NONE"


def test_direction_is_unknown_during_warmup_and_prefix_stable():
    t, o, h, l, c = walk(500, seed=4, vol=1.0, drift=0.3, sec=3600)
    d = direction_series(o, h, l, c, t, "H1")
    assert (d[:150] == "UNKNOWN").all()
    assert (direction_series(o[:300], h[:300], l[:300], c[:300], t[:300], "H1") == d[:300]).all()


# ====================================================================== setup state machine (hand-built scenario)
def bar(o, h, l, c):
    return (o, h, l, c)


def scenario(extra=()):
    """flat 100 (ATR warm-up), impulse 100 -> 108, pullback into the 103 zone, bullish pin bar at the zone, then `extra` bars."""
    rows = [bar(100, 100.2, 99.8, 100)] * 20
    px = 100.0
    for i in range(8):                                    # impulse bars 20..27 (+1 per bar)
        rows.append(bar(px, px + 1.2, px - 0.1, px + 1.0)); px += 1.0
    for cl in (107.0, 106.0, 105.0, 104.0):               # pullback bars 28..31
        rows.append(bar(cl + 1.0, cl + 1.1, cl - 0.2, cl))
    rows.append(bar(104.0, 104.1, 103.1, 103.3))          # bar 32: low 103.1 enters the 103 zone, bearish (no confirmation)
    rows.append(bar(103.4, 103.7, 102.7, 103.6))          # bar 33: bullish pin bar at the zone
    rows.extend(extra)
    o, h, l, c = (np.array([r[i] for r in rows], dtype=float) for i in range(4))
    t = T0 + np.arange(len(rows)) * SEC
    swings = [sw("H", 3, 103.1, 5), sw("L", 8, 102.9, 10), sw("L", 19, 99.8, 21), sw("H", 27, 108.1, 29)]
    return o, h, l, c, t, swings


def run(extra=(), ctx="UP", policy=POLICY, swings=None, ctx_arr=None):
    o, h, l, c, t, s = scenario(extra)
    n = len(c)
    arr = np.full(n, ctx, dtype=object) if ctx_arr is None else ctx_arr(n)
    return run_setups(o, h, l, c, t, "M15", s if swings is None else swings, arr, policy=policy), (o, h, l, c, t)


def states(res, direction="BUY"):
    return [(e["state"], e["bar_idx"]) for e in res["events"] if e["direction"] == direction]


def test_full_lifecycle_to_entry_eligible_then_window_end():
    extra = [bar(103.7, 104.4, 103.6, 104.2),             # 34: close above the entry band -> ENTRY_WINDOW
             bar(104.2, 104.3, 103.6, 103.8),             # 35: back inside the band -> ENTRY_ELIGIBLE
             bar(103.8, 103.85, 103.5, 103.7), bar(103.7, 103.8, 103.55, 103.75), bar(103.75, 103.85, 103.6, 103.7)]   # 36..38 inside the band (window ends at 37)
    res, _ = run(extra)
    seq = states(res)
    assert [s for s, _ in seq] == ["SETUP_FORMING", "PULLBACK_IN_PROGRESS", "AT_RELEVANT_ZONE", "AWAITING_CONFIRMATION", "CONFIRMED",
                                   "ENTRY_WINDOW", "ENTRY_ELIGIBLE", "EXPIRED"], seq
    idx = dict((s, i) for s, i in seq)
    assert idx["AT_RELEVANT_ZONE"] == 32 and idx["CONFIRMED"] == 33 and idx["ENTRY_WINDOW"] == 34 and idx["ENTRY_ELIGIBLE"] == 35 and idx["EXPIRED"] == 38
    conf = next(e for e in res["events"] if e["state"] == "CONFIRMED")
    assert conf["entry_level"] == pytest.approx(103.6) and conf["invalidation_level"] < 102.55
    assert any("CONFIRMATION" in x for x in conf["evidence"]) and any("ZONE" in x for x in conf["evidence"]) and conf["next_required_event"]
    assert next(e for e in res["events"] if e["state"] == "EXPIRED")["reasons"] == ["ENTRY_WINDOW_ENDED"]
    assert not [e for e in res["events"] if e["direction"] == "SELL"]


def test_every_event_is_known_at_its_bar_close_and_setup_ids_are_stable_and_unique_per_setup():
    res, (o, h, l, c, t) = run([bar(103.7, 104.4, 103.6, 104.2)])
    ids = {e["setup_id"] for e in res["events"]}
    assert len(ids) == 1 and next(iter(ids)).startswith("M15-BUY-")
    for e in res["events"]:
        assert e["known_at"] == int(t[e["bar_idx"]]) + SEC and e["policy_version"] == "setup-1"
    res2, _ = run([bar(103.7, 104.4, 103.6, 104.2)])
    assert [e["setup_id"] for e in res["events"]] == [e["setup_id"] for e in res2["events"]]            # deterministic


def test_zone_failed_invalidates():
    extra = [bar(103.6, 103.6, 100.9, 101.0)]                                                         # close far below the zone low minus buffer
    res, _ = run(extra)
    # confirmation already happened at bar 33 here, so use a scenario WITHOUT confirmation: replace the pin bar
    o, h, l, c, t, s = scenario()
    o[33], h[33], l[33], c[33] = 103.3, 103.4, 102.9, 103.0                                           # an ordinary bar, no pattern
    o = np.append(o, 103.0); h = np.append(h, 103.1); l = np.append(l, 100.8); c = np.append(c, 101.0); t = np.append(t, t[-1] + SEC)
    res = run_setups(o, h, l, c, t, "M15", s, np.full(len(c), "UP", dtype=object))
    seq = states(res)
    assert seq[-1][0] == "INVALIDATED" and next(e for e in res["events"] if e["state"] == "INVALIDATED")["reasons"] == ["ZONE_FAILED"]


def test_confirmation_timeout_expires():
    o, h, l, c, t, s = scenario()
    o[33], h[33], l[33], c[33] = 103.3, 103.4, 102.9, 103.0
    extra = [(103.0 + 0.01 * i, 103.2, 102.8, 103.0) for i in range(8)]                              # hover at the zone, never a pattern
    o = np.concatenate([o, [x[0] for x in extra]]); h = np.concatenate([h, [x[1] for x in extra]])
    l = np.concatenate([l, [x[2] for x in extra]]); c = np.concatenate([c, [x[3] for x in extra]]); t = T0 + np.arange(len(c)) * SEC
    res = run_setups(o, h, l, c, t, "M15", s, np.full(len(c), "UP", dtype=object))
    ev = [e for e in res["events"] if e["state"] == "EXPIRED"]
    assert ev and ev[0]["reasons"] == ["CONFIRMATION_TIMEOUT"] and ev[0]["bar_idx"] == 32 + 6


def test_price_running_away_before_any_entry_band_is_missed_not_eligible():
    res, _ = run([bar(103.7, 106.0, 103.65, 105.9)])                                                  # +2.3 above entry, far outside the band, > 1 ATR chase
    seq = [s for s, _ in states(res)]
    assert seq[-1] == "MISSED" and "ENTRY_ELIGIBLE" not in seq
    assert next(e for e in res["events"] if e["state"] == "MISSED")["reasons"] == ["PRICE_RAN_AWAY"]


def test_invalidation_level_touch_after_confirmation():
    res, _ = run([bar(103.5, 103.6, 102.0, 102.1)])
    assert states(res)[-1][0] == "INVALIDATED"
    assert next(e for e in res["events"] if e["state"] == "INVALIDATED")["reasons"] == ["INVALIDATION_LEVEL_TOUCHED"]


def test_context_lost_invalidates_before_confirmation_only():
    o, h, l, c, t, s = scenario()
    o[33], h[33], l[33], c[33] = 103.3, 103.4, 102.9, 103.0
    n = len(c)
    ctx = np.full(n, "UP", dtype=object); ctx[33:] = "NONE"
    res = run_setups(o, h, l, c, t, "M15", s, ctx)
    assert states(res)[-1][0] == "INVALIDATED" and next(e for e in res["events"] if e["state"] == "INVALIDATED")["reasons"] == ["CONTEXT_LOST"]
    # after CONFIRMED the higher-timeframe context flipping does not cancel the already confirmed setup (entry window logic governs it)
    o2, h2, l2, c2, t2, s2 = scenario([bar(103.7, 104.4, 103.6, 104.2)])
    ctx2 = np.full(len(c2), "UP", dtype=object); ctx2[34:] = "NONE"
    res2 = run_setups(o2, h2, l2, c2, t2, "M15", s2, ctx2)
    assert "CONFIRMED" in [s for s, _ in states(res2)] and states(res2)[-1][0] == "ENTRY_WINDOW"


def test_no_direction_or_conflict_creates_no_setup():
    assert run(ctx="NONE")[0]["events"] == [] and run(ctx="UNKNOWN")[0]["events"] == []
    o, h, l, c, t, s = scenario()
    res = run_setups(o, h, l, c, t, "M15", s, np.full(len(c), "UP", dtype=object), ctx_conflict=np.ones(len(c), dtype=bool))
    assert res["events"] == []


def test_sell_is_the_exact_mirror_of_buy():
    o, h, l, c, t, s = scenario([bar(103.7, 104.4, 103.6, 104.2), bar(104.2, 104.3, 103.6, 103.8)])
    buy = run_setups(o, h, l, c, t, "M15", s, np.full(len(c), "UP", dtype=object))
    mo, mh, ml, mc = -o, -l, -h, -c                                                                   # the same market seen upside down
    ms = [Swing("L" if x.kind == "H" else "H", x.idx, x.known_idx, -x.price, x.formed_at, x.known_at, "M15") for x in s]
    sell = run_setups(mo, mh, ml, mc, t, "M15", ms, np.full(len(c), "DOWN", dtype=object))
    b = [(e["state"], e["bar_idx"], e["reasons"]) for e in buy["events"] if e["direction"] == "BUY"]
    s_ = [(e["state"], e["bar_idx"], e["reasons"]) for e in sell["events"] if e["direction"] == "SELL"]
    assert b and b == s_
    be = next(e for e in buy["events"] if e["state"] == "CONFIRMED"); se = next(e for e in sell["events"] if e["state"] == "CONFIRMED")
    assert se["entry_level"] == pytest.approx(-be["entry_level"]) and se["invalidation_level"] == pytest.approx(-be["invalidation_level"])
    assert not [e for e in buy["events"] if e["direction"] == "SELL"] and not [e for e in sell["events"] if e["direction"] == "BUY"]


# ====================================================================== properties on random markets
ALLOWED = {None: {"SETUP_FORMING"}, "SETUP_FORMING": {"PULLBACK_IN_PROGRESS", "EXPIRED", "INVALIDATED"},
           "PULLBACK_IN_PROGRESS": {"AT_RELEVANT_ZONE", "INVALIDATED", "EXPIRED"},
           "AT_RELEVANT_ZONE": {"AWAITING_CONFIRMATION", "CONFIRMED"}, "AWAITING_CONFIRMATION": {"CONFIRMED", "INVALIDATED", "EXPIRED"},
           "CONFIRMED": {"ENTRY_WINDOW", "ENTRY_ELIGIBLE", "INVALIDATED", "MISSED", "EXPIRED"},
           "ENTRY_WINDOW": {"ENTRY_ELIGIBLE", "INVALIDATED", "MISSED", "EXPIRED"}, "ENTRY_ELIGIBLE": {"ENTRY_WINDOW", "INVALIDATED", "EXPIRED"}}
TERMINAL = {"INVALIDATED", "MISSED", "EXPIRED"}


def market(seed, n=1200, ctx_every=40):
    t, o, h, l, c = walk(n, seed=seed, vol=1.6, drift=0.02, sec=900)
    sws = zigzag_swings(h, l, c, t, "M15", k=1.5)                       # k below the production 2.5 on purpose: more setups to exercise the machine
    rng = np.random.default_rng(seed)
    ctx = np.empty(n, dtype=object)
    for i in range(0, n, ctx_every):
        ctx[i:i + ctx_every] = rng.choice(["UP", "DOWN", "NONE"])
    return t, o, h, l, c, sws, ctx


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5, 6])
def test_transitions_are_legal_ids_never_repeat_after_terminal_and_events_are_rare(seed):
    t, o, h, l, c, sws, ctx = market(seed)
    res = run_setups(o, h, l, c, t, "M15", sws, ctx)
    by: dict[str, list] = {}
    for e in res["events"]:
        by.setdefault(e["setup_id"], []).append(e)
    for sid, evs in by.items():
        prev = None
        for e in evs:
            assert e["state"] in ALLOWED[prev], (sid, prev, e["state"])
            assert prev not in TERMINAL
            prev = e["state"]
        assert sum(1 for e in evs if e["state"] in TERMINAL) <= 1
    assert len(res["events"]) < len(c) / 3                                  # events only on transitions, never one per bar/tick
    assert len(by) == len({e["setup_id"] for e in res["events"] if e["state"] == "SETUP_FORMING"})


def test_random_markets_actually_exercise_the_confirmation_path():
    seen, reasons = set(), set()
    for seed in range(1, 25):
        t, o, h, l, c, sws, ctx = market(seed)
        for e in run_setups(o, h, l, c, t, "M15", sws, ctx)["events"]:
            seen.add(e["state"])
            if e["state"] in TERMINAL:
                reasons.add((e["state"], e["reasons"][0]))
    every_state = {"SETUP_FORMING", "PULLBACK_IN_PROGRESS", "AT_RELEVANT_ZONE", "AWAITING_CONFIRMATION", "CONFIRMED", "ENTRY_WINDOW",
                   "ENTRY_ELIGIBLE", "INVALIDATED", "MISSED", "EXPIRED"}
    assert every_state <= seen, every_state - seen                                             # the property tests above are not vacuous
    for r in (("INVALIDATED", "ZONE_FAILED"), ("INVALIDATED", "STRUCTURE_BROKEN"), ("INVALIDATED", "CONTEXT_LOST"),
              ("INVALIDATED", "INVALIDATION_LEVEL_TOUCHED"), ("MISSED", "PRICE_RAN_AWAY"), ("EXPIRED", "CONFIRMATION_TIMEOUT"),
              ("EXPIRED", "ENTRY_WINDOW_ENDED"), ("EXPIRED", "SUPERSEDED_BY_CONTINUATION")):
        assert r in reasons, r


@pytest.mark.parametrize("seed", [1, 2, 3, 4])
def test_no_future_information_prefix_equals_full(seed):
    t, o, h, l, c, sws, ctx = market(seed, n=900)
    full = run_setups(o, h, l, c, t, "M15", sws, ctx)
    key = lambda L: [(e["setup_id"], e["state"], e["bar_idx"], e["direction"], e["entry_level"], e["invalidation_level"]) for e in L]
    for cut in (200, 333, 500, 700, 900):
        sw_cut = zigzag_swings(h[:cut], l[:cut], c[:cut], t[:cut], "M15", k=1.5)
        part = run_setups(o[:cut], h[:cut], l[:cut], c[:cut], t[:cut], "M15", sw_cut, ctx[:cut])
        assert key(part["events"]) == key([e for e in full["events"] if e["bar_idx"] < cut]), (seed, cut)


# ====================================================================== WAIT taxonomy / current status
def status_for(extra, ctx="UP", **kw):
    res, (o, h, l, c, t) = run(extra, ctx=ctx)
    return current_status(res, len(c), ctx_last=ctx, **kw), res


def test_wait_reasons_follow_the_active_state():
    st, _ = status_for([bar(103.7, 104.4, 103.6, 104.2)])
    assert st["decision_context"] == "WAIT" and st["wait_reason"] == "ENTRY_WINDOW_NOT_OPEN"
    st, _ = status_for([bar(103.7, 104.4, 103.6, 104.2), bar(104.2, 104.3, 103.6, 103.8)])
    assert st["decision_context"] == "ENTRY_ELIGIBLE" and st["wait_reason"] is None
    assert status_for([], ctx="NONE")[0]["wait_reason"] == "NO_DIRECTION"
    assert status_for([], ctx="UP", stale=True)[0]["wait_reason"] == "DATA_STALE"
    assert status_for([], ctx="UNKNOWN")[0]["wait_reason"] == "INSUFFICIENT_HISTORY"
    assert status_for([], ctx="UP", history_ok=False)[0]["wait_reason"] == "INSUFFICIENT_HISTORY"


def test_signal_conflict_when_both_directions_are_active_or_higher_timeframe_opposes():
    res = {"events": [{"setup_id": "a", "direction": "BUY", "state": "SETUP_FORMING", "zone": None}, {"setup_id": "b", "direction": "SELL", "state": "SETUP_FORMING", "zone": None}]}
    assert current_status(res, 10, "UP")["wait_reason"] == "SIGNAL_CONFLICT"
    assert current_status({"events": []}, 10, "UP", conflict_last=True)["wait_reason"] == "SIGNAL_CONFLICT"
    assert current_status({"events": []}, 10, "UP")["wait_reason"] == "AWAITING_PULLBACK"
