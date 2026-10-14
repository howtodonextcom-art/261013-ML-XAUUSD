"""Backend data behind the chart layers: EMA endpoint (closed bars only), zones in the heavy output, research status, V2 section in the payload contract."""
import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in ("services/gateway", "services/intelligence", "tests/unit"):
    sys.path.insert(0, str(ROOT / p))
import test_m1_entry_v2 as T  # noqa: E402
from xau_gateway.intel_logic import compute_heavy  # noqa: E402
from xau_intel.indicators import ema  # noqa: E402


@pytest.fixture()
def seeded():
    from fastapi.testclient import TestClient
    from xau_gateway import app as appmod
    from xau_gateway.candles import Candle
    mk = T.synth_market(n1=60 * 24 * 6)
    appmod.S.engine.closed = {tf: [] for tf in ("M1", "M5", "M15", "H1", "H4")}
    appmod.S.engine.history = {tf: [Candle(tf, int(t), float(o), float(h), float(l), float(c), 1, state="CLOSED", source="MT5_HISTORY", completeness="HISTORICAL")
                                    for t, o, h, l, c in zip(b["time"], b["open"], b["high"], b["low"], b["close"])] for tf, b in mk.items()}
    appmod.S.engine.open = {}
    appmod._IND_CACHE.clear()
    yield mk, TestClient(appmod.app, base_url="http://127.0.0.1:8765", client=("127.0.0.1", 50000))
    appmod.S.engine.history = {}
    appmod._IND_CACHE.clear()


def test_ema_endpoint_returns_the_analysis_ema_of_closed_bars_only(seeded):
    mk, c = seeded
    r = c.get("/api/indicators/M15?limit=300")
    assert r.status_code == 200
    d = r.json()
    b = mk["M15"]
    assert d["tf"] == "M15" and len(d["time"]) == 300 and d["time"] == [int(x) for x in b["time"][-300:]]
    for p in (20, 50, 200):
        want = ema(b["close"], p)[-300:]
        got = np.array([np.nan if x is None else x for x in d[f"ema{p}"]])
        assert np.allclose(got, want, equal_nan=True, atol=1e-4)
    assert d["time"][-1] == int(b["time"][-1])                                   # the last published point is the last CLOSED bar


def test_the_ema_endpoint_never_includes_the_forming_bar(seeded):
    from xau_gateway import app as appmod
    from xau_gateway.candles import Candle
    mk, c = seeded
    last_t = int(mk["M1"]["time"][-1])
    appmod.S.engine.open = {"M1": Candle("M1", last_t + 60, 1.0, 1.0, 1.0, 9999.0, 1, state="OPEN")}      # a forming bar with an absurd close
    d = c.get("/api/indicators/M1?limit=50").json()
    assert d["time"][-1] == last_t and all(x is None or x < 5000 for x in d["ema20"])


def test_ema_endpoint_validates_and_caps(seeded):
    mk, c = seeded
    assert c.get("/api/indicators/D1").status_code == 404
    assert len(c.get("/api/indicators/H1?limit=999999").json()["time"]) <= 2000
    assert len(c.get("/api/indicators/H1?limit=0").json()["time"]) == 1
    h4 = c.get("/api/indicators/M15?limit=2000").json()                                  # 576 bars: the first 199 EMA200 values are not valid yet
    assert h4["ema200"][0] is None and any(x is not None for x in h4["ema200"])      # invalid warm-up is null, never a made-up number
    json.dumps(h4, allow_nan=False)


def test_zones_in_the_heavy_output_are_known_causal_classified_and_sorted_by_distance():
    mk = T.synth_market(n1=60 * 24 * 14)
    bars = {tf: mk[tf] for tf in ("M15", "H1", "H4")}
    now = int(mk["M15"]["time"][-1]) + 900
    h = compute_heavy(bars, now)
    z = h["zones"]
    assert 0 < len(z) <= 6
    px = float(mk["M15"]["close"][-1])
    assert all(x["known_at"] <= now and x["low"] <= x["center"] <= x["high"] and x["touches"] >= 2 for x in z)
    assert [abs(x["center"] - px) for x in z] == sorted(abs(x["center"] - px) for x in z)
    for x in z:
        assert x["side"] == ("SUPPORT" if x["high"] <= px else "RESISTANCE" if x["low"] >= px else "AT_PRICE")
    # causality: the zones at an earlier time do not use later swings
    cut = int(mk["M15"]["time"][int(len(mk["M15"]["time"]) * 0.7)]) + 900
    early = compute_heavy({tf: mk[tf] for tf in ("M15", "H1", "H4")}, cut)["zones"]
    assert all(x["known_at"] <= cut for x in early)
    json.dumps(early, allow_nan=False)


def test_research_status_endpoint_reports_the_frozen_conclusions_without_secrets(seeded):
    mk, c = seeded
    r = c.get("/api/research").json()
    assert r["v1_backtest"]["verdict"] == "INSUFFICIENT_EVIDENCE" and r["v1_backtest"]["holdout"] == "SEALED"
    assert r["ml_shadow"]["verdict"] == "NO_EVIDENCE_OF_PREDICTIVE_SKILL" and r["ml_shadow"]["feeds_decision"] is False
    assert r["m1_entry_v2"]["performance_claim"] == "NONE" and r["mt5_live"] == {"mode_ab": "LIVE_AB_NOT_TESTED", "indicator_parity": "PARITY_NOT_TESTED"}
    assert "not a profitable trading system" in r["release"]
    blob = json.dumps(r).lower()
    assert "token" not in blob and "equity" not in blob and "account" not in blob


def test_the_new_endpoints_require_authentication():
    from fastapi.testclient import TestClient
    import os
    from xau_gateway.app import app
    os.environ["XAU_AUTH"] = "on"
    try:
        c = TestClient(app, base_url="http://127.0.0.1:8765", client=("127.0.0.1", 50000))
        assert c.get("/api/indicators/M1").status_code == 401 and c.get("/api/research").status_code == 401
    finally:
        os.environ["XAU_AUTH"] = "off"
