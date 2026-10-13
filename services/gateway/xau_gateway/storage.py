"""Canonical storage: partitioned Parquet (raw ticks / M1 bars) + SQLite WAL manifest.

Rules
- Raw data is never deleted or rewritten in place; files are written atomically (tmp -> rename) with sha256 + row count
  in the manifest.
- Dataset identity = (kind, source_id, server, symbol, capture_session_id, chunk). Live chunks carry the capture session so a
  restart (bridge_seq reset) can never collide with an earlier session. Live chunks are NEVER superseded.
- Historical chunks (fixed identity such as an hour) that are re-fetched with different content are added and the old one is
  marked superseded (kept on disk). Identical re-fetch is a no-op (idempotent). Supersede never crosses source/server/symbol.
- Reads are always filtered (source / server / symbol / session); an unfiltered read is explicit and mixes provenance.
- Restart recovery is driven by what is PERSISTED (restore_cursor), never by an in-memory checkpoint that may be ahead of disk.
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

from .tick_cursor import RawTick, TickCursor

SCHEMA_VERSION = 2
DATASET_VERSION = "ds-0.2"

TICK_SCHEMA = pa.schema([
    ("source_id", pa.string()), ("terminal_ref", pa.string()), ("server", pa.string()), ("symbol", pa.string()),
    ("time_msc", pa.int64()), ("bid", pa.float64()), ("ask", pa.float64()), ("last", pa.float64()),
    ("volume", pa.int64()), ("flags", pa.int32()), ("received_at_ns", pa.int64()), ("quality_flags", pa.string()),
    ("dataset_version", pa.string()), ("capture_session_id", pa.string()), ("provenance", pa.string()),
])
BAR_SCHEMA = pa.schema([
    ("source_id", pa.string()), ("server", pa.string()), ("symbol", pa.string()), ("tf", pa.string()),
    ("time", pa.int64()), ("open", pa.float64()), ("high", pa.float64()), ("low", pa.float64()),
    ("close", pa.float64()), ("tick_volume", pa.int64()), ("spread", pa.int32()), ("real_volume", pa.int64()),
    ("dataset_version", pa.string()),
])
FILE_COLS = ("path", "rows", "min_key", "max_key", "sha256", "superseded", "chunk", "source_id", "server", "symbol",
             "session", "quality")


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
              quality TEXT DEFAULT '', session TEXT DEFAULT '');
            CREATE INDEX IF NOT EXISTS ix_files_chunk ON files(kind, source_id, server, symbol, chunk, superseded);
            CREATE TABLE IF NOT EXISTS quarantine(
              id INTEGER PRIMARY KEY, kind TEXT, key INTEGER, reason TEXT, detail TEXT, created_utc TEXT,
              server TEXT DEFAULT '', symbol TEXT DEFAULT '');
            CREATE TABLE IF NOT EXISTS checkpoints(name TEXT PRIMARY KEY, value TEXT, updated_utc TEXT);
            CREATE TABLE IF NOT EXISTS sessions(
              session_id TEXT PRIMARY KEY, source_id TEXT, server TEXT, symbol TEXT, started_utc TEXT,
              server_utc_offset_s INTEGER, terminal_ref TEXT, note TEXT);
            """)
            cols = {r[1] for r in db.execute("PRAGMA table_info(files)")}
            if "session" not in cols:  # migrate manifests created by schema v1
                db.execute("ALTER TABLE files ADD COLUMN session TEXT DEFAULT ''")
            qcols = {r[1] for r in db.execute("PRAGMA table_info(quarantine)")}
            for c in ("server", "symbol"):
                if c not in qcols:
                    db.execute(f"ALTER TABLE quarantine ADD COLUMN {c} TEXT DEFAULT ''")
            db.execute("INSERT OR REPLACE INTO meta VALUES('schema_version',?)", (str(SCHEMA_VERSION),))

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

    # ---------------- metadata / sessions
    def set_meta(self, k: str, v: str):
        with self._lock, self._db() as db:
            db.execute("INSERT INTO meta VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, v))

    def get_meta(self, k: str) -> str | None:
        with self._db() as db:
            r = db.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
        return r[0] if r else None

    def new_session(self, source_id: str, server: str, symbol: str, server_utc_offset_s: int | None,
                    terminal_ref: str = "", note: str = "") -> str:
        sid = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + uuid.uuid4().hex[:8]
        with self._lock, self._db() as db:
            db.execute("INSERT INTO sessions VALUES(?,?,?,?,datetime('now'),?,?,?)",
                       (sid, source_id, server, symbol, server_utc_offset_s, terminal_ref, note))
        return sid

    # ---------------- write
    def write_chunk(self, kind: str, schema: pa.Schema, rows: dict[str, list], *, source_id: str, server: str,
                    symbol: str, chunk: str, key_col: str, partition: str, session: str = "",
                    allow_supersede: bool = True) -> dict:
        """Atomically write one parquet chunk. Returns {'status': 'written'|'identical'|'superseded_old'|'empty'}."""
        table = pa.table(rows, schema=schema)
        n = table.num_rows
        if n == 0:
            return {"status": "empty", "rows": 0}
        keys = table.column(key_col).to_pylist()
        d = self.root / kind / f"source={source_id}" / f"server={server}" / f"symbol={symbol}" / partition
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / f".{uuid.uuid4().hex}.tmp"
        pq.write_table(table, tmp, compression="zstd")
        digest = sha256_file(tmp)
        with self._lock, self._db() as db:
            old = db.execute("SELECT id,sha256 FROM files WHERE kind=? AND source_id=? AND server=? AND symbol=? "
                             "AND chunk=? AND session=? AND superseded=0",
                             (kind, source_id, server, symbol, chunk, session)).fetchall()
            if any(o[1] == digest for o in old) or any(self._same_content(table, o[0]) for o in old):
                tmp.unlink()
                return {"status": "identical", "rows": n}
            if old and not allow_supersede:
                tmp.unlink()
                raise RuntimeError(f"chunk identity collision for immutable chunk {chunk!r} (session {session!r})")
            final = d / f"{chunk.replace(':', '-')}-{digest[:12]}.parquet"
            tmp.replace(final)  # atomic publish
            if old:
                db.executemany("UPDATE files SET superseded=1 WHERE id=?", [(o[0],) for o in old])
            db.execute("INSERT INTO files(kind,source_id,server,symbol,chunk,path,rows,min_key,max_key,sha256,"
                       "schema_version,dataset_version,created_utc,session) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'),?)",
                       (kind, source_id, server, symbol, chunk, str(final.relative_to(self.root)), n, min(keys),
                        max(keys), digest, SCHEMA_VERSION, DATASET_VERSION, session))
        return {"status": "superseded_old" if old else "written", "rows": n, "path": str(final)}

    def _same_content(self, table: pa.Table, file_id: int) -> bool:
        """True when an existing active file holds the same data apart from metadata columns (dataset_version, provenance of
        schema evolution): a metadata-only change must not supersede a chunk. Fewer/more/different rows => False."""
        with self._db() as db:
            r = db.execute("SELECT path FROM files WHERE id=?", (file_id,)).fetchone()
        if not r:
            return False
        try:
            old = pq.read_table(self.root / r[0])
        except Exception:  # noqa: BLE001
            return False
        skip = {"dataset_version", "capture_session_id", "provenance"}
        cols = [c for c in table.column_names if c in old.column_names and c not in skip]
        if old.num_rows != table.num_rows:
            return False
        return table.select(cols).equals(old.select(cols))

    def quarantine(self, kind: str, key: int, reason: str, detail: str = "", server: str = "", symbol: str = ""):
        with self._lock, self._db() as db:
            db.execute("INSERT INTO quarantine(kind,key,reason,detail,created_utc,server,symbol) "
                       "VALUES(?,?,?,?,datetime('now'),?,?)", (kind, key, reason, detail, server, symbol))

    def quarantined(self, kind: str, server: str | None = None, symbol: str | None = None) -> dict[int, str]:
        q, a = "SELECT key,reason FROM quarantine WHERE kind=?", [kind]
        for col, v in (("server", server), ("symbol", symbol)):
            if v is not None:  # strict: a quarantine row applies only to the server/symbol it was written for
                q += f" AND {col}=?"
                a.append(v)
        with self._db() as db:
            return {k: r for k, r in db.execute(q, a)}

    def set_checkpoint(self, name: str, value: str):
        with self._lock, self._db() as db:
            db.execute("INSERT INTO checkpoints VALUES(?,?,datetime('now')) ON CONFLICT(name) DO UPDATE SET "
                       "value=excluded.value, updated_utc=excluded.updated_utc", (name, value))

    def get_checkpoint(self, name: str) -> str | None:
        with self._db() as db:
            r = db.execute("SELECT value FROM checkpoints WHERE name=?", (name,)).fetchone()
        return r[0] if r else None

    # ---------------- read / verify
    def files(self, kind: str, include_superseded=False, *, source_id=None, server=None, symbol=None, session=None,
              chunk_prefix=None) -> list[dict]:
        q, a = f"SELECT {','.join(FILE_COLS)} FROM files WHERE kind=?", [kind]
        if not include_superseded:
            q += " AND superseded=0"
        for col, v in (("source_id", source_id), ("server", server), ("symbol", symbol), ("session", session)):
            if v is not None:
                q += f" AND {col}=?"
                a.append(v)
        if chunk_prefix is not None:
            q += " AND chunk LIKE ?"
            a.append(chunk_prefix + "%")
        with self._db() as db:
            return [dict(zip(FILE_COLS, r)) for r in db.execute(q + " ORDER BY min_key", a)]

    def verify(self) -> list[str]:
        """Problems list (empty = every manifest file exists with matching checksum)."""
        bad = []
        with self._db() as db:
            kinds = [r[0] for r in db.execute("SELECT DISTINCT kind FROM files")]
        for f in [x for k in kinds for x in self.files(k, True)]:
            p = self.root / f["path"]
            if not p.exists():
                bad.append(f"MISSING {f['path']}")
            elif sha256_file(p) != f["sha256"]:
                bad.append(f"CHECKSUM_MISMATCH {f['path']}")
        return bad

    def read_table(self, kind: str, **filters) -> pa.Table:
        """Filters: source_id, server, symbol, session, chunk_prefix. Older files lacking newer columns are null-filled."""
        paths = [str(self.root / f["path"]) for f in self.files(kind, **filters)]
        if not paths:
            return pa.table({})
        return pa.concat_tables([pq.read_table(p) for p in paths], promote_options="default")

    # ---------------- restart recovery from PERSISTED state
    def restore_cursor(self, *, source_id: str, server: str, symbol: str, overlap_ms: int = 2000) -> TickCursor:
        """Rebuild a TickCursor from persisted live ticks only: seed the overlap window as 'already seen' so a restart
        re-reads (from MT5) exactly the ticks that were consumed but never reached disk, without duplicating persisted ones."""
        files = self.files("ticks", source_id=source_id, server=server, symbol=symbol)
        cur = TickCursor(overlap_ms)
        if not files:
            return cur
        wm = max(f["max_key"] for f in files)
        lo = wm - overlap_ms
        tabs = [pq.read_table(self.root / f["path"], columns=["time_msc", "bid", "ask", "last", "volume", "flags"])
                for f in files if f["max_key"] >= lo]
        t = pa.concat_tables(tabs)
        msc = t["time_msc"].to_pylist()
        order = sorted((i for i, m in enumerate(msc) if m >= lo), key=lambda i: msc[i])
        cols = {c: t[c].to_pylist() for c in ("bid", "ask", "last", "volume", "flags")}
        cur.ingest([RawTick(msc[i], cols["bid"][i], cols["ask"][i], cols["last"][i], cols["volume"][i], cols["flags"][i])
                    for i in order])
        cur.late_total = cur.emitted_total = 0  # seeding is not emission
        return cur


class LiveTickWriter(threading.Thread):
    """Off-hot-path writer for live ticks. Buffers and flushes by size/time; a failed flush is RETRIED with backoff (ticks stay
    in the buffer, order preserved). Only when the bounded buffer overflows are the oldest ticks dropped; that sets `hole=True`
    permanently (health = DEGRADED) because the persisted watermark would otherwise skip over the lost span unnoticed.
    Chunks are immutable and named with the capture session, so restarts cannot collide or supersede."""

    def __init__(self, store: Store, source_id="mt5_py_poll", flush_s=5.0, flush_n=5000, session_id: str | None = None,
                 retry_base_s: float = 1.0, max_buffer: int = 500_000):
        super().__init__(daemon=True, name="tick-writer")
        import queue
        self.store, self.source_id, self.flush_s, self.flush_n = store, source_id, flush_s, flush_n
        self.session_id = session_id or uuid.uuid4().hex[:12]
        self.retry_base_s, self.max_buffer = retry_base_s, max_buffer
        self.q: "queue.Queue" = queue.Queue(maxsize=200000)
        self.stop_ev = threading.Event()
        self.dropped = 0
        self.written = 0
        self.failed_flushes = 0
        self.pending_failures = 0     # consecutive failed attempts for the current buffer (0 = healthy)
        self.hole = False
        self.errors: list[str] = []

    def offer(self, tk) -> None:
        try:
            self.q.put_nowait(tk)
        except Exception:  # noqa: BLE001
            self.dropped += 1
            self.hole = True  # the writer queue itself overflowed: ticks are lost, loudly

    def _flush(self, buf) -> list:
        """Write `buf`; return the ticks that could NOT be written (empty list = fully persisted)."""
        if not buf:
            return []
        groups: dict[tuple, list] = {}
        for t in buf:
            day = time.strftime("%Y-%m-%d", time.gmtime(t.time_msc / 1000))  # server-time date
            groups.setdefault((t.broker_server, t.symbol, day), []).append(t)
        failed: list = []
        for (server, symbol, day), ts in groups.items():
            cols = {"source_id": [t.source_id for t in ts], "terminal_ref": [""] * len(ts),
                    "server": [server] * len(ts), "symbol": [symbol] * len(ts),
                    "time_msc": [t.time_msc for t in ts], "bid": [t.bid for t in ts], "ask": [t.ask for t in ts],
                    "last": [t.last for t in ts], "volume": [t.volume for t in ts], "flags": [t.flags for t in ts],
                    "received_at_ns": [t.gateway_received_ns for t in ts],  # process-monotonic ns: meaningful only within one session
                    "quality_flags": [",".join(t.quality_flags) for t in ts],
                    "dataset_version": [DATASET_VERSION] * len(ts), "capture_session_id": [self.session_id] * len(ts),
                    "provenance": ["LIVE_CAPTURE"] * len(ts)}
            try:
                self.store.write_chunk("ticks", TICK_SCHEMA, cols, source_id=self.source_id, server=server, symbol=symbol,
                                       chunk=f"live-{ts[0].bridge_seq}-{ts[-1].bridge_seq}", key_col="time_msc",
                                       partition=f"date={day}", session=self.session_id, allow_supersede=False)
                self.written += len(ts)
            except Exception as e:  # noqa: BLE001
                self.errors.append(repr(e))
                del self.errors[:-20]
                failed.extend(ts)
        failed.sort(key=lambda t: t.bridge_seq)
        return failed

    def run(self):
        import queue
        buf, last, next_try = [], time.monotonic(), 0.0
        while not (self.stop_ev.is_set() and self.q.empty() and not buf):
            try:
                buf.append(self.q.get(timeout=0.2))
                for _ in range(10_000):  # drain what is already queued
                    buf.append(self.q.get_nowait())
            except queue.Empty:
                pass
            now = time.monotonic()
            due = len(buf) >= self.flush_n or (buf and now - last >= self.flush_s) or (buf and self.stop_ev.is_set())
            if buf and due and now >= next_try:
                buf = self._flush(buf)
                if buf:
                    self.failed_flushes += 1
                    self.pending_failures += 1
                    next_try = now + min(30.0, self.retry_base_s * 2 ** min(self.pending_failures, 5))
                    if len(buf) > self.max_buffer:
                        lost = len(buf) - self.max_buffer
                        buf = buf[lost:]
                        self.dropped += lost
                        self.hole = True
                    if self.stop_ev.is_set() and self.pending_failures > 8:
                        self.dropped += len(buf)   # shutting down with an unwritable disk: report, do not hang
                        self.hole = True
                        break
                else:
                    self.pending_failures = 0
                    last = now
