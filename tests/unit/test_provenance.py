import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "intelligence"))
sys.path.insert(0, str(Path(__file__).parent))
from xau_intel.provenance import TF_SEC, read_meta, verify_provenance  # noqa: E402
from test_intel import walk  # noqa: E402


def _case(tf="H1", n=3000, **over):
    sec = TF_SEC[tf]
    t0 = (1_700_006_400 // sec) * sec
    t, o, h, l, c = walk(n, seed=2, vol=1.0, t0=t0, sec=sec)
    d = {"time": t.astype(float), "open": o, "high": h, "low": l, "close": c}
    meta = {"schema": "1", "symbol": "XAUUSD", "timeframe": tf, "server": "MetaQuotes-Demo", "account_ref": "abcd1234",
            "terminal_path": r"C:\Program Files\MetaTrader 5", "bars": str(n), "last_time": str(int(t[-1])), "dump_utc": "1800000000"}
    expected = {"server": "MetaQuotes-Demo", "account_ref": "abcd1234"}
    store = {"time": t, "open": o.copy(), "high": h.copy(), "low": l.copy(), "close": c.copy()}
    kw = dict(expected=expected, terminal_path=r"C:\Program Files\MetaTrader 5\terminal64.exe", symbol="XAUUSD", tf=tf,
              now_utc=1800000100.0, store_bars=store)
    meta.update(over.pop("meta", {}))
    kw.update(over)
    return meta, d, kw


def test_accepts_a_genuine_fresh_dump():
    meta, d, kw = _case()
    assert verify_provenance(meta, d, **kw) == (True, [])


@pytest.mark.parametrize("override,needle", [
    ({"meta": {"server": "FTMO-Server"}}, "SERVER"),
    ({"meta": {"account_ref": "deadbeef"}}, "ACCOUNT_REF"),
    ({"meta": {"terminal_path": r"C:\Program Files\FTMO Global Markets MT5 Terminal"}}, "TERMINAL_PATH"),
    ({"meta": {"symbol": "XAUEUR"}}, "SYMBOL"),
    ({"meta": {"timeframe": "H4"}}, "TIMEFRAME"),
    ({"now_utc": 1800000000.0 + 7200}, "STALE_DUMP"),
    ({"meta": {"bars": "2999"}}, "BAR_COUNT"),
    ({"meta": {"schema": "2"}}, "META_SCHEMA"),
])
def test_rejects(override, needle):
    meta, d, kw = _case(**override)
    ok, why = verify_provenance(meta, d, **kw)
    assert not ok and any(needle in w for w in why), why


def test_rejects_prices_that_do_not_match_the_stored_feed_even_if_the_metadata_lies():
    meta, d, kw = _case()
    kw["store_bars"]["close"] = kw["store_bars"]["close"] + 0.5          # same bars but another broker's prices
    ok, why = verify_provenance(meta, d, **kw)
    assert not ok and any("STORE_MISMATCH" in w for w in why)


def test_requires_enough_store_overlap_and_a_valid_time_grid():
    meta, d, kw = _case()
    kw["store_bars"] = {k: v[:100] for k, v in kw["store_bars"].items()}
    assert any("STORE_OVERLAP" in w for w in verify_provenance(meta, d, **kw)[1])
    meta, d, kw = _case()
    d["time"] = d["time"] + 1.0
    assert any("TIME_GRID" in w for w in verify_provenance(meta, d, **kw)[1])


def test_requires_a_pinned_server():
    meta, d, kw = _case()
    kw["expected"] = {}
    assert any("NO_PINNED_SERVER" in w for w in verify_provenance(meta, d, **kw)[1])


def test_read_meta_parses_key_value_lines(tmp_path):
    p = tmp_path / "x.meta"
    p.write_text("schema=1\nserver=MetaQuotes-Demo\nterminal_path=C:\\Program Files\\MetaTrader 5\n", encoding="utf-8")
    m = read_meta(p)
    assert m["schema"] == "1" and m["server"] == "MetaQuotes-Demo" and m["terminal_path"].endswith("MetaTrader 5")
