"""UTC store versus the LIVE candle path around a broker DST switch (Level 5.6 verification).

Synthetic ticks carry an independent truth: price = 4000 + (true_utc - T0) / 60. The live CandleEngine buckets them in SERVER time (as it does on the gateway); the closed
M1 candles are written as the legacy dataset; the UTC store is derived with hourly measured offset evidence. Every converted bar is then compared with the truth encoded in
its own price. Real broker DST remains NOT TESTED: this test proves the logic on synthetic data only."""
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in ("services/gateway", "services/intelligence"):
    sys.path.insert(0, str(ROOT / p))
from xau_gateway import utcstore as U  # noqa: E402
from xau_gateway.candles import CandleEngine  # noqa: E402
from xau_gateway.storage import BAR_SCHEMA, Store  # noqa: E402

SERVER, SYMBOL, SRC = "Live-DST-Test", "XAUUSD", "mt5_hist_bars"
T0 = 1_790_000_000 - (1_790_000_000 % 86400)
H = 3600


@pytest.mark.parametrize("before,after", [(10800, 7200), (7200, 10800)], ids=["fall-back", "spring-forward"])
def test_every_converted_bar_matches_the_truth_encoded_in_its_price_and_the_switch_hours_are_excluded(tmp_path, before, after):
    sw = T0 + 36 * H                                                                         # true UTC instant of the broker switch
    off = lambda u: before if u < sw else after                                               # noqa: E731
    eng = CandleEngine(timeframes=("M1",), max_closed=100_000)
    for u in range(T0, T0 + 3 * 86400, 20):                                                   # ticks arrive in true chronological order
        px = 4000 + (u - T0) / 60.0
        eng.on_tick((u + off(u)) * 1000, px, px + 0.3)                                        # stamped with SERVER time, exactly like MT5
    closed = list(eng.closed["M1"])
    assert closed, "the live engine produced no closed bars"
    by_server = {}
    for c in closed:                                                                          # the legacy dataset is keyed by server stamp (one row per stamp)
        by_server[int(c.t)] = c
    store = Store(tmp_path / "s")
    ts = sorted(by_server)
    rows = {"source_id": [SRC] * len(ts), "server": [SERVER] * len(ts), "symbol": [SYMBOL] * len(ts), "tf": ["M1"] * len(ts), "time": ts,
            "open": [by_server[t].o for t in ts], "high": [by_server[t].h for t in ts], "low": [by_server[t].l for t in ts], "close": [by_server[t].c for t in ts],
            "tick_volume": [by_server[t].tick_volume for t in ts], "spread": [30] * len(ts), "real_volume": [0] * len(ts), "dataset_version": ["t"] * len(ts)}
    store.write_chunk("bars_m1", BAR_SCHEMA, rows, source_id=SRC, server=SERVER, symbol=SYMBOL, chunk="live-1", key_col="time", partition="m")
    for k in range(0, 3 * 24):                                                                # hourly measured evidence, as the gateway records it (HIGH + fresh)
        u = T0 + k * H + 5
        U.add_offset_evidence(store, SERVER, u, off(u), "HIGH", "gateway_live")
    rep = U.migrate(store, SERVER, SYMBOL)
    bars = U.read_utc_bars(store, SERVER, SYMBOL)
    assert len(bars["time"]) > 0 and len(np.unique(bars["time"])) == len(bars["time"])
    truth_utc = T0 + np.rint((bars["open"] - 4000) * 60).astype(np.int64)                     # the bar's OWN price says which true minute it came from
    bar_floor = bars["time"] - (bars["time"] % 60)
    assert np.all(np.abs(truth_utc - bar_floor) <= 60), "a converted bar disagrees with the truth encoded in its price (wrong offset applied)"
    gap_lo, gap_hi = sw - H + 5, sw + 5                                                       # the measured interval between the last old and the first new evidence
    assert not np.any((bars["time"] > gap_lo) & (bars["time"] < gap_hi)), "a bar inside the unmeasured switch interval was converted"
    assert sum(rep["excluded"].values()) >= 60                                                # at least the hour between the two measurements is excluded
    assert np.any(bars["time"] <= gap_lo) and np.any(bars["time"] >= gap_hi)                  # bars on BOTH sides are proven and kept
    assert np.all(bars["offset"][bars["time"] <= gap_lo] == before) and np.all(bars["offset"][bars["time"] >= gap_hi] == after)
    assert rep["excluded"], "nothing was excluded around the switch"
    assert int(np.sum(bars["server_time"] - bars["time"] != bars["offset"])) == 0             # server stamp and offset reproduce the UTC key
    assert len(closed) <= len(ts) + 3600 // 60 + 1                                            # (the live engine itself may have merged the repeated hour: it never creates a bar)
