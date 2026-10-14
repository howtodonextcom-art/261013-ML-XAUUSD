"""Mode B reader: tails the CSV written by mt5/experts/XauTickLoggerModeB.mq5 (read-only EA, no network, no trading call).

Pure and testable: no MT5 import, no threads. `poll()` returns the complete new data lines since the last call; a partial last line is kept
until its newline arrives, a truncated/replaced file restarts from the beginning (reported), malformed lines are counted, never raised and never
repaired. The header line (`#schema=1;symbol=..;server=..;account_ref=..;digits=..`) is parsed so the caller can verify the source identity
exactly like Mode A (SOURCE_MISMATCH on difference). Every EA restart appends a new header: `sessions` counts them.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ModeBTick:
    time_msc: int
    bid: float
    ask: float
    last: float
    volume: int
    flags: int
    wall_ns: int              # time.time_ns() when the reader saw the line (compare with time_msc minus the server offset for latency)


@dataclass
class ModeBReader:
    path: Path
    offset: int = 0
    buf: bytes = b""
    header: dict = field(default_factory=dict)
    sessions: int = 0
    gaps: list = field(default_factory=list)       # EA-reported #gap markers and suspected restart gaps (never repaired, always reported)
    last_msc: int = 0
    bad_lines: int = 0
    resets: int = 0
    lines_total: int = 0
    last_poll_error: str | None = None

    def poll(self, now_ns: int | None = None) -> list[ModeBTick]:
        now_ns = time.time_ns() if now_ns is None else now_ns
        try:
            size = os.path.getsize(self.path)
        except OSError as e:
            self.last_poll_error = type(e).__name__
            return []
        self.last_poll_error = None
        if size < self.offset:                       # truncated or replaced: start over, say so, never guess
            self.offset, self.buf = 0, b""
            self.resets += 1
        if size == self.offset:
            return []
        try:
            with open(self.path, "rb") as f:
                f.seek(self.offset)
                chunk = f.read(size - self.offset)
        except OSError as e:
            self.last_poll_error = type(e).__name__
            return []
        self.offset += len(chunk)
        data = self.buf + chunk
        *lines, self.buf = data.split(b"\n")         # the last element is an incomplete line (possibly empty)
        out: list[ModeBTick] = []
        for raw in lines:
            line = raw.rstrip(b"\r").decode("ascii", "replace").strip()
            if not line:
                continue
            self.lines_total += 1
            if line.startswith("#"):
                self._meta(line)
                continue
            t = parse_line(line, now_ns)
            if t is None:
                self.bad_lines += 1
            else:
                self.last_msc = max(self.last_msc, t.time_msc)
                out.append(t)
        return out

    def _meta(self, line: str) -> None:
        """`#schema=...` = a new EA session header (identity); `#gap;...` = the EA says it could not copy everything; other comments are ignored."""
        kv = {}
        for part in line[1:].split(";"):
            if "=" in part:
                k, v = part.split("=", 1)
                kv[k.strip()] = v.strip()
        if line.startswith("#schema"):
            if self.sessions and self.last_msc:
                try:
                    started = int(kv.get("started_msc", "0"))
                except ValueError:
                    started = 0
                if started and started - self.last_msc > 5000:
                    self.gaps.append({"kind": "SUSPECTED_RESTART_GAP", "last_msc": self.last_msc, "restart_msc": started})
            self.header = kv
            self.sessions += 1
        elif line.startswith("#gap"):
            self.gaps.append({"kind": "EA_GAP_MARKER", **kv})


def parse_line(line: str, now_ns: int) -> ModeBTick | None:
    p = line.split(",")
    if len(p) != 6:
        return None
    try:
        t = ModeBTick(int(p[0]), float(p[1]), float(p[2]), float(p[3]), int(p[4]), int(p[5]), now_ns)
    except ValueError:
        return None
    if t.time_msc <= 0 or not (t.bid == t.bid and t.ask == t.ask):          # non-positive time or NaN: malformed
        return None
    return t


def identity_mismatch(header: dict, expected: dict | None, symbol_hint: str | None = None) -> str | None:
    """None when the EA's header matches the pinned identity (server, account_ref, symbol); else the reason. A missing header is a mismatch."""
    exp = expected or {}
    if not header:
        return "no header line yet: the source identity is unknown"
    if exp.get("server") and header.get("server") != exp["server"]:
        return f"server {header.get('server')} != expected {exp['server']}"
    if exp.get("account_ref") and header.get("account_ref") != exp["account_ref"]:
        return "account identity differs from the pinned account_ref"
    if symbol_hint and not str(header.get("symbol", "")).startswith(symbol_hint):
        return f"symbol {header.get('symbol')} does not match {symbol_hint}"
    return None
