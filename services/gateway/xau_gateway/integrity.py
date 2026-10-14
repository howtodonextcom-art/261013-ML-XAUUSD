"""Cross-file integrity checks for the store (read-only except supersede_where, which only flips the manifest flag; files stay on disk)."""
from __future__ import annotations

import numpy as np

from .storage import Store


def duplicate_times(store: Store, kind: str, **flt) -> dict:
    """Bars: active files of one (source, server, symbol) must hold each `time` once. Returns {'rows', 'unique', 'duplicates', 'examples'}."""
    t = store.read_table(kind, **flt)
    if t.num_rows == 0:
        return {"rows": 0, "unique": 0, "duplicates": 0, "examples": []}
    times = np.asarray(t["time"])
    u, c = np.unique(times, return_counts=True)
    return {"rows": int(len(times)), "unique": int(len(u)), "duplicates": int(len(times) - len(u)), "examples": [int(x) for x in u[c > 1][:5]]}


def supersede_where(store: Store, kind: str, *, source_id: str, server: str, symbol: str, chunk_prefix: str, quality: str) -> int:
    """Mark matching ACTIVE files as superseded with a quality note (never deleted). Returns the number of files changed."""
    with store._lock, store._db() as db:
        cur = db.execute("UPDATE files SET superseded=1, quality=? WHERE kind=? AND source_id=? AND server=? AND symbol=? AND chunk LIKE ? AND superseded=0",
                         (quality, kind, source_id, server, symbol, chunk_prefix + "%"))
        return cur.rowcount
