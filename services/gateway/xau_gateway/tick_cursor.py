"""Overlap-window tick cursor with occurrence counting.

MT5 ticks have no unique id. Identity = (time_msc, payload fingerprint) + occurrence index k, i.e. the k-th tick with
that exact payload at that millisecond. Each poll re-reads an overlap window; a tick is NEW iff its occurrence index
is >= the number already consumed for that (msc, fingerprint). This never relies on `last_msc + 1`.

Limits (published, not hidden):
 - Two bit-identical ticks in the same ms are distinguishable only by count; if the source itself collapses them we
   cannot know. Delivery is "exactly-once per observed occurrence", not a proof of exact-once at the exchange.
 - A tick that appears at an ms OLDER than the current watermark is emitted flagged late=True (LATE_INSERT) so that
   consumers can persist it and the data-quality engine can record it; candle engines must not rewrite closed bars.
 - A tick that appears later than `overlap_ms` behind the watermark cannot be seen by the overlap re-read; the
   history-settle probe (benchmarks/history_settle_probe.py) quantifies that lag, and the parity job re-checks old bars.
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from typing import Iterable, NamedTuple


class RawTick(NamedTuple):
    time_msc: int
    bid: float
    ask: float
    last: float
    volume: int
    flags: int

    @property
    def fingerprint(self) -> tuple:
        return (self.bid, self.ask, self.last, self.volume, self.flags)


@dataclass(frozen=True)
class Emitted:
    tick: RawTick
    occurrence: int
    late: bool


class TickCursor:
    def __init__(self, overlap_ms: int = 2000):
        self.overlap_ms = overlap_ms
        self.watermark_msc = 0                      # greatest time_msc emitted so far
        self.seen: dict[int, Counter] = {}          # msc -> Counter[fingerprint] for msc >= watermark - overlap
        self.late_total = 0
        self.emitted_total = 0
        self.initial_from_msc = 0                   # cold-start read position; does not make ticks 'late'

    def fetch_from_msc(self, continuation: bool = False) -> int:
        """Where the next source read should start. Normal poll: start of the overlap window (re-reads recent ticks to
        catch late inserts). continuation=True: the previous page was full, so read on from the watermark instead
        (otherwise a page smaller than the overlap window would never advance). 0 if nothing consumed yet."""
        if not self.watermark_msc:
            return self.initial_from_msc
        return self.watermark_msc if continuation else max(self.watermark_msc - self.overlap_ms, 0)

    def ingest(self, batch: Iterable[RawTick], continuation: bool = False) -> list[Emitted]:
        """`batch` must be in source order and start at the second containing fetch_from_msc(continuation) (the MT5 API
        has 1 s granularity, so every earlier occurrence in that second is present and counts stay correct).
        Returns only genuinely new occurrences, in source order."""
        out: list[Emitted] = []
        floor = self.fetch_from_msc(continuation)  # ms precision: ticks below this are not tracked, so never judged
        occ_in_batch: dict[tuple, int] = {}
        for t in batch:
            if self.watermark_msc and t.time_msc < floor:
                continue  # outside the tracked window: its occurrence counts were pruned, so novelty cannot be judged
            key = (t.time_msc, t.fingerprint)
            k = occ_in_batch.get(key, 0)
            occ_in_batch[key] = k + 1
            have = self.seen.get(t.time_msc, Counter())[t.fingerprint]
            if k < have:
                continue  # already consumed
            late = bool(self.watermark_msc) and t.time_msc < self.watermark_msc
            self.seen.setdefault(t.time_msc, Counter())[t.fingerprint] += 1
            self.watermark_msc = max(self.watermark_msc, t.time_msc)
            self.emitted_total += 1
            self.late_total += late
            out.append(Emitted(t, k, late))
        cutoff = self.fetch_from_msc()  # keep exactly what the next overlap read can return; pruning more causes re-emits
        for m in [m for m in self.seen if m < cutoff]:
            del self.seen[m]
        return out

    # ---- checkpoint (restart safety)
    def to_json(self) -> str:
        return json.dumps({"v": 1, "overlap_ms": self.overlap_ms, "watermark": self.watermark_msc,
                           "late_total": self.late_total, "emitted_total": self.emitted_total,
                           "seen": [[m, [[list(fp), n] for fp, n in c.items()]] for m, c in self.seen.items()]})

    @classmethod
    def from_json(cls, s: str) -> "TickCursor":
        d = json.loads(s)
        assert d["v"] == 1
        c = cls(d["overlap_ms"])
        c.watermark_msc, c.late_total, c.emitted_total = d["watermark"], d["late_total"], d["emitted_total"]
        c.seen = {m: Counter({tuple(fp): n for fp, n in items}) for m, items in d["seen"]}
        return c
