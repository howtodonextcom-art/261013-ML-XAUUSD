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


def test_discarding_the_pool_kills_a_hung_worker(bars):
    import time
    from xau_gateway import app as appmod
    pool = appmod._heavy_pool()
    pool.submit(os.getpid).result(timeout=60)
    procs = list(pool._processes.values())
    pool.submit(time.sleep, 120)                                               # a hung task
    time.sleep(0.5)
    appmod._discard_pool()
    assert appmod._HEAVY["pool"] is None
    for p in procs:
        p.join(5)
        assert not p.is_alive(), "the hung worker survived the discard"


def test_an_orphaned_worker_ends_itself_when_the_gateway_process_dies_hard(tmp_path):
    """The parent creates the pool, prints the worker pid and is killed without cleanup (os._exit): the watchdog must end the worker within seconds."""
    import subprocess
    import time
    from xau_gateway.workers import pid_alive
    script = tmp_path / "parent.py"
    script.write_text(
        "import os, sys\n"
        f"sys.path[:0] = [r'{ROOT / 'services/gateway'}', r'{ROOT / 'services/intelligence'}']\n"
        "from xau_gateway import app as appmod\n"
        "if __name__ == '__main__':                      # spawn re-imports this script in the worker: the guard is required\n"
        "    pid = appmod._heavy_pool().submit(os.getpid).result(timeout=60)\n"
        "    print(pid, flush=True)\n"
        "    os._exit(0)\n", encoding="utf-8")
    out = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, timeout=120, env={**os.environ, "XAU_HEAVY_INPROC": ""})
    wpid = int(out.stdout.strip().splitlines()[-1])
    deadline = time.time() + 15
    while time.time() < deadline and pid_alive(wpid):
        time.sleep(0.5)
    assert not pid_alive(wpid), "the orphaned worker is still running 15 s after its parent died"


def test_pid_alive_is_true_for_this_process_and_false_for_nonsense():
    from xau_gateway.workers import pid_alive
    assert pid_alive(os.getpid()) and not pid_alive(0) and not pid_alive(999_999_999)
