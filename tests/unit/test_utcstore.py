"""UTC-keyed bar store (Level 5.5 P0): offsets come only from measured evidence; DST overlap/gap bars are excluded, never guessed or invented."""
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in ("services/gateway", "services/intelligence"):
    sys.path.insert(0, str(ROOT / p))
from xau_gateway import utcstore as U  # noqa: E402
from xau_gateway.storage import BAR_SCHEMA, Store  # noqa: E402

SERVER, SYMBOL, SRC = "Test-Server", "XAUUSD", "mt5_hist_bars"
T0 = 1_791_000_000 - (1_791_000_000 % 86400)          # a UTC midnight
H = 3600


def write_legacy(store, server_times, price=4100.0):
    n = len(server_times)
    rows = {"source_id": [SRC] * n, "server": [SERVER] * n, "symbol": [SYMBOL] * n, "tf": ["M1"] * n, "time": [int(x) for x in server_times],
            "open": [price + 0.01 * i for i in range(n)], "high": [price + 0.5 + 0.01 * i for i in range(n)], "low": [price - 0.5 + 0.01 * i for i in range(n)],
            "close": [price + 0.2 + 0.01 * i for i in range(n)], "tick_volume": [10] * n, "spread": [30] * n, "real_volume": [0] * n, "dataset_version": ["t"] * n}
    return store.write_chunk("bars_m1", BAR_SCHEMA, rows, source_id=SRC, server=SERVER, symbol=SYMBOL, chunk="legacy-1", key_col="time", partition="m")


def test_an_offset_is_only_accepted_when_measured_evidence_of_that_offset_brackets_the_bar():
    runs = U.runs_of([(T0, 10800), (T0 + 10 * 86400, 10800)])
    inside = T0 + 3 * 86400
    assert U.resolve_offset(inside + 10800, runs) == (10800, "EVIDENCED_BRACKETED")
    near = T0 + 10 * 86400 + 2 * H
    assert U.resolve_offset(near + 10800, runs) == (None, "UNKNOWN_NO_EVIDENCE")                # no extension past the last measurement: a switch may sit right after it (round 13)
    far = T0 + 10 * 86400 + 12 * H
    assert U.resolve_offset(far + 10800, runs) == (None, "UNKNOWN_NO_EVIDENCE")                 # beyond the near window: no guess
    assert U.resolve_offset(T0 - 30 * 86400 + 10800, runs) == (None, "UNKNOWN_NO_EVIDENCE")     # long before the first measurement


def test_bars_between_two_different_measured_offsets_are_unknown_and_the_repeated_hour_is_ambiguous():
    sw = T0 + 5 * 86400                                                                          # the broker moved from UTC+3 to UTC+2 at this instant
    sparse = U.runs_of([(T0, 10800), (sw - 86400, 10800), (sw + 86400, 7200), (sw + 5 * 86400, 7200)])
    s_in_gap = sw + 3 * H + 10800
    assert U.resolve_offset(s_in_gap, sparse)[1] == "UNKNOWN_SWITCH_GAP"                         # we only know the switch happened somewhere in this day-long gap
    assert U.resolve_offset(sw - 3 * 86400 + 10800, sparse) == (10800, "EVIDENCED_BRACKETED")
    assert U.resolve_offset(sw + 3 * 86400 + 7200, sparse) == (7200, "EVIDENCED_BRACKETED")
    dense = U.runs_of([(T0, 10800), (sw - 60, 10800), (sw + 60, 7200), (sw + 5 * 86400, 7200)])  # evidence right around the instant
    repeated = sw + 9000                                                                          # server stamp inside the repeated hour [sw+7200, sw+10800)
    off, status = U.resolve_offset(repeated, dense)
    assert off is None and status == "AMBIGUOUS_DST_OVERLAP"


def test_migration_derives_unique_utc_rows_without_touching_legacy_and_is_idempotent(tmp_path):
    store = Store(tmp_path / "s")
    server_times = [T0 + 10800 + 60 * i for i in range(3 * 1440)]
    server_times = [t for t in server_times if not (T0 + 10800 + 1440 * 60 + 600 <= t < T0 + 10800 + 1440 * 60 + 600 + 120 * 60)]         # a 120-bar hole
    write_legacy(store, server_times)
    U.add_offset_evidence(store, SERVER, T0 - 60, 10800, "HIGH", "gateway_live")
    U.add_offset_evidence(store, SERVER, T0 + 3 * 86400 + 3 * H, 10800, "HIGH", "gateway_live")
    legacy_before = [(f["path"], f["sha256"]) for f in store.files("bars_m1")]
    r1 = U.migrate(store, SERVER, SYMBOL)
    assert r1["written_rows"] == len(server_times) and not r1["excluded"] and r1["backup"] and Path(r1["backup"]).exists()
    bars = U.read_utc_bars(store, SERVER, SYMBOL)
    assert len(bars["time"]) == len(server_times) and len(np.unique(bars["time"])) == len(bars["time"])
    assert np.all(bars["server_time"] - bars["time"] == 10800)                                    # original server stamp preserved next to the UTC key
    assert int(np.sum(np.diff(bars["time"]) > 60)) == 1                                           # the hole is still a hole: no candle was invented
    assert [(f["path"], f["sha256"]) for f in store.files("bars_m1")] == legacy_before            # legacy untouched
    r2 = U.migrate(store, SERVER, SYMBOL, backup=False)
    assert set(r2["chunks"].values()) == {"identical"}                                            # idempotent: nothing new written
    assert len(store.files(U.KIND)) == len(store.files(U.KIND, include_superseded=True))          # and nothing superseded
    again = U.read_utc_bars(Store(tmp_path / "s"), SERVER, SYMBOL)                                 # a fresh process (restart) reads the same rows
    assert np.array_equal(again["time"], bars["time"])


def test_a_dst_switch_inside_the_data_excludes_the_unprovable_hours_and_never_collides(tmp_path):
    store = Store(tmp_path / "s")
    sw = T0 + 2 * 86400                                                                           # UTC instant of the broker switch UTC+3 -> UTC+2 (fall-back)
    utc_ticks = np.arange(T0, T0 + 4 * 86400, 60)
    server = np.where(utc_ticks < sw, utc_ticks + 10800, utc_ticks + 7200)                        # the TRUE broker stamps: the hour [sw+7200, sw+10800) occurs twice
    legacy = {}
    for s in server:                                                                              # legacy store is keyed by server stamp: the repeated hour collapses (last wins)
        legacy[int(s)] = 1
    write_legacy(store, sorted(legacy))
    for obs, off in ((T0 + 60, 10800), (sw - 2 * H, 10800), (sw + 2 * H, 7200), (T0 + 4 * 86400 - 60, 7200)):
        U.add_offset_evidence(store, SERVER, obs, off, "HIGH", "gateway_live")
    rep = U.migrate(store, SERVER, SYMBOL)
    bars = U.read_utc_bars(store, SERVER, SYMBOL)
    assert len(np.unique(bars["time"])) == len(bars["time"])                                      # no two stamps map to one instant
    assert rep["excluded"].get("UNKNOWN_SWITCH_GAP", 0) > 0                                       # the hours around the switch are excluded: nothing guessed
    before, after = bars["time"] < sw - 2 * H, bars["time"] > sw + 2 * H
    assert np.all(bars["offset"][before] == 10800) and np.all(bars["offset"][after] == 7200)
    assert not np.any((bars["time"] > sw - 2 * H) & (bars["time"] < sw + 2 * H))                  # not one bar inside the unproven window


def test_rollback_removes_only_the_derived_kind_and_keeps_everything_on_disk(tmp_path):
    store = Store(tmp_path / "s")
    write_legacy(store, [T0 + 10800 + 60 * i for i in range(500)])
    U.add_offset_evidence(store, SERVER, T0, 10800, "HIGH", "gateway_live")
    U.add_offset_evidence(store, SERVER, T0 + 12 * H, 10800, "HIGH", "gateway_live")
    U.migrate(store, SERVER, SYMBOL)
    assert store.files(U.KIND)
    rb = U.rollback_utc(store)
    assert rb["manifest_rows_removed"] >= 1 and rb["moved_to"] and Path(rb["moved_to"]).exists()
    assert not store.files(U.KIND) and store.files("bars_m1")
    assert U.read_utc_bars(store, SERVER, SYMBOL)["time"].size == 0
    U.migrate(store, SERVER, SYMBOL)                                                               # and the migration can simply be run again
    assert U.read_utc_bars(store, SERVER, SYMBOL)["time"].size == 500


def test_closures_are_only_recognised_by_recurrence_never_by_length_alone():
    day = 86400
    t = []
    for d in range(6):                                                                             # six days; a 120-bar daily break at the same server clock time each day
        base = T0 + d * day
        t += [base + 60 * m for m in range(0, 1440) if not (1320 <= m < 1440)]
    t = np.array(t, dtype=np.int64)
    sigs = U.closure_signatures(t)
    assert len(sigs) == 1
    one_off = np.array([x for x in t if not (T0 + 2 * day + 600 * 60 <= x < T0 + 2 * day + 900 * 60)], dtype=np.int64)       # plus a single 300-minute outage in the middle of a day
    sigs2 = U.closure_signatures(one_off)
    assert sigs2 == sigs                                                                           # the outage never becomes a "closure"
    m1 = {"time": one_off, "server_time": one_off}
    wins = U.closure_windows(m1, sigs2)
    assert len(wins) == 5 and all((b - a) // 60 + 1 == 120 for a, b in wins)                       # the daily breaks are closures; the 300-bar outage is not


def test_the_gateway_records_high_confidence_offset_evidence_on_change_and_hourly_only(monkeypatch):
    import types
    import time as _t
    from xau_gateway import mt5_source as M
    got = []
    snap = {"v": (10800, "HIGH", 0.3, 50)}
    fake = types.SimpleNamespace(offset=types.SimpleNamespace(snapshot=lambda: snap["v"], recent_consistent=lambda off: True), status={}, on_offset=lambda *a: got.append(a), _ev_last=None)
    M.MT5TickSource._publish_offset(fake)
    M.MT5TickSource._publish_offset(fake)                                    # same offset, same minute: not recorded again
    assert len(got) == 1 and got[0][0] == 10800
    snap["v"] = (7200, "HIGH", 0.3, 50)
    M.MT5TickSource._publish_offset(fake)                                    # a changed offset is recorded at once (dense evidence around a broker switch)
    assert [g[0] for g in got] == [10800, 7200]
    snap["v"] = (7200, "LOW", 40.0, 50)
    fake._ev_last = (7200, _t.time() - 7200)
    M.MT5TickSource._publish_offset(fake)                                    # LOW confidence is never evidence, even when an hour has passed
    assert len(got) == 2
    snap["v"] = (7200, "HIGH", 0.3, 50)
    M.MT5TickSource._publish_offset(fake)                                    # an hour later with HIGH confidence: recorded
    assert len(got) == 3


# ---------------- review round 12 regressions
def test_h1_stamps_around_a_fall_back_never_get_the_wrong_offset_with_hourly_evidence():
    sw = T0 + 3 * 86400                                                                     # true switch UTC+3 -> UTC+2
    runs = U.runs_of([(T0, 10800), (sw - 1800, 10800), (sw + 1800, 7200), (T0 + 6 * 86400, 7200)])
    wrong = 0
    for k in range(-7200, 7200, 60):                                                        # every true bar from 2 h before to 2 h after the switch
        utc = sw + k
        true_off = 10800 if utc < sw else 7200
        off, status = U.resolve_offset(utc + true_off, runs)
        if off is not None and off != true_off:
            wrong += 1
    assert wrong == 0
    assert U.resolve_offset(sw + 9000, runs)[0] is None                                      # a stamp inside the repeated hour


def test_an_isolated_provisional_outlier_cannot_split_the_run_or_extend_evidence_and_far_apart_same_offset_points_do_not_bridge_a_season():
    ev = [(T0, 10800, True), (T0 + 86400, 7200, False), (T0 + 2 * 86400, 10800, True)]       # a connect-time point taken during the break
    runs = U.runs_of(ev)
    assert len(runs) == 1 and runs[0][0] == 10800
    only_provisional_last = U.runs_of([(T0, 10800, True), (T0 + 86400, 10800, False)])
    assert U.resolve_offset(T0 + 86400 + 5 * H + 10800, only_provisional_last)[0] is None  # a provisional edge never extends evidence beyond itself
    assert U.resolve_offset(T0 + 86400 + 10800, only_provisional_last)[0] is None           # and without a measured point on BOTH sides it is not used at all (round 14)
    sparse = U.runs_of([(T0, 10800), (T0 + 200 * 86400, 10800)])
    assert U.resolve_offset(T0 + 100 * 86400 + 7200, sparse)[0] is None                      # 200 days of silence: a whole season could have changed


def test_h4_a_month_that_loses_all_provable_rows_does_not_stay_active(tmp_path):
    store = Store(tmp_path / "s")
    write_legacy(store, [T0 + 10800 + 60 * i for i in range(120)])
    U.add_offset_evidence(store, SERVER, T0, 10800, "HIGH", "gateway_live")
    U.add_offset_evidence(store, SERVER, T0 + 6 * H, 10800, "HIGH", "gateway_live")
    assert U.migrate(store, SERVER, SYMBOL)["written_rows"] == 120 and U.read_utc_bars(store, SERVER, SYMBOL)["time"].size == 120
    with store._lock, store._db() as db:
        db.execute("DELETE FROM offset_evidence")                                            # evidence is replaced by one far-away point
    U.add_offset_evidence(store, SERVER, T0 + 400 * 86400, 10800, "HIGH", "gateway_live")
    rep = U.migrate(store, SERVER, SYMBOL)
    assert rep["written_rows"] == 0 and U.read_utc_bars(store, SERVER, SYMBOL)["time"].size == 0   # no stale rows are served
    assert len(store.files(U.KIND, include_superseded=True)) >= 1                            # the old chunk is kept on disk, only superseded


def test_h2_a_stale_high_window_is_not_fresh_after_a_broker_switch():
    from xau_gateway.timeutil import OffsetEstimator
    est = OffsetEstimator()
    for _ in range(50):
        est.add_fresh(1000.0 + 10800, 1000.0)                                                # 50 samples at UTC+3 (the previous week)
    assert est.recent_consistent(10800)
    for _ in range(4):
        est.add_fresh(2000.0 + 7200, 2000.0)                                                 # the first 4 ticks after the broker moved to UTC+2
    off, conf, _, _ = est.snapshot()
    assert (off, conf) == (10800, "HIGH")                                                    # the median is still the OLD offset and still HIGH ...
    assert not est.recent_consistent(10800)                                                  # ... but the freshness guard refuses it


def test_r13_two_consecutive_wrong_provisional_points_cannot_override_the_measured_offset():
    ev = [(T0, 10800, True), (T0 + 5 * 86400, 7200, False), (T0 + 6 * 86400, 7200, False), (T0 + 10 * 86400, 10800, True)]
    runs = U.runs_of(ev)
    assert [r[0] for r in runs] == [10800]                                                   # the provisional pair contradicts both measured neighbours: dropped
    assert U.resolve_offset(T0 + 5 * 86400 + 12 * H + 10800, runs) == (10800, "EVIDENCED_BRACKETED")
    agreeing = U.runs_of([(T0, 10800, False), (T0 + 86400, 10800, True)])
    assert len(agreeing) == 1                                                                 # a provisional point that agrees with its measured neighbour is kept
    assert U.runs_of([(T0, 10800, False)]) == []                                              # provisional evidence alone proves nothing


def test_r13_a_switch_right_after_the_last_measurement_is_not_extended_over():
    S = T0 + 5 * 86400                                                                        # spring-forward UTC+2 -> UTC+3 right after the last measurement
    runs = U.runs_of([(S - 86400, 7200), (S - H, 7200)])
    for k in range(0, 3 * H, 600):
        assert U.resolve_offset(S + k + 10800, runs)[0] is None                              # bars of the new offset never receive the old one
    assert U.resolve_offset(S - 4 * H + 7200, runs)[0] == 7200                               # bars more than 2 h before the newest measurement are fine


def test_r13_short_lived_measured_offsets_are_trusted_and_never_relabelled():
    D = 86400
    runs = U.runs_of([(T0 + k * H, 10800) for k in range(0, 24)] + [(T0 + D + k * H, 7200) for k in range(0, 48)] + [(T0 + 3 * D + k * H, 10800) for k in range(0, 24)])
    assert [r[0] for r in runs] == [10800, 7200, 10800]                                      # the 2-day offset run is kept (it was dropped as an "outlier" before)
    for k in range(0, 2 * D - 7200, 600):
        utc = T0 + D + 2 * H + k
        assert U.resolve_offset(utc + 7200, runs)[0] in (7200, None)                         # never the 10800 of the neighbouring runs
