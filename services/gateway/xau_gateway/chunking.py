"""Chunk identity must not depend on when a run happens.

A backfill chunk id is derived from a FIXED absolute grid (epoch-aligned cells), never from the moving `start` of the run. Two runs with
different `days` or at different moments therefore address the same cell with the same id; the store then either sees identical content
(no-op) or a revision of that very cell (old file superseded, kept on disk), and bars can never be duplicated by overlapping chunks.
"""
from __future__ import annotations

CELL_S = 30 * 86400


def grid_cells(start: int, end: int, cell_s: int = CELL_S) -> list[tuple[int, int, int]]:
    """[(cell_id, a, b)] covering [start, end): cell_id is the epoch-aligned cell start; [a, b) is the part of the cell inside the request."""
    out = []
    c = (start // cell_s) * cell_s
    while c < end:
        a, b = max(c, start), min(c + cell_s, end)
        if a < b:
            out.append((c, a, b))
        c += cell_s
    return out
