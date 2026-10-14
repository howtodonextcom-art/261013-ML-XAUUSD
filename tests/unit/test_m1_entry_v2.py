"""M1 Entry Intelligence V2 (shadow): state machine on hand-built arrays, the 'wick without confirmation' case, mirror, causality (prefix invariance and
future corruption on a synthetic market, mutation-checked), determinism, V1 independence."""
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in ("services/intelligence", "tests/unit"):
    sys.path.insert(0, str(ROOT / p))
from xau_intel.backtest.engine import canon  # noqa: E402
from xau_intel.m1 import entry_v2 as V  # noqa: E402
from xau_intel.m1.entry_v2 import POLICY, _idx_at, _scan, forming_observation, run_v2  # noqa: E402
from xau_intel.structure import Swing  # noqa: E402

T0 = 1_791_900_000 - (1_791_900_000 % 900)


def swing(kind, idx, price, known_idx, sec=900):
    return Swing(kind, idx, known_idx, price, T0 + idx * sec, T0 + known_idx * sec + sec, "M15")


def build(n1=80, n5=40, pin1=(), eng1=(), any5=(), c1=None, c5=None, l5=None):
    """BUY-coordinate arrays. Zone from two confirmed M15 swing lows at 99.5 with ATR15 = 2 -> zone [99.0, 100.0]. ATR1 = 0.4, ATR5 = 1.0."""
    t1 = T0 + 60 * np.arange(n1)
    t5 = T0 + 300 * np.arange(n5)
    close1 = np.full(n1, 100.3) if c1 is None else np.asarray(c1, float)
    m1 = {"time": t1, "open": close1.copy(), "high": close1 + 0.1, "low": close1 - 0.1, "close": close1}
    close5 = np.full(n5, 100.3) if c5 is None else np.asarray(c5, float)
    m5 = {"time": t5, "open": close5.copy(), "high": close5 + 0.2, "low": (close5 - 0.2) if l5 is None else np.asarray(l5, float), "close": close5}
    z = lambda n: np.zeros(n, dtype=bool)
    pat1 = {"pin_bull": z(n1), "engulf_bull": z(n1)}
    for i in pin1:
        pat1["pin_bull"][i] = True
    for i in eng1:
        pat1["engulf_bull"][i] = True
    pat5 = {"any_bull": z(n5)}
    for j in any5:
        pat5["any_bull"][j] = True
        m5["low"][j] = min(m5["low"][j], 99.8)                       # the confirming M5 bar reaches into the zone (zone.high = 100.0)
    sw15 = [swing("L", 0, 99.5, 0), swing("L", 1, 99.5, 1)]          # confirmed early (known at T0+900 s and T0+1800 s)
    j5 = np.array([_idx_at(t5, "M5", int(x) + 60) for x in t1])
    j15 = np.zeros(n1, dtype=int)
    return {"m1": m1, "m5": m5, "sw15": sw15, "sw1": [], "ctx_ok": np.ones(n1, dtype=bool), "pat1": pat1, "pat5": pat5, "atr1": np.full(n1, 0.4), "atr5": np.full(n5, 1.0),
            "atr15": np.full(1, 2.0), "j5": j5, "j15": j15, "c5": m5["close"], "l5": m5["low"]}


def stages(res):
    return [(e["stage"], e["kind"]) for e in res["events"]]


def test_a_full_sequence_zone_m5_confirmation_m1_trigger_entry_window_expired():
    A = build(any5=[8], pin1=[50])                                  # M5 bar 8 closes at T0+2700 s (M1 index 45); the pin bar is M1 bar 50, after it
    r = _scan(1, A, POLICY)
    st = stages(r)
    assert st[0] == ("M5_CONFIRMED_AWAITING_M1", "M5_CONFIRMED") and st[1] == ("M1_TRIGGERED", "M1_REJECTION")
    trig = r["events"][1]
    assert trig["bar_time"] == int(A["m1"]["time"][50]) and trig["known_at"] == int(A["m1"]["time"][50]) + 60          # knowable at the CLOSE of the trigger bar
    assert r["events"][0]["known_at"] >= int(A["m5"]["time"][8]) + 300                                                  # never before the M5 bar closed
    assert ("ENTRY_WINDOW", "WINDOW_STATE") in st                                                                        # price stays in the entry band
    assert st[-1] == ("EXPIRED", "EXPIRED")                                                                              # 5 M1 bars later the window ends
    assert r["state"]["stage"] in ("WATCHING_ZONE", "NO_ZONE")                                                           # afterwards the machine looks for the next setup


def test_a_wick_rejection_on_m1_WITHOUT_the_m5_confirmation_is_never_a_trigger_or_a_signal():
    """The case the user asked for: an M1 pin bar appears, but the M5 confirmation is missing."""
    r = _scan(1, build(any5=[], pin1=[50]), POLICY)
    assert r["events"] == []
    assert r["state"]["stage"] == "WATCHING_ZONE" and "M5 confirmation" in r["state"]["next_required"] and "trigger" not in r["state"]


def test_a_trigger_bar_before_the_m5_confirmation_was_known_is_ignored():
    r = _scan(1, build(any5=[8], pin1=[30]), POLICY)                # M1 bar 30 closes at T0+1860 s, the M5 bar 8 closed at T0+2700 s: not knowable yet
    assert all(e["kind"] != "M1_REJECTION" for e in r["events"])


def test_missed_invalidated_and_failed_confirmation_are_terminal_and_distinct():
    c = [100.3] * 80
    for k in range(51, 56):
        c[k] = 102.0                                                 # price runs 1.4 above the trigger close (> 0.5 ATR5): MISSED
    r = _scan(1, build(any5=[8], pin1=[50], c1=c), POLICY)
    assert ("MISSED", "MISSED") in stages(r) and ("EXPIRED", "EXPIRED") not in stages(r)
    c2 = [100.3] * 80
    for k in range(51, 56):
        c2[k] = 98.5                                                 # closes below zone.low - 0.25 ATR5 = 98.75: INVALIDATED
    r2 = _scan(1, build(any5=[8], pin1=[50], c1=c2), POLICY)
    assert ("INVALIDATED", "INVALIDATED") in stages(r2)
    c5 = [100.3] * 40
    for j in range(9, 14):
        c5[j] = 98.0                                                 # M5 closes beyond the zone before any M1 trigger
    r3 = _scan(1, build(any5=[8], c5=c5, l5=[x - 0.2 for x in c5]), POLICY)
    assert ("FAILED_CONFIRMATION", "FAILED_CONFIRMATION") in stages(r3)
    assert all(e["kind"] != "M1_REJECTION" for e in r3["events"])


def test_the_confirmation_expires_when_no_m1_trigger_arrives_in_time():
    r = _scan(1, build(any5=[8]), POLICY)
    assert ("CONFIRMATION_EXPIRED", "CONFIRMATION_EXPIRED") in stages(r)


def test_engulfing_triggers_too_and_the_first_matching_kind_names_the_event():
    r = _scan(1, build(any5=[8], eng1=[50]), POLICY)
    assert ("M1_TRIGGERED", "M1_ENGULFING") in stages(r)
    assert sum(1 for e in r["events"] if e["stage"] == "M1_TRIGGERED" and e["kind"] != "WINDOW_STATE") == 1                # exactly one trigger per confirmation
    both = _scan(1, build(any5=[8], pin1=[50], eng1=[50]), POLICY)
    trig = [e for e in both["events"] if e["stage"] == "M1_TRIGGERED"][0]
    assert trig["kind"] == "M1_REJECTION" and "M1_ENGULFING" in trig["evidence"]


def test_sell_is_the_exact_mirror_of_buy():
    A = build(any5=[8], pin1=[50])
    buy = _scan(1, A, POLICY)
    sell = _scan(-1, A, POLICY)        # the SELL scan receives MIRRORED prices of the real market; here the mirrored prices are the BUY arrays
    assert [(e["stage"], e["kind"], e["known_at"], e["bar_time"]) for e in buy["events"]] == [(e["stage"], e["kind"], e["known_at"], e["bar_time"]) for e in sell["events"]]
    z, zs = buy["events"][1]["zone"], sell["events"][1]["zone"]
    assert zs["low"] == pytest.approx(-z["high"]) and zs["high"] == pytest.approx(-z["low"])
    assert all(e["direction"] == "SELL" for e in sell["events"]) and all(e["direction"] == "BUY" for e in buy["events"])


def test_no_context_means_no_events_and_a_clear_stage():
    A = build(any5=[8], pin1=[50])
    A["ctx_ok"][:] = False
    r = _scan(1, A, POLICY)
    assert r["events"] == [] and r["state"]["stage"] == "NO_CONTEXT"


def test_the_forming_bar_observation_is_display_only_and_never_an_event():
    v2 = {"primary": "BUY", "directions": {"BUY": {"stage": "WATCHING_ZONE"}}}
    pin = {"open": 100.5, "high": 100.3, "low": 99.4, "close": 100.55}      # long lower wick, small body near the high, range 1.2 >= 0.5 ATR
    obs = forming_observation(pin, 0.4, v2)
    assert obs and obs["confirmed"] is False and obs["candidate"] == "FORMING_REJECTION_CANDIDATE" and "unconfirmed" in obs["note"]
    assert forming_observation({"open": 100.0, "high": 100.1, "low": 99.95, "close": 100.05}, 0.4, v2) is None            # not a pin geometry
    assert forming_observation(pin, 0.4, {"primary": "BUY", "directions": {"BUY": {"stage": "NO_ZONE"}}}) is None         # no zone: nothing to observe
    assert forming_observation(pin, 0.4, {"primary": None, "directions": {}}) is None
    assert forming_observation(None, 0.4, v2) is None


# ------------------------------------------------------------------ a synthetic multi-timeframe market for the causality tests
def agg(t, o, h, l, c, k):
    n = len(c) // k
    sl = slice(0, n * k)
    return {"time": t[sl][::k], "open": o[sl].reshape(n, k)[:, 0], "high": h[sl].reshape(n, k).max(1), "low": l[sl].reshape(n, k).min(1), "close": c[sl].reshape(n, k)[:, -1]}


def synth_market(n1=60 * 24 * 14, seed=3):
    rng = np.random.default_rng(seed)
    t = T0 - (T0 % 14400) + 60 * np.arange(n1)
    wave = 0.012 * np.sin(2 * np.pi * np.arange(n1) / 3000.0) + 0.006 * np.sin(2 * np.pi * np.arange(n1) / 700.0)
    close = 2000 + np.cumsum(wave + rng.normal(0, 0.7, n1))
    open_ = np.concatenate([[2000.0], close[:-1]])
    high = np.maximum(open_, close) + np.abs(rng.normal(0, 0.35, n1))
    low = np.minimum(open_, close) - np.abs(rng.normal(0, 0.35, n1))
    bars = {"M1": {"time": t, "open": open_, "high": high, "low": low, "close": close}}
    for tf, k in (("M5", 5), ("M15", 15), ("H1", 60), ("H4", 240)):
        bars[tf] = agg(t, open_, high, low, close, k)
    return bars


@pytest.fixture(scope="module")
def market():
    return synth_market()


def cuts_for(market, full):
    """Cuts anchored on the triggers themselves (the moment a trigger became knowable) plus fractional cuts: a peeking trigger is only visible there."""
    n = len(market["M1"]["time"])
    anchored = [e["known_at"] for e in full if e["stage"] == "M1_TRIGGERED"][:10]
    return anchored + [int(market["M1"]["time"][int(n * f)]) + 60 for f in (0.35, 0.6, 0.85)]


def test_the_synthetic_market_exercises_the_pipeline(market):
    r = run_v2(market, int(market["M1"]["time"][-1]) + 60, window=10**9)
    kinds = {e["stage"] for e in r["events"]}
    assert "M5_CONFIRMED_AWAITING_M1" in kinds and "M1_TRIGGERED" in kinds, kinds
    assert r["label"].startswith("SHADOW")


def test_prefix_invariance_events_known_at_an_earlier_time_do_not_change_when_later_bars_arrive(market):
    full = run_v2(market, int(market["M1"]["time"][-1]) + 60, window=10**9)["events"]
    checked = 0
    for cut in cuts_for(market, full):
        early = run_v2(market, cut, window=10**9)["events"]
        want = [e for e in full if e["known_at"] <= cut]
        assert canon(early) == canon(want), f"look-ahead at cut {cut}"
        checked += len(want)
    assert checked > 20


def test_future_corruption_does_not_change_the_past(market):
    n = len(market["M1"]["time"])
    cut = int(market["M1"]["time"][int(n * 0.6)]) + 60
    bad = {tf: {k: v.copy() for k, v in b.items()} for tf, b in market.items()}
    for tf, b in bad.items():
        after = b["time"] >= cut
        for k in ("open", "high", "low", "close"):
            b[k][after] = b[k][after] * 3 + 700
    a = run_v2(market, cut, window=10**9)
    b = run_v2(bad, cut, window=10**9)
    assert canon(a["events"]) == canon(b["events"]) and canon(a["directions"]) == canon(b["directions"])


def test_the_lookahead_detector_detects_a_peeking_trigger(market, monkeypatch):
    """Mutation: make the M1 pin pattern peek one bar ahead; the prefix test must then fail."""
    real = V.candle_patterns

    def peeking(o, h, l, c, atr):
        r = real(o, h, l, c, atr)
        if len(c) > 5000:                                              # M1 arrays only
            for key in ("pin_bull", "pin_bear", "any_bull", "any_bear"):
                r[key] = np.concatenate([r[key][1:], [False]])         # the flag of bar i+1 attributed to bar i
        return r
    monkeypatch.setattr(V, "candle_patterns", peeking)
    full = run_v2(market, int(market["M1"]["time"][-1]) + 60, window=10**9)["events"]
    bad = False
    for cut in cuts_for(market, full):
        early = run_v2(market, cut, window=10**9)["events"]
        if canon(early) != canon([e for e in full if e["known_at"] <= cut]):
            bad = True
    assert bad, "the prefix-invariance test is blind to a peeking pattern"


def test_determinism_and_v1_independence(market):
    now = int(market["M1"]["time"][-1]) + 60
    assert canon(run_v2(market, now)) == canon(run_v2(market, now))
    src = (ROOT / "services/intelligence/xau_intel/setups/machine.py").read_text(encoding="utf-8") + (ROOT / "services/intelligence/xau_intel/decision/decide.py").read_text(encoding="utf-8")
    assert "entry_v2" not in src and "xau_intel.m1" not in src and ".m1 " not in src       # V1 never imports V2: a V2 change cannot move a V1 decision


def test_event_prices_are_real_prices_for_sell_not_mirrored_ones():
    """Regression (found by inspecting the live forward log): SELL trigger_close/trigger_low were logged in mirrored (negated) space."""
    A = build(any5=[8], pin1=[50])
    buy = [e for e in _scan(1, A, POLICY)["events"] if e["stage"] == "M1_TRIGGERED" and e["kind"] != "WINDOW_STATE"][0]
    sell = [e for e in _scan(-1, A, POLICY)["events"] if e["stage"] == "M1_TRIGGERED" and e["kind"] != "WINDOW_STATE"][0]
    assert sell["trigger_close"] == pytest.approx(-buy["trigger_close"]) and sell["trigger_low"] == pytest.approx(-buy["trigger_low"])   # the test arrays ARE the mirror: real = -(array)
    assert buy["trigger_close"] > 0 and buy["log_schema"] == 2 and sell["log_schema"] == 2
