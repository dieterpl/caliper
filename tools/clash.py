"""What counts as a collision, and which pairs are worth asking about.

`rom.py` swings one joint through its limits; `collide.py` poses the whole model
along the gait it actually walks. Both need the same two answers, and a second
copy of either is how two tools start disagreeing about whether the same machine
is broken.

**What a collision is.** A pair that ALREADY shares metal at rest is not
colliding: a shaft sits in its bore, a fork straddles a can, a belt reaches into
the pulley it drives. Rotating those changes the shared volume by tens of mm^3
within a fraction of a degree, so an absolute test reports every such pair as
blocked immediately, which is useless. Only growth past the rest-pose overlap
counts -- `GROWTH_VOL + REL_GROWTH * rest`.

**Which pairs to ask about.** A real boolean costs ~60 ms, so a 4000-pose sweep
cannot afford one per pair per pose. `PairField` unions each part's box over the
whole sample set first and drops any pair that cannot meet anywhere in it, then
re-tests boxes at each individual pose before reaching for OCCT. Both bounds are
conservative by construction, so nothing is dropped that could have touched.

The boxes come from transforming the eight corners of a part's LOCAL bounding
box rather than placing its geometry. A solid lies inside its own box, and a
rigid motion carries that box inside the box of its moved corners -- so the
result still contains the posed part, at a few microseconds instead of tens of
milliseconds. That is what makes the wide sweeps finish.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import kin  # noqa: E402  (adds cad/ to the path and populates SCENE)
from fitcheck import MIN_VOL, NEAR_MM, aabb, box_gap, intersection, nearest  # noqa: E402

# Shared solid has to grow past this before a pair counts as having closed up.
# The absolute floor is fitcheck's 5 mm^3 -- below that it is tessellation noise.
# The relative term is what makes the answer trustworthy for a pair that already
# shares metal at rest, and many do.
GROWTH_VOL = MIN_VOL
REL_GROWTH = 0.25


def union_box(boxes):
    """AABB covering every box in the list — a cheap reachability bound, so a
    pair that can never meet is never booleaned."""
    return (min(b[0] for b in boxes), max(b[1] for b in boxes),
            min(b[2] for b in boxes), max(b[3] for b in boxes),
            min(b[4] for b in boxes), max(b[5] for b in boxes))


def world_box(shape):
    """AABB of already-placed geometry."""
    return aabb(shape, (0, 0, 0))


def corners(part):
    """The eight corners of a part's own local bounding box."""
    b = part.bounding_box()
    return [(x, y, z)
            for x in (b.min.X, b.max.X)
            for y in (b.min.Y, b.max.Y)
            for z in (b.min.Z, b.max.Z)]


def relative_key(la, lb, tol=1e-6):
    """How part b stands relative to part a, rounded to a hashable key.

    Whether two parts touch depends only on this, never on where the pair sits
    in the world — so two poses with the same key have the same answer, and the
    second one is free.
    """
    rel = la.inverse() * lb
    return tuple(round(v / tol) for v in
                 (*rel.position.to_tuple(), *rel.orientation.to_tuple()))


def posed_box(loc, pts):
    """Conservative world AABB of a part placed by `loc`, from its corners."""
    p = kin.transform(loc, pts)
    return (float(p[:, 0].min()), float(p[:, 0].max()),
            float(p[:, 1].min()), float(p[:, 1].max()),
            float(p[:, 2].min()), float(p[:, 2].max()))


@dataclass
class Hit:
    """Two parts sharing solid at some pose. `blocked()` decides if that is a
    fault; a Hit on its own may just be a shaft sitting in its bore."""
    a: str
    b: str
    volume: float           # mm^3 shared at this pose
    rest: float             # ...and at the authored rest pose
    growth: float
    center: tuple | None    # centroid of the largest blob, world mm

    @property
    def margin(self) -> float:
        """How far this pair is towards blocking; >= 1.0 is a collision."""
        limit = GROWTH_VOL + REL_GROWTH * self.rest
        return self.growth / limit if limit else 0.0


@dataclass
class Gap:
    """Two parts that clear each other, and by how much."""
    a: str
    b: str
    distance: float
    pa: tuple
    pb: tuple


def blocked(hit: Hit) -> bool:
    """Has this pair closed up, as opposed to merely touching the way it was
    built to?"""
    return hit.growth > GROWTH_VOL + REL_GROWTH * hit.rest


class PairField:
    """The pairs worth testing across a set of poses, and what each starts from.

    `poses` is the sample set the sweep will visit — it is used only to bound
    where each part can reach, so it may be coarser than what `scan()` is later
    asked about, as long as it spans the same range.

    `keep(a, b)` filters the pair list further (rom.py wants only pairs that move
    relative to each other; --cross wants only pairs from different legs).
    `reach` is how close two union boxes must come to be worth keeping: 0 means
    they must actually overlap, which is the cheapest useful setting.
    """

    def __init__(self, parts, poses, *, ground=False, keep=None, reach=NEAR_MM,
                 near=NEAR_MM):
        self.P = parts
        self.near = near
        names = [n for n in parts if ground or n != "ground"]
        self._corners = {n: corners(parts[n].part) for n in names}

        boxes = []
        for pose in poses:
            locs = kin.placements(pose)
            boxes.append({n: posed_box(locs[n], self._corners[n]) for n in names})
        span = {n: union_box([b[n] for b in boxes]) for n in names}

        self.pairs: list[tuple[str, str]] = []
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                if parts[a].owner == parts[b].owner:
                    continue
                if keep and not keep(a, b):
                    continue
                if box_gap(span[a], span[b]) > reach:
                    continue
                self.pairs.append((a, b))

        # Only parts that survived into a pair ever need real geometry.
        self.used = sorted({n for p in self.pairs for n in p})
        rest = kin.placements()
        rest_geo = {n: rest[n] * parts[n].part for n in self.used}
        self.baseline: dict[tuple[str, str], float] = {}
        for a, b in self.pairs:
            blobs = intersection(rest_geo[a], rest_geo[b])
            self.baseline[(a, b)] = sum(x[0] for x in blobs) if blobs else 0.0

    # -- one pose ---------------------------------------------------------
    def _placed(self, pose):
        """(locations, boxes, lazy geometry getter) for one pose."""
        locs = kin.placements(pose)
        boxes = {n: posed_box(locs[n], self._corners[n]) for n in self.used}
        geo: dict[str, object] = {}

        def shape(n):
            if n not in geo:
                geo[n] = locs[n] * self.P[n].part
            return geo[n]

        return boxes, shape

    def scan(self, pose) -> tuple[list[Hit], list[Gap]]:
        """(hits, gaps) at one pose: every pair sharing solid, and the closest
        approach of every pair that comes within `near` without touching.

        Boxes decide what gets asked. Two solids cannot share space unless their
        boxes do, so a boolean only runs on an actual box overlap; a distance
        query only runs on a pair whose boxes are within `near` of each other.
        """
        boxes, shape = self._placed(pose)
        hits: list[Hit] = []
        gaps: list[Gap] = []
        for a, b in self.pairs:
            g = box_gap(boxes[a], boxes[b])
            if g > self.near:
                continue
            if g <= 0:
                blobs = intersection(shape(a), shape(b)) or []
                vol = sum(x[0] for x in blobs)
                if vol > MIN_VOL:
                    rest = self.baseline[(a, b)]
                    hits.append(Hit(a, b, vol, rest, vol - rest, blobs[0][1]))
                    continue
            got = nearest(shape(a), shape(b))
            if got and got[0] <= self.near:
                gaps.append(Gap(a, b, got[0], got[1], got[2]))
        return hits, gaps

    # -- a whole sweep ----------------------------------------------------
    def sweep(self, poses, note=None) -> list[dict]:
        """Fold a list of poses into one row per pair: the worst it ever got,
        the closest it ever came, and where in the sweep each happened.

        Done in two passes, because the exact answers are the expensive ones.
        The first pass is boxes only — cheap enough to run on every pose. The
        second spends OCCT only where the first says it could matter:

          * a boolean only where two boxes actually overlap, and
          * a distance query under a branch and bound. Box gap never exceeds
            true gap, so once some pose has been measured at `best`, every pose
            whose BOX gap is already >= best is provably not the closest
            approach and is skipped. Visiting poses in order of box gap
            therefore finds the exact minimum over the sample, usually after one
            or two queries instead of one per pose.
        """
        n = len(poses)
        # pass 1: box gap of every pair at every pose, and how the two parts of
        # each pair stand RELATIVE to each other. Boxes and 4x4s only, so this
        # is affordable on every pose even when there are thousands of them.
        #
        # The relative pose is what decides whether two parts touch -- so a pose
        # that repeats one already measured cannot say anything new, and is
        # dropped here rather than paid for in OCCT. It is not a rare case: the
        # abduction joints hold a constant offset through the whole gait, so
        # every chassis-to-leg pair is one measurement, not one per phase.
        span = [[0.0] * n for _ in self.pairs]
        seen: list[dict] = [{} for _ in self.pairs]
        todo: list[list[int]] = [[] for _ in self.pairs]
        for i, pose in enumerate(poses):
            locs = kin.placements(pose)
            boxes = {nm: posed_box(locs[nm], self._corners[nm]) for nm in self.used}
            for k, (a, b) in enumerate(self.pairs):
                span[k][i] = box_gap(boxes[a], boxes[b])
                key = relative_key(locs[a], locs[b])
                if key not in seen[k]:
                    seen[k][key] = i
                    todo[k].append(i)
            if note and n > 200 and (i + 1) % 200 == 0:
                note(f"      boxes {i + 1}/{n}")
        # A pose left out of todo[k] repeats one that is in it, so it inherits
        # that pose's answer and never reaches OCCT.
        distinct = sum(len(t) for t in todo)

        # Real geometry is held for ONE pose at a time and built per part on
        # demand: placing every part of every pose at once is what runs a wide
        # sweep out of memory.
        cache: dict[str, object] = {}
        cache_i = -1
        cache_locs = None

        def shape(i, name):
            nonlocal cache, cache_i, cache_locs
            if cache_i != i:
                cache, cache_i, cache_locs = {}, i, kin.placements(poses[i])
            if name not in cache:
                cache[name] = cache_locs[name] * self.P[name].part
            return cache[name]

        # pass 2a: the booleans, pose by pose so the geometry above is reused.
        by_pose: list[list[int]] = [[] for _ in range(n)]
        for k, want in enumerate(todo):
            for i in want:
                if span[k][i] <= 0:
                    by_pose[i].append(k)

        worst: dict[int, dict] = {}
        for i in range(n):
            for k in by_pose[i]:
                a, b = self.pairs[k]
                blobs = intersection(shape(i, a), shape(i, b)) or []
                vol = sum(x[0] for x in blobs)
                rest = self.baseline[(a, b)]
                if vol - rest <= worst.get(k, {}).get("growth", 0.0):
                    continue
                hit = Hit(a, b, vol, rest, vol - rest,
                          blobs[0][1] if blobs else None)
                worst[k] = {"growth": hit.growth, "volume": vol, "at": i / n,
                            "index": i, "blocked": blocked(hit),
                            "margin": hit.margin,
                            "center": list(hit.center) if hit.center else None,
                            "pose": {j: v for j, v in poses[i].items() if v}}

        # pass 2b: the closest approach of everything that never touched.
        rows = []
        for k, (a, b) in enumerate(self.pairs):
            row = {"a": a, "b": b, "rest": self.baseline[(a, b)],
                   "growth": 0.0, "gap": None}
            row.update(worst.get(k, {}))
            if row["growth"] <= 0:
                best = self.near
                for i in sorted(todo[k], key=lambda i: span[k][i]):
                    if span[k][i] >= best:
                        break               # no later pose can be closer
                    got = nearest(shape(i, a), shape(i, b))
                    if got and got[0] < best:
                        best = got[0]
                        row.update(gap=got[0], gap_at=i / n, gap_index=i,
                                   closest=[list(got[1]), list(got[2])])
            if row["growth"] > 0 or row["gap"] is not None:
                rows.append(row)
            if note and (k + 1) % 50 == 0:
                note(f"      pairs {k + 1}/{len(self.pairs)}")
        if note:
            note(f"      {distinct} distinct relative poses of "
                 f"{n * len(self.pairs)} pair-poses")
        return rows
