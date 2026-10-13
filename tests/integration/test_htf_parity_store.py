"""Aggregated-from-M1 vs native MT5 HTF bars on the persisted store. Skipped (not PASS) when the store lacks the data."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "gateway"))
from xau_gateway.quality import htf_parity  # noqa: E402
from xau_gateway.storage import Store  # noqa: E402

CFG = ROOT / "configs" / "source.json"
STORE = ROOT / "data" / "store"
pytestmark = pytest.mark.skipif(not (CFG.exists() and (STORE / "manifest.sqlite").exists()), reason="no local store/config")


@pytest.mark.parametrize("tf", ["M5", "M15", "H1", "H4"])
def test_aggregate_equals_native(tf):
    server = json.loads(CFG.read_text())["expected"]["server"]
    r = htf_parity(Store(STORE), tf, "XAUUSD", server)
    if r["status"] == "INSUFFICIENT_DATA":
        pytest.skip(f"{tf}: insufficient data in store")
    assert r["status"] == "PASS" and r["mismatches"] == [] and r["compared"] > 100, r
