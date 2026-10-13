"""Canonical tick contract (prompt section 3.2). Source timestamps are preserved untouched."""
from dataclasses import dataclass, asdict


@dataclass(slots=True, frozen=True)
class Tick:
    source_id: str
    broker_server: str
    symbol: str
    time_msc: int             # terminal/server-time epoch ms, exactly as provided by MT5
    bid: float
    ask: float
    last: float
    volume: int
    flags: int
    bridge_seq: int           # gateway-assigned monotonically increasing sequence
    gateway_received_ns: int  # time.monotonic_ns() at receipt (same-host latency only)
    quality_flags: tuple = ()

    @property
    def spread(self) -> float:
        return self.ask - self.bid

    def to_dict(self) -> dict:
        d = asdict(self)
        d["quality_flags"] = list(self.quality_flags)
        d["spread"] = self.spread
        return d


def tick_quality(bid: float, ask: float, prev_msc: int | None, msc: int) -> tuple:
    """Flag anomalies; never silently fix them."""
    q = []
    if bid <= 0 or ask <= 0:
        q.append("NONPOSITIVE_PRICE")
    elif bid > ask:
        q.append("CROSSED_QUOTE")
    if prev_msc is not None and msc < prev_msc:
        q.append("OUT_OF_ORDER")
    return tuple(q)
