"""UTC-keyed M1 bar store (Level 5.5 P0). Derived, additive and fail-closed.

The legacy `bars_m1` dataset is keyed by BROKER SERVER time. Server time follows the broker's daylight-saving rules, so a server stamp alone does not identify one instant:
at a fall-back the same stamp occurs twice, at a spring-forward an hour of stamps never occurs. This module derives `bars_m1_utc`:

* one row per UTC instant (`utc_time` unique), with the ORIGINAL `server_time`, the `utc_offset_s` that was applied, `offset_status`/`offset_origin` (provenance) and the
  legacy dataset identity. The legacy chunks are never touched (the new kind is added next to them; superseded copies stay on disk).
* the offset of a bar is NEVER guessed. It must be bracketed by MEASURED evidence (`offset_evidence`: gateway HIGH-confidence measurements and the offset recorded at each
  capture-session start) of the SAME offset. A bar whose candidate instants fall between two different offsets (a switch happened somewhere there), or that fits two
  offsets (the repeated fall-back hour), or that is far from any evidence, is NOT written. No candle is invented for a missing instant.
* migration is idempotent (identical content -> no new file), keeps a backup of the manifest first, and `rollback_utc` removes only the derived kind from the manifest
  (files moved aside, never deleted).
"""
from __future__ import annotations

import calendar
import json
import sqlite3
import time
from pathlib import Path

import numpy as np
import pyarrow as pa

from .storage import DATASET_VERSION, Store

KIND = "bars_m1_utc"
HIST_BARS = "mt5_hist_bars"
NEAR_S = 0                        # no extension beyond the first/last evidence: a broker switch can sit right after the last measurement (review round 13); bars between measurements are bracketed
MIN_CLOSURE_BARS = 30             # shorter holes are never candidates for a market closure
MIN_CLOSURE_RECURRENCE = 3        # a closure signature must have been seen at least this often

UTC_SCHEMA = pa.schema([
    ("source_id", pa.string()), ("server", pa.string()), ("symbol", pa.string()),
    ("utc_time", pa.int64()), ("server_time", pa.int64()), ("utc_offset_s", pa.int32()), ("offset_status", pa.string()), ("offset_origin", pa.string()),
    ("open", pa.float64()), ("high", pa.float64()), ("low", pa.float64()), ("close", pa.float64()),
    ("tick_volume", pa.int64()), ("spread", pa.int32()), ("legacy_kind", pa.string()), ("dataset_version", pa.string()),
])


# ---------------------------------------------------------------- evidence
def ensure_tables(store: Store) -> None:
    with store._lock, store._db() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS offset_evidence(
            id INTEGER PRIMARY KEY, server TEXT, observed_utc INTEGER, offset_s INTEGER, confidence TEXT, origin TEXT, session_id TEXT DEFAULT '',
            UNIQUE(server, observed_utc, origin))""")


def add_offset_evidence(store: Store, server: str, observed_utc: int, offset_s: int, confidence: str, origin: str, session_id: str = "") -> None:
    ensure_tables(store)
    with store._lock, store._db() as db:
        db.execute("INSERT OR IGNORE INTO offset_evidence(server, observed_utc, offset_s, confidence, origin, session_id) VALUES(?,?,?,?,?,?)",
                   (server, int(observed_utc), int(offset_s), confidence, origin, session_id))


def seed_from_session_meta(store: Store, server: str) -> int:
    """The offset recorded at each capture-session start (meta `session:<id>:server_utc_offset_s`); the session id embeds the UTC start time. These points are PROVISIONAL
    (taken at connect, before the estimator has measured anything): they may bracket bars between two agreeing points but never extend evidence beyond their own time."""
    ensure_tables(store)
    n = 0
    with store._db() as db:
        rows = db.execute("SELECT k, v FROM meta WHERE k LIKE 'session:%:server_utc_offset_s'").fetchall()
        sess = {r[0]: r[1] for r in db.execute("SELECT session_id, server FROM sessions")}
    for k, v in rows:
        sid = k.split(":")[1]
        if v in (None, "", "None") or sess.get(sid) not in (server, None):
            continue
        try:
            obs = calendar.timegm(time.strptime(sid.split("-")[0], "%Y%m%dT%H%M%SZ"))             # UTC, independent of the PC time zone
            off = int(v)
        except (ValueError, IndexError):
            continue
        add_offset_evidence(store, server, obs, off, "SESSION_CONNECT", "session_meta", sid)
        n += 1
    return n


def load_evidence(store: Store, server: str) -> list[tuple[int, int, bool]]:
    """(observed_utc, offset_s, high). `high` = measured by the gateway with HIGH confidence and a consistent recent window; only those may extend the evidence in time."""
    ensure_tables(store)
    with store._db() as db:
        rows = db.execute("SELECT observed_utc, offset_s, origin FROM offset_evidence WHERE server=? ORDER BY observed_utc", (server,)).fetchall()
    return [(int(a), int(b), o == "gateway_live") for a, b, o in rows]


MAX_BRIDGE_S = 30 * 86400         # same-offset evidence further apart than this does not bracket anything between (a season may have changed in between)


def runs_of(evidence: list[tuple]) -> list[tuple[int, int, int, bool, bool]]:
    """(offset, first_observed_utc, last_observed_utc, first_is_high, last_is_high) of consecutive evidence with the SAME offset. 2-tuples (obs, offset) count as high.
    A PROVISIONAL point (session connect, taken before the estimator measured anything) is used only if every HIGH point next to it (the nearest before and the nearest after)
    carries the same offset and at least one exists: provisional points can fill the space between agreeing measurements but never contradict or replace them (review round 13).
    A same-offset run is split at gaps > MAX_BRIDGE_S."""
    ev = sorted(((int(e[0]), int(e[1]), True if len(e) < 3 else bool(e[2])) for e in evidence))
    highs = [e for e in ev if e[2]]
    keep = []
    for obs, off, high in ev:
        if not high:
            before = [h for h in highs if h[0] <= obs]
            after = [h for h in highs if h[0] >= obs]
            neighbours = ([before[-1]] if before else []) + ([after[0]] if after else [])
            if not neighbours or any(h[1] != off for h in neighbours):
                continue
        keep.append((obs, off, high))
    out: list[list] = []
    for obs, off, high in keep:
        if out and out[-1][0] == off and obs - out[-1][2] <= MAX_BRIDGE_S:
            out[-1][2], out[-1][4] = obs, high
        else:
            out.append([off, obs, obs, high, high])
    return [tuple(r) for r in out]


def resolve_offset(server_time: int, runs: list, near_s: int = NEAR_S) -> tuple[int | None, str]:
    """(offset, status). offset is None (the bar must not be converted) unless EXACTLY ONE evidenced offset explains the server stamp AND the stamp cannot belong to the
    unmeasured interval around a switch between two different offsets (every stamp that a bar inside that interval could carry is excluded, whichever offset it truly had)."""
    runs = [tuple(r) + (True, True) if len(r) == 3 else tuple(r) for r in runs]
    last = len(runs) - 1
    cands = []
    for i, (off, a, b, fh, lh) in enumerate(runs):
        utc = server_time - off
        if a <= utc <= b:
            cands.append((off, "EVIDENCED_BRACKETED"))
        elif i == 0 and utc < a and a - utc <= near_s and fh:
            cands.append((off, "EVIDENCED_NEAR_BEFORE"))
        elif i == last and utc > b and utc - b <= near_s and lh:
            cands.append((off, "EVIDENCED_NEAR_AFTER"))
    uncertain = False
    for (o1, _, b1, _, _), (o2, a2, _, _, _) in zip(runs, runs[1:]):
        if o1 != o2 and b1 + min(o1, o2) <= server_time <= a2 + max(o1, o2):
            uncertain = True
    if uncertain:
        return None, "AMBIGUOUS_DST_OVERLAP" if len(cands) > 1 else "UNKNOWN_SWITCH_GAP"
    if len(cands) == 1:
        return cands[0]
    if len(cands) > 1:
        return None, "AMBIGUOUS_DST_OVERLAP"
    return None, "UNKNOWN_NO_EVIDENCE"


# ---------------------------------------------------------------- closures
def _wd(ts: int) -> int:
    return int((ts // 86400 + 3) % 7)               # Monday = 0 (the epoch day was a Thursday); server stamps are read as naive clock time


def _mod(ts: int) -> int:
    return int((ts % 86400) // 60)


def hole_signature(last_before_server: int, first_after_server: int) -> tuple[int, int, int, int, int]:
    """(long, start weekday, start minute-of-day, end weekday, end minute-of-day) in SERVER clock terms. A daily break (< 24 h) recurs every weekday, so its weekday fields
    are -1; a weekend-type hole (>= 24 h) recurs weekly, so it keeps them."""
    s = last_before_server + 60
    if first_after_server - s >= 86400:
        return (1, _wd(s), _mod(s), _wd(first_after_server), _mod(first_after_server))
    return (0, -1, _mod(s), -1, _mod(first_after_server))


def closure_signatures(server_times: np.ndarray, min_bars: int = MIN_CLOSURE_BARS, min_count: int = MIN_CLOSURE_RECURRENCE) -> list[list[int]]:
    """Recurring closures learned from the data in SERVER clock terms (the broker's schedule follows the server clock, not UTC): holes of >= min_bars missing M1 bars whose
    start and end (minute-of-day; plus weekday for weekend-type holes) repeat at least `min_count` times. One-off holes (a feed outage) never become closures."""
    t = np.sort(np.unique(np.asarray(server_times, dtype=np.int64)))
    d = np.diff(t) // 60 - 1
    cnt: dict[tuple, int] = {}
    for k in np.where(d >= min_bars)[0]:
        sig = hole_signature(int(t[k]), int(t[k + 1]))
        cnt[sig] = cnt.get(sig, 0) + 1
    return sorted([list(s) for s, c in cnt.items() if c >= min_count])


def closure_windows(m1: dict, signatures: list[list[int]], min_bars: int = MIN_CLOSURE_BARS) -> list[tuple[int, int]]:
    """UTC windows [first missing bar, last missing bar] of holes in `m1` (needs `time` = UTC and `server_time`) that match a recurring closure signature."""
    sigs = {tuple(s) for s in signatures}
    t, ts = np.asarray(m1["time"], dtype=np.int64), np.asarray(m1["server_time"], dtype=np.int64)
    out = []
    for k in np.where(np.diff(t) // 60 - 1 >= min_bars)[0]:
        if hole_signature(int(ts[k]), int(ts[k + 1])) in sigs:
            out.append((int(t[k]) + 60, int(t[k + 1]) - 60))
    return out


# ---------------------------------------------------------------- migration
def _backup_manifest(store: Store, keep: int = 5) -> Path:
    d = store.root / "backup"
    d.mkdir(exist_ok=True)
    first = d / "manifest-utcmig-FIRST.sqlite"                            # the pre-first-migration state is kept for ever (the rotating copies below keep only the newest)
    dst = first if not first.exists() else d / f"manifest-utcmig-{time.strftime('%Y%m%dT%H%M%S')}-{int(time.time() * 1000) % 1000:03d}.sqlite"
    src = sqlite3.connect(store.db_path)
    try:
        tmp = dst.with_suffix(".tmp")
        out = sqlite3.connect(tmp)
        try:
            src.backup(out)
        finally:
            out.close()
        tmp.replace(dst)                                              # a crash mid-copy never leaves a partial backup under the final name
    finally:
        src.close()
    old = sorted(d.glob("manifest-utcmig-*.sqlite"))
    for p in old[:-keep]:
        p.unlink()
    return dst


def migrate(store: Store, server: str, symbol: str, source_id: str = HIST_BARS, backup: bool = True) -> dict:
    """Derive `bars_m1_utc` from the legacy dataset. Idempotent. Returns a report (also stored in meta)."""
    backup_path = str(_backup_manifest(store)) if backup else None      # BEFORE anything is written (pristine FIRST copy)
    ensure_tables(store)
    seeded = seed_from_session_meta(store, server)
    t = store.read_table("bars_m1", source_id=source_id, server=server, symbol=symbol)
    report = {"server": server, "symbol": symbol, "seeded_evidence": seeded, "legacy_rows": 0, "written_rows": 0, "excluded": {}, "chunks": {}, "backup": backup_path}
    if t.num_rows == 0:
        return report
    st = np.asarray(t["time"]).astype(np.int64)
    order = np.argsort(st, kind="stable")
    cols = {k: np.asarray(t[k])[order] for k in ("time", "open", "high", "low", "close", "tick_volume", "spread")}
    uniq_t, first = np.unique(cols["time"], return_index=True)             # the legacy key is the server stamp: duplicates (should not exist) keep the first row
    cols = {k: v[first] for k, v in cols.items()}
    report["legacy_rows"] = int(len(uniq_t))
    store.set_meta(f"utc_closure_signatures:{server}:{symbol}", json.dumps(closure_signatures(cols["time"])))
    runs = runs_of(load_evidence(store, server))
    rows_by_month: dict[str, list[int]] = {}
    utc = np.zeros(len(uniq_t), dtype=np.int64)
    offs = np.zeros(len(uniq_t), dtype=np.int32)
    stat: list[str] = [""] * len(uniq_t)
    for i, ts in enumerate(cols["time"]):
        off, status = resolve_offset(int(ts), runs)
        if off is None:
            report["excluded"][status] = report["excluded"].get(status, 0) + 1
            continue
        utc[i], offs[i], stat[i] = int(ts) - off, off, status
        rows_by_month.setdefault(time.strftime("%Y%m", time.gmtime(int(ts) - off)), []).append(i)
    allu = [utc[i] for ix in rows_by_month.values() for i in ix]
    if len(allu) != len(set(allu)):
        raise RuntimeError("UTC collision during migration: refusing to write (two server stamps map to one instant)")
    plan = []
    for month, ix in sorted(rows_by_month.items()):
        ix = sorted(ix, key=lambda i: utc[i])
        rows = {"source_id": [source_id] * len(ix), "server": [server] * len(ix), "symbol": [symbol] * len(ix), "utc_time": [int(utc[i]) for i in ix],
                "server_time": [int(cols["time"][i]) for i in ix], "utc_offset_s": [int(offs[i]) for i in ix], "offset_status": [stat[i] for i in ix],
                "offset_origin": ["offset_evidence"] * len(ix), "open": [float(cols["open"][i]) for i in ix], "high": [float(cols["high"][i]) for i in ix],
                "low": [float(cols["low"][i]) for i in ix], "close": [float(cols["close"][i]) for i in ix], "tick_volume": [int(cols["tick_volume"][i]) for i in ix],
                "spread": [int(cols["spread"][i]) for i in ix], "legacy_kind": ["bars_m1"] * len(ix), "dataset_version": [DATASET_VERSION] * len(ix)}
        plan.append((month, rows))
    wanted = {f"utc-{m}" for m, _ in plan}
    with store._lock, store._db() as db:                                  # a month that no longer has any provable row must not stay active (review round 12, H4)
        for (chunk,) in db.execute("SELECT DISTINCT chunk FROM files WHERE kind=? AND source_id=? AND server=? AND symbol=? AND superseded=0", (KIND, source_id, server, symbol)).fetchall():
            if chunk not in wanted:
                db.execute("UPDATE files SET superseded=1 WHERE kind=? AND source_id=? AND server=? AND symbol=? AND chunk=?", (KIND, source_id, server, symbol, chunk))
                report["chunks"][chunk] = "superseded_empty"
    for month, rows in plan:
        r = store.write_chunk(KIND, UTC_SCHEMA, rows, source_id=source_id, server=server, symbol=symbol, chunk=f"utc-{month}", key_col="utc_time", partition=f"month={month}")
        report["chunks"][month] = r["status"]
        report["written_rows"] += len(rows["utc_time"])
    store.set_meta(f"utc_migration_report:{server}:{symbol}", json.dumps(report, sort_keys=True))
    return report


def rollback_utc(store: Store) -> dict:
    """Remove ONLY the derived kind from the manifest (its files are moved aside, never deleted). The legacy dataset is untouched."""
    d = store.root / KIND
    aside = None
    with store._lock, store._db() as db:
        n = db.execute("DELETE FROM files WHERE kind=?", (KIND,)).rowcount
    if d.exists():
        aside = store.root / f"{KIND}.rolledback-{time.strftime('%Y%m%dT%H%M%S')}"
        d.rename(aside)
    return {"manifest_rows_removed": n, "moved_to": None if aside is None else str(aside)}


def read_utc_bars(store: Store, server: str, symbol: str, source_id: str = HIST_BARS) -> dict:
    """Sorted arrays keyed by UTC. Raises if two rows share an instant (a corrupted derivation must never reach the evaluator)."""
    t = store.read_table(KIND, source_id=source_id, server=server, symbol=symbol)
    if t.num_rows == 0:
        return {k: np.array([]) for k in ("time", "server_time", "offset", "open", "high", "low", "close", "spread")}
    u = np.asarray(t["utc_time"]).astype(np.int64)
    o = np.argsort(u, kind="stable")
    g = lambda k: np.asarray(t[k])[o]  # noqa: E731
    out = {"time": u[o], "server_time": g("server_time").astype(np.int64), "offset": g("utc_offset_s").astype(np.int64), "open": g("open"), "high": g("high"),
           "low": g("low"), "close": g("close"), "spread": g("spread").astype(float)}
    if len(out["time"]) != len(np.unique(out["time"])):
        raise RuntimeError("bars_m1_utc holds duplicate UTC instants")
    return out
