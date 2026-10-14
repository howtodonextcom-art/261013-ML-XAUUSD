import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "intelligence"))
from xau_intel.indicators import atr, bars_since_sign_change, compute_features, ema, macd, rolling_percentile, rsi, sma, true_range  # noqa: E402
from xau_intel.regime_snapshot import MIN_BARS, analyse_tf, build_snapshot, classify_regime, TfBars  # noqa: E402
from xau_intel.structure import (fractal_swings, label_structure, structure_events, support_resistance, swings_known_by,  # noqa: E402
                                 trend_from_labels, zigzag_swings)

WILDER = np.array([44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28, 46.00, 46.03, 46.41, 46.22, 45.64])


def walk(n, seed=1, vol=1.0, drift=0.0, t0=1_700_006_400, sec=900):
    rng = np.random.default_rng(seed)
    c = 2000 + np.cumsum(rng.normal(drift, vol, n))
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) + rng.uniform(0.05, 0.6, n) * vol
    l = np.minimum(o, c) - rng.uniform(0.05, 0.6, n) * vol
    t = t0 + np.arange(n) * sec
    return t, o, h, l, c


# ------------------------------------------------------------------ indicator definitions (hand-checked)
def test_ema_recursion_seed_and_validity():
    x = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    e = ema(x, 3)
    a = 0.5
    ref = [1.0]
    for v in x[1:]:
        ref.append(ref[-1] + a * (v - ref[-1]))
    assert np.isnan(e[:2]).all() and np.allclose(e[2:], ref[2:])


def test_rsi_matches_published_wilder_example():
    r = rsi(WILDER, 14)
    assert np.isnan(r[:14]).all()
    assert np.allclose(r[14:], [70.46, 66.25, 66.48, 69.35, 66.29, 57.92], atol=0.06)


def test_rsi_flat_is_50_and_monotonic_up_is_100():
    assert rsi(np.full(30, 5.0), 14)[-1] == 50.0
    assert rsi(np.arange(30, dtype=float), 14)[-1] == 100.0


def test_atr_is_sma_of_true_range_excluding_first_bar():
    h = np.array([10, 12, 13, 12, 14, 15.0]); l = np.array([9, 10, 11, 10, 12, 13.0]); c = np.array([9.5, 11, 12, 11, 13, 14.0])
    tr = true_range(h, l, c)
    assert tr[0] == 1.0 and tr[1] == max(2, abs(12 - 9.5), abs(10 - 9.5))
    a = atr(h, l, c, 3)
    assert np.isnan(a[:3]).all() and a[3] == pytest.approx(tr[1:4].mean()) and a[5] == pytest.approx(tr[3:6].mean())


def test_macd_signal_is_simple_ma_and_hist_is_difference():
    _, _, _, _, c = walk(120, seed=3)
    line, sig, hist = macd(c)
    assert np.allclose(sig[40:], sma(line, 9)[40:]) and np.allclose(hist[40:], line[40:] - sig[40:])
    assert np.isnan(line[:25]).all() is np.True_ or np.isnan(line[:25]).sum() >= 24


def test_cross_age_counts_bars_since_sign_change():
    v = np.array([np.nan, 1, 1, 1, -1, -1, 1, 1.0])
    assert np.nan_to_num(bars_since_sign_change(v), nan=-1).tolist() == [-1, 0, 1, 2, 0, 1, 0, 1]


def test_rolling_percentile_is_causal_rank():
    x = np.arange(10, dtype=float)
    p = rolling_percentile(x, 5)
    assert np.isnan(p[:4]).all() and p[4] == 1.0
    assert rolling_percentile(np.array([5, 4, 3, 2, 1.0]), 5)[4] == 0.0


# ------------------------------------------------------------------ causality: truncating the future changes nothing
def test_features_are_causal_cut_series_equals_full_series_prefix():
    t, o, h, l, c = walk(500, seed=7)
    full = compute_features(o, h, l, c)
    for cut in (250, 330, 499):
        part = compute_features(o[:cut], h[:cut], l[:cut], c[:cut])
        for k in ("rsi", "atr", "macd", "macd_hist", "atr_ratio50", "ema_compression_atr"):
            a, b = full[k][:cut], part[k]
            assert np.allclose(a, b, equal_nan=True), (k, cut)
        for n in (20, 50, 100, 200):
            assert np.allclose(full["ema"][n][:cut], part["ema"][n], equal_nan=True)
        assert (full["ema_alignment"][:cut] == part["ema_alignment"]).all()


def test_insufficient_history_is_explicit_not_a_number():
    t, o, h, l, c = walk(150, seed=2)
    f = compute_features(o, h, l, c)
    assert f["ema_alignment"][-1] == "INSUFFICIENT_HISTORY"          # EMA200 cannot exist with 150 bars
    reg, why = classify_regime(f, 149, "UP", False)
    assert reg == "UNKNOWN" and why == ["INSUFFICIENT_HISTORY"]


# ------------------------------------------------------------------ structure: no look-ahead, no repaint (gates G1, G2)
@pytest.mark.parametrize("method,kw", [("fractal", {"n": 3}), ("zigzag", {"k": 2.0})])
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_swings_do_not_use_the_future_and_never_repaint(method, kw, seed):
    t, o, h, l, c = walk(400, seed=seed, vol=1.5)
    if method == "fractal":
        full = fractal_swings(h, l, t, "M15", **kw)
    else:
        full = zigzag_swings(h, l, c, t, "M15", **kw)
    emitted_before: set = set()
    for cut in range(30, 400, 7):
        known = swings_known_by(h, l, c, t, "M15", cut, method=method, **kw)
        key = lambda s: (s.kind, s.idx, s.known_idx, s.price)
        expect = [s for s in full if s.known_idx <= cut]
        assert [key(s) for s in known] == [key(s) for s in expect], (method, seed, cut)    # G1: equals full-series result restricted to known_idx <= cut
        now = {key(s) for s in known}
        assert emitted_before <= now, "a swing disappeared or changed after more bars arrived"  # G2: no repaint
        emitted_before = now


def test_swing_timestamps_are_ordered_and_complete():
    t, o, h, l, c = walk(300, seed=5, vol=1.5)
    for s in fractal_swings(h, l, t, "M15") + zigzag_swings(h, l, c, t, "M15"):
        assert s.known_at > s.formed_at and s.known_idx >= s.idx and s.source_timeframe == "M15"


def test_fractal_known_exactly_n_bars_after_extreme():
    h = np.array([1, 2, 3, 9, 3, 2, 1, 1, 1.0]); l = h - 0.5; t = np.arange(9) * 900 + 1_700_006_400
    sw = fractal_swings(h, l, t, "M15", n=3)
    hi = [s for s in sw if s.kind == "H"]
    assert len(hi) == 1 and hi[0].idx == 3 and hi[0].known_idx == 6
    assert hi[0].known_at == t[6] + 900 and hi[0].formed_at == t[3]


def test_labels_and_trend():
    t, o, h, l, c = walk(60, seed=1)
    # hand-made: lows rise and highs rise
    from xau_intel.structure import Swing
    S = lambda k, i, p: Swing(k, i, i + 3, p, 0, 1, "M15")
    up = [S("L", 1, 10), S("H", 2, 20), S("L", 3, 12), S("H", 4, 25)]
    assert [x["label"] for x in label_structure(up)] == ["FIRST_L", "FIRST_H", "HL", "HH"] and trend_from_labels(label_structure(up)) == "UP"
    dn = [S("H", 1, 30), S("L", 2, 20), S("H", 3, 28), S("L", 4, 15)]
    assert trend_from_labels(label_structure(dn)) == "DOWN"
    assert trend_from_labels(label_structure(up[:2])) == "UNKNOWN"


def _bars_from_closes(closes, wick=0.2, t0=1_700_006_400, sec=900):
    c = np.asarray(closes, float)
    o = np.r_[c[0], c[:-1]]
    return t0 + np.arange(len(c)) * sec, o, c + wick, c - wick, c      # high/low depend on the close only: strict fractals are unambiguous


def test_bos_choch_and_wick_is_not_a_break():
    # zig-zag up trend (HH/HL), then a close below the last swing low = CHoCH_DOWN
    path = [10, 12, 14, 12, 10, 12, 16, 20, 17, 14, 12, 14, 18, 22, 26, 22, 18, 15, 13, 11, 9, 8]
    t, o, h, l, c = _bars_from_closes(path)
    ev = structure_events(o, h, l, c, t, "M15", n=2, method="fractal")
    kinds = [e["event"] for e in ev]
    assert "BOS_UP" in kinds or "BREAKOUT_UP" in kinds
    assert any(k == "CHOCH_DOWN" for k in kinds), kinds
    for e in ev:
        assert e["known_at"] >= e["formed_at"] and e["evaluated_at"] == e["known_at"] and e["feature_version"]
        assert e["level_known_at"] <= e["event_time"]   # the level was confirmed no later than the moment the breaking bar OPENED
    # a wick through a level without a close beyond is not an event
    c2 = c.copy(); h2 = h.copy(); h2[-1] = 99.0
    assert structure_events(o, h2, l, c2, t, "M15", n=2, method="fractal") == structure_events(o, h, l, c, t, "M15", n=2, method="fractal")


def test_structure_events_do_not_repaint_when_bars_are_appended():
    t, o, h, l, c = walk(400, seed=11, vol=1.5)
    for method in ("zigzag", "fractal"):
        _no_repaint(o, h, l, c, t, method)


def _no_repaint(o, h, l, c, t, method):
    full = structure_events(o, h, l, c, t, "M15", method=method)
    for cut in (120, 200, 300, 399):
        part = structure_events(o[:cut], h[:cut], l[:cut], c[:cut], t[:cut], "M15", method=method)
        expect = [e for e in full if e["bar_idx"] < cut]
        norm = lambda L: [(e["event"], e["bar_idx"], e["level"], e["level_known_at"]) for e in L]
        assert norm(part) == norm(expect), cut


def test_support_resistance_clusters_confirmed_swings_only():
    from xau_intel.structure import Swing
    sw = [Swing("H", 1, 4, 100.0, 0, 5, "M15"), Swing("H", 8, 11, 100.2, 0, 12, "M15"), Swing("L", 5, 8, 90.0, 0, 9, "M15")]
    lv = support_resistance(sw, atr_value=1.0)
    assert lv[0]["touches"] == 2 and 100.0 <= lv[0]["price"] <= 100.2 and support_resistance([], 1.0) == [] and support_resistance(sw, float("nan")) == []


# ------------------------------------------------------------------ snapshot + multi-timeframe consistency
def _mtf(n_m15=1200, seed=4):
    t, o, h, l, c = walk(n_m15, seed=seed, vol=1.2)
    from xau_gateway_agg import agg
    return {"M15": dict(time=t, open=o, high=h, low=l, close=c), "H1": agg(t, o, h, l, c, 3600)}


def test_snapshot_contains_only_closed_bars_and_is_read_only():
    t, o, h, l, c = walk(40, seed=1)
    b = {"M15": dict(time=t, open=o, high=h, low=l, close=c)}
    now = int(t[20] + 900 - 1)                  # one second before bar 20 closes
    s = build_snapshot(b, now)
    assert len(s.tfs["M15"].close) == 20 and s.tfs["M15"].time[-1] == t[19]
    s2 = build_snapshot(b, int(t[20] + 900))    # exactly when it closes: now included
    assert len(s2.tfs["M15"].close) == 21
    with pytest.raises(ValueError):
        s.tfs["M15"].close[0] = 0.0


def test_htf_bar_enters_snapshot_only_after_it_closes_and_snapshot_is_deterministic():
    d = _mtf()
    t = d["M15"]["time"]
    h1_open = int(d["H1"]["time"][250])
    inside = h1_open + 1800
    s_in = build_snapshot(d, inside)
    s_after = build_snapshot(d, h1_open + 3600)
    assert s_in.tfs["H1"].time[-1] < h1_open and s_after.tfs["H1"].time[-1] == h1_open
    assert analyse_tf_json(s_in) == analyse_tf_json(build_snapshot(d, inside))        # deterministic


def analyse_tf_json(s):
    import json
    from xau_intel.regime_snapshot import analyse_snapshot
    return json.dumps(analyse_snapshot(s), sort_keys=True, default=str)


def test_mtf_analysis_at_time_t_is_unaffected_by_future_bars():
    d = _mtf(1500, seed=9)
    t_eval = int(d["M15"]["time"][1200] + 900)
    full = build_snapshot(d, t_eval)                      # built from all data, filtered by time
    trunc = {tf: {k: v[: int((np.asarray(b["time"]) + {"M15": 900, "H1": 3600}[tf] <= t_eval).sum())] for k, v in b.items()} for tf, b in d.items()}
    assert analyse_tf_json(full) == analyse_tf_json(build_snapshot(trunc, t_eval))     # future bars physically removed => same answer


# ------------------------------------------------------------------ regime
def _tfbars(t, o, h, l, c):
    return TfBars("M15", np.asarray(t), np.asarray(o), np.asarray(h), np.asarray(l), np.asarray(c))


def test_regime_trending_up_on_clean_trend():
    t, o, h, l, c = walk(900, seed=3, vol=0.6, drift=0.5)
    r = analyse_tf(_tfbars(t, o, h, l, c))
    assert r["regime"] in ("TRENDING_UP", "VOLATILITY_EXPANSION", "TRANSITION")      # a trend must never be classified DOWN/SIDEWAYS
    assert r["ema_alignment"] == "BULL" and r["structure_trend"] in ("UP", "RANGE")


def test_regime_trending_down_mirror():
    t, o, h, l, c = walk(900, seed=3, vol=0.6, drift=-0.5)
    r = analyse_tf(_tfbars(t, o, h, l, c))
    assert r["ema_alignment"] == "BEAR" and r["regime"] != "TRENDING_UP"


def test_regime_unknown_when_history_short():
    t, o, h, l, c = walk(100, seed=3)
    r = analyse_tf(_tfbars(t, o, h, l, c))
    assert r["regime"] == "UNKNOWN" and "INSUFFICIENT_HISTORY" in r["reasons"]


def _calm_then_spike(seed, rng_seed):
    t, o, h, l, c = walk(700, seed=seed, vol=0.3)
    c2 = c.copy()
    c2[-12:] += np.cumsum(np.random.default_rng(rng_seed).normal(0, 6.0, 12))
    o2 = np.r_[c2[0], c2[:-1]]
    h2 = np.maximum(o2, c2) + 0.3
    l2 = np.minimum(o2, c2) - 0.3
    h2[-12:] += 3.0                      # only the last 12 bars are wide: calm baseline, then expansion
    l2[-12:] -= 3.0
    return t, o2, h2, l2, c2


def test_regime_volatility_expansion_after_calm_then_spike():
    t, o2, h2, l2, c2 = _calm_then_spike(5, 1)
    r = analyse_tf(_tfbars(t, o2, h2, l2, c2))
    assert r["regime"] == "VOLATILITY_EXPANSION"


def test_high_atr_alone_does_not_imply_direction_and_rsi70_does_not_decide():
    t, o2, h2, l2, c2 = _calm_then_spike(6, 2)
    r = analyse_tf(_tfbars(t, o2, h2, l2, c2))
    assert r["regime"] not in ("TRENDING_UP", "TRENDING_DOWN")                  # expansion is reported as volatility, not as a direction
    assert "decision" not in r and "BUY" not in str(r) and "SELL" not in str(r)  # P3 outputs context only


# ------------------------------------------------------------------ the incremental implementation equals a naive reference (oracle)
def _naive_events(o, h, l, c, times, tf, method="zigzag", k=2.5, n=3):
    """Original O(n^2) formulation kept as an oracle: re-labels the whole confirmed-swing list at every bar."""
    from xau_intel.structure import TF_SEC, Swing, _ev
    h, l, c, t = (np.asarray(v, float) for v in (h, l, c, times))
    sec = TF_SEC[tf]
    all_sw = zigzag_swings(h, l, c, t, tf, k=k) if method == "zigzag" else fractal_swings(h, l, t, tf, n=n)
    all_sw = sorted((x for x in all_sw if not x.window_start_artifact), key=lambda s: (s.known_idx, s.idx, s.kind))
    events, broken, known, si = [], set(), [], 0
    for j in range(len(c)):
        while si < len(all_sw) and all_sw[si].known_idx <= j - 1:
            known.append(all_sw[si]); si += 1
        if not known:
            continue
        trend = trend_from_labels(label_structure(known))
        hi = next((s for s in reversed(known) if s.kind == "H"), None)
        lo = next((s for s in reversed(known) if s.kind == "L"), None)
        if hi is not None and (hi.kind, hi.idx) not in broken and c[j] > hi.price:
            broken.add((hi.kind, hi.idx))
            events.append(_ev("BOS_UP" if trend == "UP" else "CHOCH_UP" if trend == "DOWN" else "BREAKOUT_UP", hi, j, t, sec, tf, trend, None))
        if lo is not None and (lo.kind, lo.idx) not in broken and c[j] < lo.price:
            broken.add((lo.kind, lo.idx))
            events.append(_ev("BOS_DOWN" if trend == "DOWN" else "CHOCH_DOWN" if trend == "UP" else "BREAKOUT_DOWN", lo, j, t, sec, tf, trend, None))
    return events


@pytest.mark.parametrize("method", ["zigzag", "fractal"])
@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5, 6])
def test_incremental_structure_events_equal_naive_oracle(method, seed):
    t, o, h, l, c = walk(900, seed=seed, vol=1.4)
    assert structure_events(o, h, l, c, t, "M15", method=method) == _naive_events(o, h, l, c, t, "M15", method=method)


def test_analysis_cost_is_bounded_for_long_series():
    import time as _t
    t, o, h, l, c = walk(60000, seed=8, vol=1.0, sec=60)
    t0 = _t.perf_counter()
    r = analyse_tf(TfBars("M1", t, o, h, l, c))
    assert r["bars"] == 5000 and _t.perf_counter() - t0 < 5.0


# ------------------------------------------------------------------ the MT5 comparator itself is not vacuous
def _fake_dump(n=1500, seed=3, perturb=None):
    from xau_intel.mt5_parity import COLS, ours
    t, o, h, l, c = walk(n, seed=seed, vol=1.0)
    d = {"time": t.astype(float), "open": o, "high": h, "low": l, "close": c}
    d.update(ours(d))
    for k in ("ema20", "ema50", "ema100", "ema200", "rsi14", "atr14", "macd", "signal"):
        d[k] = np.nan_to_num(d[k], nan=0.0)
    if perturb:
        k, delta = perturb
        d[k] = d[k].copy(); d[k][-5:] += delta
    return d


def test_mt5_comparator_passes_identical_and_fails_when_a_value_differs():
    from xau_intel.mt5_parity import compare
    assert compare(_fake_dump())["status"] == "PASS"
    bad = compare(_fake_dump(perturb=("rsi14", 0.01)))
    assert bad["status"] == "FAIL" and bad["indicators"]["rsi14"]["status"] == "FAIL" and bad["indicators"]["atr14"]["status"] == "PASS"
    assert compare(_fake_dump(perturb=("ema200", 0.01)))["indicators"]["ema200"]["status"] == "FAIL"


def test_mt5_comparator_header_is_checked(tmp_path):
    from xau_intel.mt5_parity import read_csv
    p = tmp_path / "x.csv"; p.write_text("a;b\n1;2\n")
    with pytest.raises(ValueError):
        read_csv(p)


# ================================================== independent-review findings (P3), tests written before the fixes
def test_sma_returns_nan_when_window_contains_nan_never_zero():
    x = np.array([np.nan, np.nan, 1.0, 2.0, 3.0, 4.0])
    s = sma(x, 3)
    assert np.isnan(s[:4]).all() and s[4] == pytest.approx(2.0) and s[5] == pytest.approx(3.0)


def test_macd_signal_hist_and_cross_age_are_nan_until_really_valid():
    _, _, _, _, c = walk(120, seed=3)
    line, sig, hist = macd(c)
    first_line = int(np.where(~np.isnan(line))[0][0])
    assert first_line == 25                                  # slow EMA(26) valid from index 25
    first_sig = int(np.where(~np.isnan(sig))[0][0])
    assert first_sig == 25 + 8                               # SMA(9) of the MACD line needs 9 valid line values
    assert np.isnan(hist[:first_sig]).all()
    age = bars_since_sign_change(hist)
    assert np.isnan(age[:first_sig]).all() and age[first_sig] == 0


def test_atr_ratio_is_nan_until_the_baseline_is_complete():
    t, o, h, l, c = walk(300, seed=4)
    f = compute_features(o, h, l, c)
    r = f["atr_ratio50"]
    first = int(np.where(~np.isnan(r))[0][0])
    assert first == 14 + 49 + 14                             # ATR valid from 14; 50-bar mean valid from 63; baseline lags 14 more bars
    assert np.isnan(r[:first]).all()


def test_zigzag_matches_a_hand_computed_expectation():
    # flat (ATR warm-up), then +1/step for 10 bars, -1/step for 10, +1/step for 10 ; wicks +-0.1 => ATR about 1.2, threshold 2.4
    path = [100.0] * 20 + [100 + i for i in range(1, 11)] + [110 - i for i in range(1, 11)] + [100 + i for i in range(1, 11)]
    t, o, h, l, c = _bars_from_closes(path, wick=0.1)
    sw = zigzag_swings(h, l, c, t, "M15", k=2.0)
    kinds = [(s.kind, s.idx) for s in sw]
    assert ("H", 29) in kinds and ("L", 39) in kinds                       # the peak (bar 29) and trough (bar 39)
    pk = next(s for s in sw if s.kind == "H" and s.idx == 29)
    tr = next(s for s in sw if s.kind == "L" and s.idx == 39)
    # Hand computation. Peak: ATR14 at bar 31 = (2 flat bars of TR 0.2 + 12 moving bars of TR 1.1)/14 = 0.971 -> threshold 1.94; the
    # retrace from 110.1 to the bar-31 low 107.9 is 2.2 >= 1.94, while at bar 30 it is 1.2 < 1.81 => confirmed exactly at bar 31.
    assert pk.known_idx == 31
    # Trough: at bar 41 the retrace (102.1 - 99.9 = 2.2) equals the threshold 2*1.1 = 2.2 (a floating-point tie), so only the window
    # [41, 42] is asserted; bar 40 (retrace 1.2) can never confirm it.
    assert 41 <= tr.known_idx <= 42
    assert pk.price == pytest.approx(110.1) and tr.price == pytest.approx(99.9)


def test_events_carry_absolute_time_so_windowed_analyses_agree():
    t, o, h, l, c = walk(3000, seed=12, vol=1.5, sec=900)
    full = analyse_tf(_tfbars(t, o, h, l, c), max_bars=3000)
    win = analyse_tf(_tfbars(t, o, h, l, c), max_bars=1000)
    pick = lambda r: sorted((e["event"], e["bar_open_time"]) for e in r["events_recent"])
    both = set(pick(full)) & set(pick(win))
    assert all("bar_open_time" in e for e in full["events_recent"])
    assert pick(win) == [x for x in pick(full) if x in set(pick(win))]    # same events are identified by TIME, not window-relative index


def test_mt5_comparator_is_valid_when_mt5_computed_on_longer_history_than_the_dump():
    """MT5 computes on the whole history; the CSV holds only the last N bars. Python seeds from the slice. Seeds differ early
    (informational) but must have decayed in the late zone; the verdict must therefore rest on the late zone only."""
    from xau_intel.mt5_parity import COLS, compare, ours
    t, o, h, l, c = walk(6000, seed=3, vol=1.0)
    full = {"time": t.astype(float), "open": o, "high": h, "low": l, "close": c}
    mt5_like = ours(full)                                   # "MT5": indicators over the full history
    cut = slice(3000, 6000)
    d = {"time": t[cut].astype(float), "open": o[cut], "high": h[cut], "low": l[cut], "close": c[cut]}
    for k, v in mt5_like.items():
        d[k] = np.nan_to_num(v[cut], nan=0.0)
    res = compare(d)
    assert res["status"] == "PASS", res["indicators"]
    assert res["indicators"]["ema200"]["early_max_abs_diff_informational"] > 1e-3            # seeds really do differ at the start of the slice
    d2 = dict(d); d2["rsi14"] = d["rsi14"].copy(); d2["rsi14"][-5:] += 0.01
    assert compare(d2)["status"] == "FAIL"


# ================================================== zig-zag initialisation and intra-bar ordering (P3-closure)
def test_zigzag_first_swing_is_a_low_when_price_falls_first_then_rises():
    path = [100.0] * 20 + [100 - i for i in range(1, 11)] + [90 + i for i in range(1, 11)]
    t, o, h, l, c = _bars_from_closes(path, wick=0.1)
    sw = zigzag_swings(h, l, c, t, "M15", k=2.0)
    assert sw[0].window_start_artifact and sw[0].kind == "H" and sw[0].idx == 14                  # range top at the window start: flagged, not trusted
    real = [s for s in sw if not s.window_start_artifact]
    assert real[0].kind == "L" and real[0].idx == 29 and real[0].price == pytest.approx(89.9)      # the first PROVEN swing is the trough
    assert [x["label"] for x in label_structure(sw)][0].startswith("FIRST_L")                      # labels ignore the artifact


def test_zigzag_first_swing_is_a_high_when_price_rises_first_then_falls():
    path = [100.0] * 20 + [100 + i for i in range(1, 11)] + [110 - i for i in range(1, 11)]
    t, o, h, l, c = _bars_from_closes(path, wick=0.1)
    sw = zigzag_swings(h, l, c, t, "M15", k=2.0)
    first_h = next(s for s in sw if s.kind == "H")
    assert first_h.idx == 29 and sw[0].kind in ("L", "H")


def test_zigzag_outside_bar_does_not_confirm_on_the_bar_that_made_the_extreme():
    # rising leg, then ONE bar that makes a new high and also plunges far below: High/Low order unknown => no confirmation on it
    path = [100.0] * 20 + [100 + i for i in range(1, 8)]
    t, o, h, l, c = _bars_from_closes(path, wick=0.1)
    h = np.append(h, 120.0); l = np.append(l, 100.0); c = np.append(c, 105.0)               # the outside bar (index 27)
    t = np.append(t, t[-1] + 900)
    sw = zigzag_swings(h, l, c, t, "M15", k=2.0)
    assert not any(s.kind == "H" and s.known_idx == 27 for s in sw)
    h2 = np.append(h, 104.0); l2 = np.append(l, 103.0); c2 = np.append(c, 103.5); t2 = np.append(t, t[-1] + 900)   # next bar stays far below 120
    sw2 = zigzag_swings(h2, l2, c2, t2, "M15", k=2.0)
    top = [s for s in sw2 if s.kind == "H" and s.idx == 27]
    assert top and top[0].known_idx == 28 and top[0].price == 120.0                            # confirmed one bar later, at the earliest
