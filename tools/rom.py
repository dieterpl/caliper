#!/usr/bin/env python3
"""Range of motion: how far each joint can actually travel before it hits something.

`fitcheck.py` measures the model in ONE pose — the one it is authored in.
Nothing checked what happens when a joint is driven to the limit `config.py`
declares for it, so a limit could put the shank through the bracket and the only
symptom would be the sim quietly shoving two colliders apart mid-stride.

    .venv/bin/python tools/rom.py                    # every joint
    .venv/bin/python tools/rom.py --joint fl_knee    # one, in detail
    .venv/bin/python tools/rom.py --steps 40 --pairs # denser, and show the working

For each joint it rotates the whole subtree below it (link + its motors, pulleys
and belts, via tools/kin.py), scans outward from the rest pose towards each
declared limit, and bisects onto the angle where a real boolean intersection
first appears. Output is degrees of JOINT space — the frame `out/scene.json`
uses, where zero is the standing crouch, not legs-straight.

Two things stop the answer being nonsense:

  * **Baselines.** A link ALREADY overlaps its parent at the pivot; that is how
    a hinge is built. Each pair's rest-pose overlap is measured first and only
    growth beyond it counts as a collision. That rule, and the box pruning that
    keeps the sweep affordable, live in `tools/clash.py` — `collide.py` tests
    the same machine along its gait and has to agree about what a clash is.
  * **The floor is not a collision.** Swinging a leg down into the ground slab
    blocks every hip and knee at once and says nothing about the mechanism, so
    `ground` is excluded unless you ask for it with `--ground`.

Exits non-zero when a declared limit reaches past the collision-free window —
that is a mechanism that can break itself, and it wants either a tighter limit
in config.py or more clearance in the part.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from fnmatch import fnmatch
from math import degrees
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import clash  # noqa: E402  (the collision rule, shared with collide.py)
import kin  # noqa: E402  (adds cad/ to the path and populates SCENE)

BISECT = 6          # halvings after the coarse scan: 1/64 of a step
DEFAULT_STEPS = 24  # coarse samples across the whole declared range


class Sweeper:
    """Poses one joint and reports the parts that clash at a given angle."""

    def __init__(self, joint, parts, args):
        self.j = joint
        self.P = parts
        self.args = args
        self.moving = kin.subtree(joint.name)
        self.field = None

    def prepare(self, lo: float, hi: float) -> None:
        """Pick the pairs worth testing, and measure their rest-pose overlap.

        Only pairs that MOVE relative to each other are worth anything: this
        sweep turns one joint, so everything in its subtree is rigid with
        everything else in it, and everything outside is rigid too.
        """
        # Sampled across the whole range, so the reachability bound is
        # conservative: a pair it rejects cannot touch at any angle in between.
        poses = [{self.j.name: lo + (hi - lo) * k / 8} for k in range(9)]
        self.field = clash.PairField(
            self.P, poses, ground=self.args.ground,
            keep=lambda a, b: (a in self.moving) != (b in self.moving),
            # Boxes have to actually overlap here. rom does not report near
            # misses, so a pair that merely comes close is wasted booleans.
            reach=0.0, near=0.0)

    @property
    def pairs(self):
        return self.field.pairs

    @property
    def baseline(self):
        return self.field.baseline

    # -- the test ---------------------------------------------------------
    def clash(self, theta: float):
        """(moving, static, growth) for the worst pair that has closed up at
        this angle, or None if the whole subtree is clear."""
        hits, _ = self.field.scan({self.j.name: theta})
        worst = None
        for h in hits:
            # PairField names a pair in sorted order; the report wants the part
            # that moved first.
            m, s = (h.a, h.b) if h.a in self.moving else (h.b, h.a)
            if clash.blocked(h) and (worst is None or h.growth > worst[2]):
                worst = (m, s, h.growth)
            if self.args.pairs:
                print(f"      {degrees(theta):+7.1f}°  {m:20} × {s:20}"
                      f"  {h.volume:9.0f} mm³"
                      f"  (rest {h.rest:.0f}, +{h.growth:.0f})")
        return worst

    def edge(self, limit: float):
        """Scan from the rest pose out to `limit`; return (free angle, blocker)."""
        if abs(limit) < 1e-9:
            return limit, None
        steps = max(2, self.args.steps)
        good, bad, hit = 0.0, None, None
        for k in range(1, steps + 1):
            theta = limit * k / steps
            worst = self.clash(theta)
            if worst:
                bad, hit = theta, worst
                break
            good = theta
        if bad is None:
            return limit, None
        for _ in range(BISECT):     # squeeze onto the angle where it closes up
            mid = (good + bad) / 2
            worst = self.clash(mid)
            if worst:
                bad, hit = mid, worst
            else:
                good = mid
        return good, (hit[0], hit[1], bad)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--joint", action="append", default=None,
                    help="joint name or glob; repeatable (default: all)")
    ap.add_argument("--steps", type=int, default=DEFAULT_STEPS,
                    help=f"coarse samples across the range (default {DEFAULT_STEPS})")
    ap.add_argument("--pairs", action="store_true",
                    help="print every pair measurement, not just the verdict")
    ap.add_argument("--ground", action="store_true",
                    help="let the floor block a joint (off: it blocks them all)")
    args = ap.parse_args()

    P = kin.parts()
    joints = kin.joints()
    wanted = [n for n in joints
              if joints[n].type == "revolute" and joints[n].limits
              and (not args.joint or any(fnmatch(n, p) for p in args.joint))]
    if not wanted:
        print("rom: no revolute joint with limits matched", file=sys.stderr)
        return 2

    print(f"{'joint':16} {'declared':>17} {'free':>17}  blocker")
    results = []
    problems = 0
    for name in wanted:
        j = joints[name]
        lo, hi = j.limits
        t0 = time.time()
        sw = Sweeper(j, P, args)
        sw.prepare(lo, hi)
        free_lo, blk_lo = sw.edge(lo)
        free_hi, blk_hi = sw.edge(hi)
        dt = time.time() - t0

        blocked = []
        for side, free, blk in ((-1, free_lo, blk_lo), (+1, free_hi, blk_hi)):
            if blk:
                # PairField keys a pair in sorted order; `blk` names the moving
                # part first, so the key may be either way round.
                rest = sw.baseline.get((blk[0], blk[1]),
                                       sw.baseline.get((blk[1], blk[0]), 0.0))
                blocked.append({"side": "lo" if side < 0 else "hi",
                                "moving": blk[0], "static": blk[1],
                                "at_deg": degrees(blk[2]),
                                "rest_overlap": rest})
        note = "-" if not blocked else ", ".join(
            f"{b['moving']} × {b['static']} @ {b['at_deg']:+.1f}°" for b in blocked)
        free_txt = ("full" if not blocked
                    else f"{degrees(free_lo):+7.1f}..{degrees(free_hi):+7.1f}")
        print(f"{name:16} {degrees(lo):+7.1f}..{degrees(hi):+7.1f} "
              f"{free_txt:>17}  {note}   [{len(sw.pairs)} pairs, {dt:.1f}s]")
        results.append({
            "joint": name, "a": j.a, "b": j.b,
            "declared_deg": [degrees(lo), degrees(hi)],
            "free_deg": [degrees(free_lo), degrees(free_hi)],
            "blocked": blocked,
            "tested_pairs": [list(p) for p in sw.pairs],
        })
        problems += len(blocked)

    kin.OUT.mkdir(parents=True, exist_ok=True)
    (kin.OUT / "rom.json").write_text(json.dumps(
        {"unit": "degrees, joint space (0 = the authored rest pose)",
         "ground_included": args.ground, "joints": results}, indent=2))
    print(f"\nwrote {kin.OUT / 'rom.json'}")
    if problems:
        print(f"{problems} joint limit(s) reach past a collision — "
              f"tighten the limit in cad/config.py or make room in the part")
        return 1
    print("OK — every declared limit is reachable without a collision")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
