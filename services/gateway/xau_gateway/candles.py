"""Tick-driven candle engine. Bars are bucketed in the same (server) time base as MT5 bars.
Price basis defaults to BID, which is what MT5 charts draw. No synthetic ticks/bars are ever created."""
from dataclasses import dataclass

TF_SECONDS = {"M1": 60, "M5": 300, "M15": 900, "H1": 3600, "H4": 14400}


@dataclass
class Candle:
    tf: str
    t: int  # bucket start, epoch seconds (server time base)
    o: float
    h: float
    l: float
    c: float
    tick_volume: int = 0
    spread_sum: float = 0.0
    spread_max: float = 0.0
    state: str = "OPEN"  # OPEN | CLOSED
    source: str = "LIVE_TICKS"
    completeness: str = "FROM_FIRST_SEEN_TICK"  # unprovable unless the bar began at its first tick of the bucket
    last_update_msc: int = 0
    first_msc: int = 0
    late_applied: int = 0  # ticks that arrived out of order but still belong to this open bar

    def to_dict(self):
        n = max(self.tick_volume, 1)
        return {"tf": self.tf, "time": self.t, "open": self.o, "high": self.h, "low": self.l, "close": self.c,
                "tick_volume": self.tick_volume, "spread_avg": self.spread_sum / n, "spread_max": self.spread_max,
                "state": self.state, "source": self.source, "completeness": self.completeness,
                "last_update_msc": self.last_update_msc, "late_applied": self.late_applied}


class CandleEngine:
    def __init__(self, timeframes=("M1", "M5", "M15", "H1", "H4"), price="bid", max_closed=2000):
        assert price in ("bid", "ask", "mid")
        self.price, self.max_closed = price, max_closed
        self.tfs = {tf: TF_SECONDS[tf] for tf in timeframes}
        self.open: dict[str, Candle] = {}
        self.closed: dict[str, list[Candle]] = {tf: [] for tf in timeframes}
        self.first_stream_tick = True
        self.late_closed_ticks = 0  # late ticks for already-closed bars: counted, never rewritten into closed history

    def _px(self, bid, ask):
        return bid if self.price == "bid" else ask if self.price == "ask" else (bid + ask) / 2

    def on_tick(self, time_msc: int, bid: float, ask: float, flags: int | None = None):
        """Returns list of (event, Candle), event in {'update','close'}.
        tick_volume follows MT5: with price=bid only ticks carrying TICK_FLAG_BID (flags & 2) are counted
        (verified 59/60 bars in benchmarks/candle_parity.py); flags=None counts every tick. A tick belonging to a bucket older
        than the open bar is rejected (closed history is never rewritten)."""
        px, sp, ev = self._px(bid, ask), ask - bid, []
        first = self.first_stream_tick
        self.first_stream_tick = False
        for tf, sec in self.tfs.items():
            bucket = (time_msc // 1000) // sec * sec
            cur = self.open.get(tf)
            if cur is not None and bucket < cur.t:
                self.late_closed_ticks += 1
                continue
            if cur is not None and bucket > cur.t:
                cur.state = "CLOSED"
                lst = self.closed[tf]
                lst.append(cur)
                if len(lst) > self.max_closed:
                    del lst[: len(lst) - self.max_closed]
                ev.append(("close", cur))
                cur = None
            if cur is None:
                # New bar starts at its first observed tick; no fabricated tick at :00.
                cur = Candle(tf, bucket, px, px, px, px, 0, first_msc=time_msc)
                if first:
                    cur.completeness = "PARTIAL_STARTED_MID_BAR"
                self.open[tf] = cur
            late = cur.tick_volume > 0 and time_msc < cur.last_update_msc  # out-of-order but inside this open bar
            cur.h = max(cur.h, px)
            cur.l = min(cur.l, px)
            if late:
                cur.late_applied += 1
                if time_msc < cur.first_msc:  # earlier than the first tick we saw: it is the true open
                    cur.o, cur.first_msc = px, time_msc
            else:
                cur.c = px  # close always follows the latest-timestamp tick
            if flags is None or self.price != "bid" or (flags & 2):
                cur.tick_volume += 1
            cur.spread_sum += sp
            cur.spread_max = max(cur.spread_max, sp)
            cur.last_update_msc = max(cur.last_update_msc, time_msc)
            ev.append(("update", cur))
        return ev
