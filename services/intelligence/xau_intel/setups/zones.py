"""Support/resistance zones from CONFIRMED swings only.

A zone is a horizontal band: cluster of confirmed swing prices (any kind: broken support becomes resistance) lying within
`merge_atr` x ATR of each other, widened by `pad_atr` x ATR on each side. `known_at` of a zone = the latest `known_at` among its
swings, so a zone never exists before all of its swings were confirmed. Zones are recomputed from the swings known at the time
of evaluation; nothing here looks ahead.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..structure import Swing

ZONE_VERSION = "zone-1"


@dataclass(frozen=True)
class Zone:
    low: float
    high: float
    center: float
    touches: int
    known_at: int
    first_idx: int
    last_idx: int

    @property
    def zone_id(self) -> str:
        return f"Z{self.center:.2f}"


def build_zones(swings: list[Swing], atr_value: float, merge_atr: float = 0.5, pad_atr: float = 0.25, min_touches: int = 2) -> list[Zone]:
    swings = [s for s in swings if not s.window_start_artifact]
    if not swings or atr_value is None or np.isnan(atr_value) or atr_value <= 0:
        return []
    pts = sorted(swings, key=lambda s: s.price)
    clusters: list[list[Swing]] = []
    for s in pts:
        if clusters and s.price - clusters[-1][0].price <= merge_atr * atr_value:   # distance from the cluster's lowest member (no chaining drift)
            clusters[-1].append(s)
        else:
            clusters.append([s])
    zones = []
    for cl in clusters:
        if len(cl) < min_touches:
            continue
        prices = [x.price for x in cl]
        pad = pad_atr * atr_value
        zones.append(Zone(min(prices) - pad, max(prices) + pad, float(np.mean(prices)), len(cl), max(x.known_at for x in cl),
                          min(x.idx for x in cl), max(x.idx for x in cl)))
    return sorted(zones, key=lambda z: z.center)
