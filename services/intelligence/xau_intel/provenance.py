"""Provenance of an MT5 indicator dump: a CSV is never trusted by its file name.

A dump is accepted only if it provably comes from the pinned MetaQuotes-Demo terminal for this symbol and timeframe, is fresh,
is internally consistent, and (when the local store holds bars) its OHLC equals the stored MT5 bars. The last check is independent of
what the metadata claims, so a CSV from another broker's terminal (for example FTMO) is rejected even if its metadata were forged.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

TF_SEC = {"M15": 900, "H1": 3600, "H4": 14400}
MIN_BARS = 2800   # the verdict uses the last 1000 bars; with >= 2800 bars the EMA200 seed error there is below 1e-8 of its initial value


def read_meta(path: Path) -> dict:
    out = {}
    for line in Path(path).read_text(encoding="utf-8", errors="ignore").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def _norm(p: str) -> str:
    return p.replace("/", "\\").rstrip("\\").lower()


def verify_provenance(meta: dict, d: dict, *, expected: dict, terminal_path: str, symbol: str, tf: str, now_utc: float,
                      max_age_s: float = 3600.0, store_bars: dict | None = None) -> tuple[bool, list[str]]:
    """Return (ok, reasons). `expected` is the pinned identity (server, account_ref) from configs/source.json."""
    why: list[str] = []
    if meta.get("schema") != "1":
        why.append("META_SCHEMA")
    if meta.get("symbol") != symbol:
        why.append(f"SYMBOL {meta.get('symbol')!r} != {symbol!r}")
    if meta.get("timeframe") != tf:
        why.append(f"TIMEFRAME {meta.get('timeframe')!r} != {tf!r}")
    if not expected.get("server"):
        why.append("NO_PINNED_SERVER")
    elif meta.get("server") != expected["server"]:
        why.append(f"SERVER {meta.get('server')!r} != {expected['server']!r}")
    if not expected.get("account_ref"):
        why.append("NO_PINNED_ACCOUNT_REF (fail closed: the account cannot be verified)")
    elif meta.get("account_ref") != expected["account_ref"]:
        why.append("ACCOUNT_REF differs from the pinned account")
    if _norm(meta.get("terminal_path", "")) != _norm(str(Path(terminal_path).parent)):
        why.append(f"TERMINAL_PATH {meta.get('terminal_path')!r} != {str(Path(terminal_path).parent)!r}")
    try:
        age = now_utc - float(meta["dump_utc"])
        if age > max_age_s:
            why.append(f"STALE_DUMP age {age:.0f}s > {max_age_s:.0f}s")
        elif age < -300:
            why.append(f"DUMP_FROM_FUTURE by {-age:.0f}s")
    except (KeyError, ValueError):
        why.append("DUMP_UTC missing")
    times = np.asarray(d["time"], dtype=float)
    sec = TF_SEC.get(tf)
    if len(times) == 0 or (sec and np.any(times % sec != 0)) or np.any(np.diff(times) <= 0):
        why.append("TIME_GRID_OR_ORDER")
    if meta.get("last_time") and len(times) and float(meta["last_time"]) != times[-1]:
        why.append("LAST_TIME differs between meta and CSV")
    if meta.get("bars") and int(meta["bars"]) != len(times):
        why.append("BAR_COUNT differs between meta and CSV")
    if len(times) < MIN_BARS:
        why.append(f"TOO_FEW_BARS {len(times)} < {MIN_BARS} (the late-zone verdict needs this many bars for the seeds to decay)")
    if store_bars is None or len(store_bars.get("time", [])) == 0:
        why.append("UNVERIFIED_FEED: no stored MT5 bars to cross-check the CSV against (fail closed)")
    else:
        st_t = np.asarray(store_bars["time"], dtype=float)
        common, i_csv, i_st = np.intersect1d(times, st_t, return_indices=True)
        if len(common) < 500:
            why.append(f"STORE_OVERLAP only {len(common)} bars (need >= 500 to cross-check the feed)")
        else:
            same = np.ones(len(common), dtype=bool)
            for k in ("open", "high", "low", "close"):
                same &= np.abs(np.asarray(d[k])[i_csv] - np.asarray(store_bars[k], dtype=float)[i_st]) < 1e-6
            frac = float(same.mean())
            late_mask = np.isin(common, times[-1000:])
            if int(late_mask.sum()) < 900:
                why.append(f"STORE_OVERLAP does not cover the late zone ({int(late_mask.sum())} of the last 1000 bars)")
            elif not bool(same[late_mask].all()):
                why.append("STORE_MISMATCH_LATE_ZONE: a bar in the last 1000 differs from the stored MetaQuotes-Demo bars")
            if frac < 0.999:
                why.append(f"STORE_MISMATCH only {frac:.4f} of {len(common)} overlapping bars equal the stored MetaQuotes-Demo bars")
    return (not why), why
