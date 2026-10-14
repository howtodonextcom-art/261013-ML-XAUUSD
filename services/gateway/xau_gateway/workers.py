"""Helpers for the heavy-recompute worker process: liveness of a pid and the watchdog that ends an orphaned worker.

Kept tiny and import-light on purpose: a spawned worker imports this module (and nothing from the web application) before it starts working."""
from __future__ import annotations

import os
import threading
import time


def pid_alive(pid: int) -> bool:
    """True while a process with this pid exists (Windows: OpenProcess + WaitForSingleObject, never os.kill(pid, 0), which would terminate on Windows)."""
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x00100000, False, pid)           # SYNCHRONIZE
        if not h:
            return False
        try:
            return k.WaitForSingleObject(h, 0) == 0x102      # WAIT_TIMEOUT: still running
        finally:
            k.CloseHandle(h)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def worker_init(parent_pid: int, interval_s: float = 1.0) -> None:
    """Runs inside the worker: when the gateway process disappears (crash, hard kill) the worker ends itself instead of lingering as an orphan."""
    def watch():
        while True:
            time.sleep(interval_s)
            if not pid_alive(parent_pid):
                os._exit(0)
    threading.Thread(target=watch, daemon=True, name="parent-watchdog").start()
