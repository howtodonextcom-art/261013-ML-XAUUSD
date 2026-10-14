"""Review round 3: provenance must fail closed."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "intelligence"))
sys.path.insert(0, str(Path(__file__).parent))
from xau_intel.provenance import verify_provenance  # noqa: E402
from test_provenance import _case  # noqa: E402


def test_missing_or_empty_store_is_rejected_not_silently_skipped():
    meta, d, kw = _case()
    kw["store_bars"] = None
    ok, why = verify_provenance(meta, d, **kw)
    assert not ok and any("UNVERIFIED_FEED" in w for w in why)
    meta, d, kw = _case()
    kw["store_bars"] = {k: v[:0] for k, v in kw["store_bars"].items()}
    ok, why = verify_provenance(meta, d, **kw)
    assert not ok and any("UNVERIFIED_FEED" in w for w in why)


def test_unpinned_account_is_rejected():
    meta, d, kw = _case()
    kw["expected"] = {"server": "MetaQuotes-Demo"}
    ok, why = verify_provenance(meta, d, **kw)
    assert not ok and any("NO_PINNED_ACCOUNT_REF" in w for w in why)


def test_too_few_bars_for_the_late_zone_is_rejected():
    meta, d, kw = _case(n=2000)
    ok, why = verify_provenance(meta, d, **kw)
    assert not ok and any("TOO_FEW_BARS" in w for w in why)


def test_a_dump_dated_in_the_future_is_rejected():
    meta, d, kw = _case(now_utc=1800000000.0 - 1000)
    ok, why = verify_provenance(meta, d, **kw)
    assert not ok and any("DUMP_FROM_FUTURE" in w for w in why)


def test_a_mismatch_inside_the_late_zone_is_rejected_even_when_the_overall_fraction_is_high():
    meta, d, kw = _case(n=3200)
    kw["store_bars"]["close"][-3] += 0.5            # 1 bar of 3200 differs: overall 0.9997 >= 0.999, but it is inside the last 1000 bars
    ok, why = verify_provenance(meta, d, **kw)
    assert not ok and any("LATE_ZONE" in w for w in why)


def test_store_that_does_not_cover_the_late_zone_is_rejected():
    meta, d, kw = _case(n=3200)
    kw["store_bars"] = {k: v[:2000] for k, v in kw["store_bars"].items()}     # enough overlap overall (>= 500) but none of the last 1000
    ok, why = verify_provenance(meta, d, **kw)
    assert not ok and any("late zone" in w.lower() for w in why)
