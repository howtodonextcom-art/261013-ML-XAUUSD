"""The heavy recompute runs in a separate process (GIL isolation): same result as in-process, failures are contained, the pool is recreated."""
import os
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/gateway"))
sys.path.insert(0, str(ROOT / "services/intelligence"))
sys.path.insert(0, str(ROOT / "tests/unit"))
pytestmark = pytest.mark.heavy_pool


@pytest.fixture()
def bars():
    from test_backtest import synth
    b = synth(n5=48 * 120)
    return {tf: b[tf] for tf in ("M15", "H1", "H4")}


@pytest.fixture(autouse=True)
def child_env(monkeypatch):
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join([str(ROOT / "services/gateway"), str(ROOT / "services/intelligence")]))   # spawned children do not inherit sys.path edits
    monkeypatch.delenv("XAU_HEAVY_INPROC", raising=False)
    from xau_gateway import app as appmod
    appmod._HEAVY["pool"] = None
    yield
    pool = appmod._HEAVY["pool"]
    if pool is not None:
        pool.shutdown(wait=True, cancel_futures=True)
    appmod._HEAVY["pool"] = None


def test_the_process_result_equals_the_in_process_result(bars):
    from xau_gateway import app as appmod
    from xau_gateway.intel_logic import compute_heavy, strict
    from xau_intel.backtest.engine import canon
    now = int(bars["M15"]["time"][-1]) + 900
    a = strict(appmod.run_heavy(bars, now))
    assert canon(a) == canon(strict(compute_heavy(bars, now)))
    assert appmod._HEAVY["pool"] is not None                                   # it really went through the worker process


def test_a_worker_that_dies_raises_and_the_pool_is_recreated(bars):
    from concurrent.futures.process import BrokenProcessPool
    from xau_gateway import app as appmod
    now = int(bars["M15"]["time"][-1]) + 900
    appmod.run_heavy(bars, now)
    pid = appmod._heavy_pool().submit(os.getpid).result(timeout=60)
    import signal
    os.kill(pid, signal.SIGTERM)                                               # kill the worker (TerminateProcess on Windows)
    import time
    time.sleep(0.5)
    with pytest.raises(Exception):
        appmod.run_heavy(bars, now)
    assert appmod._HEAVY["pool"] is None                                       # dropped: the next call starts a fresh worker
    assert appmod.run_heavy(bars, now)["evaluated_at"] == now


def test_bad_input_inside_the_worker_is_an_exception_not_a_hang(bars):
    from xau_gateway import app as appmod
    with pytest.raises(Exception):
        appmod.run_heavy({"M15": {"time": np.array([1, 2, 3])}}, 5)
    assert appmod.run_heavy(bars, int(bars["M15"]["time"][-1]) + 900)["intel_version"]
