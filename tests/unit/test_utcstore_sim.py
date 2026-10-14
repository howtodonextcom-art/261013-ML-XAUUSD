"""Randomised DST simulation for the UTC resolver (Level 5.6, review round 14). The truth (true offset at every true instant) is known to the simulation; the resolver sees
only measured evidence (always correct at its own instant, as the freshness guard ensures), PROVISIONAL points that may be stale or wrong, and server stamps.
Property: the resolver may refuse a bar (None) but must NEVER return an offset that differs from the truth."""
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/gateway"))
from xau_gateway import utcstore as U  # noqa: E402

H, D = 3600, 86400


def simulate(seed):
    rng = np.random.default_rng(seed)
    span = 140 * D
    n_sw = int(rng.integers(0, 3))
    sw = []
    t = int(rng.integers(10 * D, 30 * D))
    for _ in range(n_sw):
        sw.append(t)
        t += int(rng.integers(35 * D, 60 * D))                                  # switches >= 35 days apart: longer than MAX_BRIDGE_S (30 d); real DST changes are months apart
        if t > span - 5 * D:
            break
    first = int(rng.choice([10800, 7200]))
    other = 7200 if first == 10800 else 10800

    def truth(u):
        k = sum(1 for s in sw if u >= s)
        return first if k % 2 == 0 else other

    ev = []
    u = 0
    while u < span:                                                             # the gateway is up for a while (hourly measurements), then down for a random time
        up = int(rng.integers(2 * H, 12 * D))
        for k in range(0, up, H):
            if u + k < span:
                obs = u + k + int(rng.integers(0, 600))
                ev.append((obs, truth(obs), True))                               # a measurement is correct at the instant it is taken
        u += up + int(rng.integers(0, 20 * D))
    for _ in range(int(rng.integers(0, 8))):                                    # provisional session-connect points: true, stale (previous offset) or simply wrong
        pu = int(rng.integers(0, span))
        kind = rng.integers(0, 3)
        off = truth(pu) if kind == 0 else (first if kind == 1 else int(rng.choice([7200, 10800])))
        ev.append((pu, off, False))
    runs = U.runs_of(ev)
    wrong, resolved, refused = 0, 0, 0
    seen_utc = {}
    samples = list(range(0, span, 3000))
    for r in runs:                                                              # dense sampling around the ends of every measured run (where a switch can hide)
        samples += [x for x in range(int(r[2]) - 3 * H, int(r[2]) + 3 * H, 300) if x >= 0]
        samples += [x for x in range(int(r[1]) - 3 * H, int(r[1]) + 3 * H, 300) if x >= 0]
    for ut in samples:
        o = truth(ut)
        off, status = U.resolve_offset(ut + o, runs)
        if off is None:
            refused += 1
            continue
        resolved += 1
        if off != o:
            wrong += 1
        key = ut + o - off
        if key in seen_utc and seen_utc[key] != ut:                            # two different true instants converted to one UTC key
            wrong += 1
        seen_utc[key] = ut
    return wrong, resolved, refused


def test_the_resolver_never_returns_a_wrong_offset_over_many_random_worlds():
    total_resolved = total_refused = 0
    for seed in range(200):
        wrong, resolved, refused = simulate(seed)
        assert wrong == 0, f"seed {seed}: {wrong} bars received a wrong offset or collided"
        total_resolved += resolved
        total_refused += refused
    assert total_resolved > 50_000 and total_refused > 1000                    # it converts plenty and refuses plenty: the property is not vacuous


# ---- the two counterexamples of the final independent review (round 14)
def test_h1_a_one_sided_stale_provisional_point_cannot_stretch_a_run_over_a_switch():
    runs = U.runs_of([(0, 7200, True), (1000, 7200, True), (9000, 7200, False)])           # a switch to 10800 happened while the gateway was down
    assert runs == [(7200, 0, 1000, True, True)]                                            # the provisional point has no measured neighbour AFTER it: dropped
    assert U.resolve_offset(3000 + 10800, runs)[0] is None                                  # a true-10800 bar at utc 3000 is refused, not relabelled 7200


def test_h2_a_fall_back_after_the_newest_measurement_never_gets_the_old_offset():
    runs = U.runs_of([(0, 10800, True), (36000, 10800, True)])                              # fall-back to 7200 at 36600, no measurement afterwards
    assert U.resolve_offset(37200 + 7200, runs)[0] is None                                  # a second-pass stamp (true utc 37200): refused, not 10800
    assert U.resolve_offset(20000 + 10800, runs)[0] == 10800                                # more than 2 h before the newest measurement: still converted
