"""Canonical storage: partitioned Parquet (raw ticks / M1 bars) + SQLite WAL manifest.

Rules: raw data is never deleted or rewritten in place; files are written atomically (tmp -> rename) with sha256 and
row counts recorded in the manifest; if a chunk is re-fetched and differs, the new file is added and the old one is
marked superseded (kept on disk). Re-running a backfill with identical content is a no-op (idempotent).
"""
from __future__ import annotations

import contextlib
import hashlib
import sqlite3
import threading
import time
import uuid
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

SCHEMA_VERSION = 1
DATASET_VERSION = "ds-0.1"

TICK_SCHEMA = pa.schema([
    ("source_id", pa.string()), ("terminal_ref", pa.string()), ("server", pa.string()), ("symbol", pa.string()),
    ("time_msc", pa.int64()), ("bid", pa.float64()), ("ask", pa.float64()), ("last", pa.float64()),
    ("volume", pa.int64()), ("flags", pa.int32()), ("received_at_ns", pa.int64()), ("quality_flags", pa.string()),
    ("dataset_version", pa.string()),
])
BAR_SCHEMA = pa.schema([
    ("source_id", pa.string()), ("server", pa.string()), ("symbol", pa.string()), ("tf", pa.string()),
    ("time", pa.int64()), ("open", pa.float64()), ("high", pa.float64()), ("low", pa.float64()),
    ("close", pa.float64()), ("tick_volume", pa.int64()), ("spread", pa.int32()), ("real_volume", pa.int64()),
    ("dataset_version", pa.string()),
])


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


class Store:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "manifest.sqlite"
        self._lock = threading.Lock()
        with self._db() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
            CREATE TABLE IF NOT EXISTS files(
              id INTEGER PRIMARY KEY, kind TEXT, source_id TEXT, server TEXT, symbol TEXT, chunk TEXT,
              path TEXT UNIQUE, rows INTEGER, min_key INTEGER, max_key INTEGER, sha256 TEXT,
              schema_version INTEGER, dataset_version TEXT, created_utc TEXT, superseded INTEGER DEFAULT 0,
              quality TEXT DEFAULT '');
            CREATE INDEX IF NOT EXISTS ix_files_chunk ON files(kind, source_id, symbol, chunk, superseded);
            CREATE TABLE IF NOT EXISTS quarantine(
              id INTEGER PRIMARY KEY, kind TEXT, key INTEGER, reason TEXT, detail TEXT, created_utc TEXT);
            CREATE TABLE IF NOT EXISTS checkpoints(name TEXT PRIMARY KEY, value TEXT, updated_utc TEXT);
            """)
            db.execute("INSERT OR IGNORE INTO meta VALUES('schema_version',?)", (str(SCHEMA_VERSION),))

    @contextlib.contextmanager
    def _db(self):
        """Commit on success, roll back on error, and ALWAYS close (sqlite3's own context manager does not close)."""
        db = sqlite3.connect(self.db_path, timeout=30)
        try:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=NORMAL")
            with db:
                yield db
        finally:
            db.close()

    # ---------------- write
    def write_chunk(self, kind: str, schema: pa.Schema, rows: dict[str, list], *, source_id: str, server: str,
                    symbol: str, chunk: str, key_col: str, partition: str) -> dict:
        """Atomically write one parquet chunk. Returns {'status': 'written'|'identical'|'superseded_old', ...}."""
        table = pa.table(rows, schema=schema)
        n = table.num_rows
        if n == 0:
            return {"status": "empty", "rows": 0}
        keys = table.column(key_col).to_pylist()
        d = self.root / kind / f"source={source_id}" / f"symbol={symbol}" / partition
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / f".{uuid.uuid4().hex}.tmp"
        pq.write_table(table, tmp, compression="zstd")
        digest = sha256_file(tmp)
        with self._lock, self._db() as db:
            old = db.execute("SELECT id,sha256,path FROM files WHERE kind=? AND source_id=? AND symbol=? AND chunk=? "
                             "AND superseded=0", (kind, source_id, symbol, chunk)).fetchall()
            if any(o[1] == digest for o in old):
                tmp.unlink()
                return {"status": "identical", "rows": n}
            final = d / f"{chunk.replace(':', '-')}-{digest[:12]}.parquet"
            tmp.replace(final)  # atomic publish
            if old:
                db.executemany("UPDATE files SET superseded=1 WHERE id=?", [(o[0],) for o in old])
            db.execute("INSERT INTO files(kind,source_id,server,symbol,chunk,path,rows,min_key,max_key,sha256,"
                       "schema_version,dataset_version,created_utc) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))",
                       (kind, source_id, server, symbol, chunk, str(final.relative_to(self.root)), n, min(keys),
                        max(keys), digest, SCHEMA_VERSION, DATASET_VERSION))
        return {"status": "superseded_old" if old else "written", "rows": n, "path": str(final)}

    def quarantine(self, kind: str, key: int, reason: str, detail: str = ""):
        with self._lock, self._db() as db:
            db.execute("INSERT INTO quarantine(kind,key,reason,detail,created_utc) VALUES(?,?,?,?,datetime('now'))",
                       (kind, key, reason, detail))

    def quarantined(self, kind: str) -> dict[int, str]:
        with self._db() as db:
            return {k: r for k, r in db.execute("SELECT key,reason FROM quarantine WHERE kind=?", (kind,))}

    def set_checkpoint(self, name: str, value: str):
        with self._lock, self._db() as db:
            db.execute("INSERT INTO checkpoints VALUES(?,?,datetime('now')) ON CONFLICT(name) DO UPDATE SET "
                       "value=excluded.value, updated_utc=excluded.updated_utc", (name, value))

    def get_checkpoint(self, name: str) -> str | None:
        with self._db() as db:
            r = db.execute("SELECT value FROM checkpoints WHERE name=?", (name,)).fetchone()
        return r[0] if r else None

    # ---------------- read / verify
    def files(self, kind: str, include_superseded=False) -> list[dict]:
        q = "SELECT path,rows,min_key,max_key,sha256,superseded,chunk FROM files WHERE kind=?"
        if not include_superseded:
            q += " AND superseded=0"
        with self._db() as db:
            return [dict(zip(("path", "rows", "min_key", "max_key", "sha256", "superseded", "chunk"), r))
                    for r in db.execute(q + " ORDER BY min_key", (kind,))]

    def verify(self) -> list[str]:
        """Return a list of problems (empty = every manifest file exists with matching checksum)."""
        bad = []
        for f in self.files("ticks", True) + self.files("bars_m1", True):
            p = self.root / f["path"]
            if not p.exists():
                bad.append(f"MISSING {f['path']}")
            elif sha256_file(p) != f["sha256"]:
                bad.append(f"CHECKSUM_MISMATCH {f['path']}")
        return bad

    def read_table(self, kind: str) -> pa.Table:
        paths = [str(self.root / f["path"]) for f in self.files(kind)]
        return pa.concat_tables([pq.read_table(p) for p in paths]) if paths else pa.table({})


class LiveTickWriter(threading.Thread):
    """Off-hot-path writer for live ticks: buffers and flushes by size/time; never blocks the pipeline."""

    def __init__(self, store: Store, source_id="mt5_py_poll", flush_s=5.0, flush_n=5000):
        super().__init__(daemon=True, name="tick-writer")
        import queue
        self.store, self.source_id, self.flush_s, self.flush_n = store, source_id, flush_s, flush_n
        self.q: "queue.Queue" = queue.Queue(maxsize=200000)
        self.stop_ev = threading.Event()
        self.dropped = 0
        self.written = 0
        self.errors: list[str] = []

    def offer(self, tk) -> None:
        try:
            self.q.put_nowait(tk)
        except Exception:  # noqa: BLE001
            self.dropped += 1  # counted and surfaced in health, never silent

    def _flush(self, buf):
        if not buf:
            return
        by_day: dict[str, list] = {}
        for t in buf:
            by_day.setdefault(time.strftime("%Y-%m-%d", time.gmtime(t.time_msc / 1000)), []).append(t)
        for day, ts in by_day.items():
            cols = {"source_id": [t.source_id for t in ts], "terminal_ref": [""] * len(ts),
                    "server": [t.broker_server for t in ts], "symbol": [t.symbol for t in ts],
                    "time_msc": [t.time_msc for t in ts], "bid": [t.bid for t in ts], "ask": [t.ask for t in ts],
                    "last": [t.last for t in ts], "volume": [t.volume for t in ts], "flags": [t.flags for t in ts],
                    "received_at_ns": [t.gateway_received_ns for t in ts],
                    "quality_flags": [",".join(t.quality_flags) for t in ts],
                    "dataset_version": [DATASET_VERSION] * len(ts)}
            try:
                self.store.write_chunk("ticks", TICK_SCHEMA, cols, source_id=self.source_id, server=ts[0].broker_server,
                                       symbol=ts[0].symbol, chunk=f"live-{ts[0].bridge_seq}-{ts[-1].bridge_seq}",
                                       key_col="time_msc", partition=f"date={day}")
                self.written += len(ts)
            except Exception as e:  # noqa: BLE001
                self.errors.append(repr(e))
                self.dropped += len(ts)

    def run(self):
        import queue
        buf, last = [], time.monotonic()
        while not (self.stop_ev.is_set() and self.q.empty()):
            try:
                buf.append(self.q.get(timeout=0.5))
            except queue.Empty:
                pass
            if len(buf) >= self.flush_n or (buf and time.monotonic() - last >= self.flush_s):
                self._flush(buf)
                buf, last = [], time.monotonic()
        self._flush(buf)
