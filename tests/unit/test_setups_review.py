"""Regression tests for the independent review of the setup machine (P4)."""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "intelligence"))
sys.path.insert(0, str(Path(__file__).parent))
from xau_intel.setups.machine import SetupPolicy, current_status, run_setups  # noqa: E402
from xau_intel.setups.trend_series import align_to, direction_series  # noqa: E402
from xau_intel.structure import Swing, zigzag_swings  # noqa: E402
from test_setups import SEC, T0, bar, market, scenario, sw  # noqa: E402
from test_intel import walk  # noqa: E402
from xau_gateway_agg import agg  # noqa: E402

C_OFF = 200.0


def mirror_arrays(o, h, l, c, swings):
    ms = [Swing("L" if x.kind == "H" else "H", x.idx, x.known_idx, C_OFF - x.price, x.formed_at, x.known_at, x.source_timeframe, x.window_start_artifact)
          for x in swings]
    return C_OFF - o, C_OFF - l, C_OFF - h, C_OFF - c, ms


def test_confirmation_bar_must_touch_the_zone_not_merely_be_a_pattern_above_it():
    o, h, l, c, t, s = scenario()
    # bar 32 touches the zone; bar 33 is a strong bullish bar entirely ABOVE the zone (low 105.35 > zone high 103.45)
    o[33], h[33], l[33], c[33] = 105.4, 106.6, 105.35, 106.5
    res = run_setups(o, h, l, c, t, "M15", s, np.full(len(c), "UP", dtype=object))
    assert "CONFIRMED" not in [e["state"] for e in res["events"]]
    assert [e["state"] for e in res["events"]][-1] == "AWAITING_CONFIRMATION"


def test_sell_evidence_is_printed_in_real_prices_not_mirrored_ones():
    o, h, l, c, t, s = scenario([bar(103.7, 104.4, 103.6, 104.2)])
    mo, mh, ml, mc, ms = mirror_arrays(o, h, l, c, s)                  # a real downtrend with positive prices (200 - original)
    res = run_setups(mo, mh, ml, mc, t, "M15", ms, np.full(len(mc), "DOWN", dtype=object))
    sell = [e for e in res["events"] if e["direction"] == "SELL"]
    conf = next(e for e in sell if e["state"] == "CONFIRMED")
    txt = " ".join(conf["evidence"])
    assert "-" not in txt.replace("higher-timeframe", "").replace("ATR", "").split("ZONE")[1]       # no negative price anywhere in zone/confirmation text
    assert f"{C_OFF - 103.6:.2f}" in txt                                                              # confirmation close in real price: 96.40
    zl, zh = conf["zone"]["low"], conf["zone"]["high"]
    assert zl < zh and zl > 0 and conf["entry_level"] == pytest.approx(C_OFF - 103.6)


def test_first_event_has_no_previous_state_and_the_chain_is_consistent():
    for seed in (1, 2, 3):
        t, o, h, l, c, sws, ctx = market(seed)
        by = {}
        for e in run_setups(o, h, l, c, t, "M15", sws, ctx)["events"]:
            by.setdefault(e["setup_id"], []).append(e)
        assert by
        for evs in by.values():
            assert evs[0]["prev_state"] is None and evs[0]["state"] == "SETUP_FORMING"
            for a, b in zip(evs, evs[1:]):
                assert b["prev_state"] == a["state"]


def test_a_stale_impulse_does_not_spawn_a_late_setup_and_age_counts_from_the_impulse():
    o, h, l, c, t, s = scenario()
    ctx = np.full(len(c), "NONE", dtype=object); ctx[40:] = "UP"
    n = len(c)
    pad = 40 - n
    # extend the series so the context only turns UP 30 bars after the impulse high became known (known_idx 29)
    extra = [bar(105.0, 105.2, 104.8, 105.0)] * 40
    rows_o = np.concatenate([o, [x[0] for x in extra]]); rows_h = np.concatenate([h, [x[1] for x in extra]])
    rows_l = np.concatenate([l, [x[2] for x in extra]]); rows_c = np.concatenate([c, [x[3] for x in extra]])
    tt = T0 + np.arange(len(rows_c)) * SEC
    ctx = np.full(len(rows_c), "NONE", dtype=object); ctx[60:] = "UP"                      # first UP bar is 31 bars after known_idx 29
    res = run_setups(rows_o, rows_h, rows_l, rows_c, tt, "M15", s, ctx)
    assert res["events"] == []                                                              # older than max_impulse_age_bars (20): no setup
    ctx2 = np.full(len(rows_c), "NONE", dtype=object); ctx2[45:] = "UP"                    # 16 bars after: still allowed
    res2 = run_setups(rows_o, rows_h, rows_l, rows_c, tt, "M15", s, ctx2, policy=SetupPolicy(max_impulse_age_bars=20))
    assert any(e["state"] == "SETUP_FORMING" for e in res2["events"])
    # age is counted from the impulse high: a setup created late still dies at known_idx + max_setup_age_bars
    long_o = np.concatenate([rows_o, np.full(60, 105.0)]); long_h = np.concatenate([rows_h, np.full(60, 105.2)])
    long_l = np.concatenate([rows_l, np.full(60, 104.8)]); long_c = np.concatenate([rows_c, np.full(60, 105.0)])
    lt = T0 + np.arange(len(long_c)) * SEC
    lctx = np.full(len(long_c), "NONE", dtype=object); lctx[45:] = "UP"
    res3 = run_setups(long_o, long_h, long_l, long_c, lt, "M15", s, lctx)
    exp = [e for e in res3["events"] if e["state"] == "EXPIRED" and e["reasons"] == ["SETUP_AGE"]]
    assert exp and exp[0]["bar_idx"] == 29 + 60 + 1


def test_conflict_at_decision_time_cancels_entry_readiness_of_an_eligible_setup():
    extra = [bar(103.7, 104.4, 103.6, 104.2), bar(104.2, 104.3, 103.6, 103.8)]
    o, h, l, c, t, s = scenario(extra)
    res = run_setups(o, h, l, c, t, "M15", s, np.full(len(c), "UP", dtype=object))
    assert current_status(res, len(c), "UP")["decision_context"] == "ENTRY_ELIGIBLE"
    st = current_status(res, len(c), "UP", conflict_last=True)
    assert st["decision_context"] == "WAIT" and st["wait_reason"] == "SIGNAL_CONFLICT" and st["active"]


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5, 6, 7, 8])
def test_random_market_upside_down_gives_the_same_lifecycle_for_the_opposite_direction(seed):
    """Not just the hand-built scenario: a whole random market seen upside down (200 - price) must produce the same states, bars and
    reason codes for SELL as the original does for BUY, with levels mapped by 200 - x."""
    t, o, h, l, c, sws, ctx = market(seed, n=900)
    ctx_up = np.where(ctx == "DOWN", "NONE", ctx).astype(object)               # keep UP periods only: the original run is BUY-only
    buy = run_setups(o, h, l, c, t, "M15", sws, ctx_up)
    mo, mh, ml, mc, ms = mirror_arrays(o, h, l, c, sws)
    ctx_dn = np.where(ctx_up == "UP", "DOWN", "NONE").astype(object)
    sell = run_setups(mo, mh, ml, mc, t, "M15", ms, ctx_dn)
    kb = [(e["state"], e["bar_idx"], e["reasons"][0]) for e in buy["events"] if e["direction"] == "BUY"]
    ks = [(e["state"], e["bar_idx"], e["reasons"][0]) for e in sell["events"] if e["direction"] == "SELL"]
    assert kb and kb == ks
    for eb, es in zip([e for e in buy["events"] if e["direction"] == "BUY"], [e for e in sell["events"] if e["direction"] == "SELL"]):
        for k in ("entry_level", "invalidation_level"):
            if eb[k] is not None:
                assert es[k] == pytest.approx(C_OFF - eb[k])


@pytest.mark.parametrize("seed", [3, 5, 9])
def test_full_pipeline_prefix_equals_full_h1_context_included(seed):
    """The prefix test recomputes the higher-timeframe direction and the alignment from truncated data (not by slicing ctx)."""
    t, o, h, l, c = walk(1600, seed=seed, vol=1.4, drift=0.04, sec=900)
    h1 = agg(t, o, h, l, c, 3600)

    def run_on(n):
        tn, on, hn, ln, cn = t[:n], o[:n], h[:n], l[:n], c[:n]
        hh = agg(tn, on, hn, ln, cn, 3600)
        d1 = direction_series(hh["open"], hh["high"], hh["low"], hh["close"], hh["time"], "H1")
        ctx = align_to(tn, "M15", hh["time"], "H1", d1)
        sws = zigzag_swings(hn, ln, cn, tn, "M15", k=1.5)
        return run_setups(on, hn, ln, cn, tn, "M15", sws, ctx)["events"], ctx

    full, ctx_full = run_on(1600)
    key = lambda L: [(e["setup_id"], e["state"], e["bar_idx"], e["entry_level"], e["invalidation_level"]) for e in L]
    seen_up = int((ctx_full == "UP").sum()) + int((ctx_full == "DOWN").sum())
    assert seen_up > 100                                                                  # the H1 context is really exercised
    for cut in (700, 1000, 1333, 1599):
        part, ctx_part = run_on(cut)
        assert (ctx_part == ctx_full[:cut]).all(), cut
        assert key(part) == key([e for e in full if e["bar_idx"] < cut]), cut


def test_sell_setups_use_mirrored_next_event_wording():
    """The independent QA found a BUY sentence ('above the invalidation level', 'bullish') on a SELL setup."""
    from xau_intel.setups.machine import NEXT_EVENT, NEXT_EVENT_SELL
    assert set(NEXT_EVENT) == set(NEXT_EVENT_SELL)
    for k, v in NEXT_EVENT_SELL.items():
        assert "bullish" not in v and "support" not in v and "below the impulse high" not in v and "above the invalidation" not in v, (k, v)
