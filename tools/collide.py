#!/usr/bin/env python3
"""Does anything hit anything while the model MOVES?

Every other check here looks at the machine standing still. `fitcheck.py`
booleans one pose — the authored crouch. `rom.py` turns ONE joint out of that
crouch with the rest of the model frozen. Neither can see a pose that needs two
joints bent at once, and neither has ever looked at the pose the model is
actually commanded into: the gait drives all twelve joints together, with the
diagonal pairs half a stride apart.

    .venv/bin/python tools/collide.py                        # the gait, one stride
    .venv/bin/python tools/collide.py --samples 48
    .venv/bin/python tools/collide.py --grid fl_hip_pitch,fl_knee --steps 12
    .venv/bin/python tools/collide.py --pose fl_knee=-73.4
    .venv/bin/python tools/collide.py --cross                # leg against leg

Four questions, four modes:

  * **gait** (default) reads `drive.samples`/`phase` straight off the joints —
    the same table `web/src/viewer/physics.js:driveTarget` interpolates at run
    time — and reconstructs what every joint is told to do at each phase of the
    stride.
  * **--grid a,b** walks two joints across their declared limits together. This
    is the class of pose `rom.py` structurally cannot reach.
  * **--pose** is one configuration, in the same `joint=DEGREES` spelling
    `render.py` takes, so a finding here can be rendered without translation.
  * **--cross** asks whether two legs can reach each other AT ALL. A leg's
    geometry depends only on its own three joints, so each leg's poses are
    enumerated once and then combined — which turns an intractable six-axis
    sweep into box arithmetic, with booleans only where boxes actually meet.

What counts as a collision is `tools/clash.py`, shared with `rom.py`: growth
past the rest-pose overlap, because a shaft in its bore is not a crash.

The MIN GAP column is the point of the exercise. Pass/fail says the design
survives today; a margin says how much of it is left. Everything lands in
`out/collide.json`. Exits non-zero if anything closed up.

WHAT IT COSTS, measured on this model: the gait sweep is ~4 min at 24 phases and
scales with `--samples`; a 6x6 `--grid` is ~70 s; `--cross` is ~30 min at the
default 3 steps and roughly (steps/3)^6 beyond that, so raise it deliberately.
An OCCT boolean on these solids is ~50 ms and a distance query ~80 ms, which is
the floor -- everything in `clash.py` exists to keep the count down.
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
import time
from math import degrees, pi, sin
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import clash  # noqa: E402
import kin  # noqa: E402  (adds cad/ to the path and populates SCENE)
from render import parse_pose  # noqa: E402  (one spelling of joint=DEGREES)

LEGS = ("fl", "fr", "bl", "br")
SHOWN = 25          # console only; out/collide.json always carries them all


# ---------------------------------------------------------------- the poses --
def gait_poses(joints, n):
    """What every driven joint is commanded to, at n phases of one stride.

    A sampled drive is a table of angles wrapped over the stride, so this is the
    same interpolation `web/src/viewer/physics.js:driveTarget` does — read from
    the model rather than re-derived, so a change to cad/gait.py cannot leave
    this behind.
    """
    driven = {name: j.drive for name, j in joints.items() if j.drive}
    poses = []
    for k in range(n):
        u = k / n
        pose = {}
        for name, d in driven.items():
            phase = ((u + d.get("phase", 0.0)) % 1.0 + 1.0) % 1.0
            s = d.get("samples")
            if s:
                f = phase * len(s)
                i = int(f)
                a = f - i
                pose[name] = s[i % len(s)] * (1 - a) + s[(i + 1) % len(s)] * a
            else:
                pose[name] = d.get("offset", 0.0) + d.get("amplitude", 0.0) * \
                    sin(2 * pi * phase)
        poses.append(pose)
    return poses


def grid_poses(joints, names, steps):
    """Cartesian product of two (or more) joints across their declared limits."""
    axes = []
    for n in names:
        j = joints[n]
        if not j.limits:
            raise SystemExit(f"collide: {n} declares no limits to sweep")
        lo, hi = j.limits
        axes.append([lo + (hi - lo) * k / (steps - 1) for k in range(steps)])
    return [dict(zip(names, combo)) for combo in itertools.product(*axes)]


# -------------------------------------------------------------- the reports --
def fmt_pt(p):
    return f"({p[0]:.1f}, {p[1]:.1f}, {p[2]:.1f})"


def sweep(P, poses, label, *, keep=None, ground=False, quiet=False, bound=None):
    """Run a pose list through the field and fold the per-pose findings into one
    row per pair: the worst it ever got, and where in the sweep that was.

    `bound` is a cheaper pose list to draw the reachability bound from, when one
    exists that covers the same ground. --cross has one: a leg's parts depend
    only on that leg's own joints, so the union over 2 x 64 single-leg poses is
    identical to the union over their 4096 combinations, and costs 1/32 as much.
    """
    t0 = time.time()
    field = clash.PairField(P, bound or poses, ground=ground, keep=keep)
    if not quiet:
        print(f"=== {label} ===")
        print(f"  {len(poses)} poses, {len(field.pairs)} pair(s) in reach "
              f"(of {len(P)} parts)")
    if not field.pairs:
        if not quiet:
            print("  nothing can reach anything — nothing to test\n")
        return [], time.time() - t0

    rows = field.sweep(poses, note=None if quiet else print)
    for r in rows:                          # radians are the model's unit; the
        if r.get("pose"):                   # report is in degrees like rom.py
            r["pose"] = {k: degrees(v) for k, v in r["pose"].items()}
    dt = time.time() - t0

    out = sorted(rows,
                 key=lambda r: (-r["growth"], r["gap"] if r["gap"] is not None else 1e9))
    if not quiet:
        print(f"  {'pair':47} {'min gap':>9} {'at':>6} {'growth':>12}")
        for r in out[:SHOWN]:
            bad = r["growth"] > 0 and r.get("blocked")
            gap = "-" if r["gap"] is None else f"{r['gap']:.2f} mm"
            at = r.get("at", r.get("gap_at", 0.0))
            grow = "-" if not r["growth"] else f"{r['growth']:9.0f} mm³"
            print(f"  {'!!' if bad else '  '} {r['a']:21} × {r['b']:21}"
                  f" {gap:>9} {at:6.2f} {grow:>12}")
        if len(out) > SHOWN:
            print(f"  ... {len(out) - SHOWN} more, see out/collide.json")
        hits = [r for r in out if r.get("blocked")]
        print(f"  {len(hits)} clash(es) in {dt:.1f}s\n")
    return out, dt


# ------------------------------------------------------------------- --cross --
def leg_of(P, name):
    """Which leg a part belongs to, or None for the chassis, head and ground."""
    owner = P[name].owner
    return owner[:2] if owner[:2] in LEGS and owner[2:3] == "_" else None


def cross_reach(P, joints, steps):
    """Can two legs reach each other at all?

    A leg's parts depend only on that leg's own three joints, so each leg is
    posed on its own coarse grid ONCE and its parts' boxes are cached. Combining
    two legs is then pure box arithmetic over the product of those grids — no
    six-axis placement, and OCCT is only asked about combinations whose boxes
    actually meet. A pair of legs whose whole reach envelopes miss each other is
    proven clear without a single boolean.
    """
    names = {leg: [n for n in P if leg_of(P, n) == leg] for leg in LEGS}
    corner = {n: clash.corners(P[n].part) for n in P}

    poses: dict[str, list] = {}
    boxes: dict[str, list] = {}
    for leg in LEGS:
        axes = []
        for suffix in ("_abd", "_hip_pitch", "_knee"):
            j = joints[leg + suffix]
            lo, hi = j.limits
            axes.append([lo + (hi - lo) * k / (steps - 1) for k in range(steps)])
        poses[leg] = []
        boxes[leg] = []
        for combo in itertools.product(*axes):
            pose = dict(zip([leg + s for s in ("_abd", "_hip_pitch", "_knee")],
                            combo))
            locs = kin.placements(pose)
            poses[leg].append(pose)
            boxes[leg].append({n: clash.posed_box(locs[n], corner[n])
                               for n in names[leg]})
    return names, poses, boxes


def cross_sweep(P, joints, steps, quiet=False):
    """Every leg against every other leg, and every leg against the chassis."""
    from fitcheck import box_gap

    t0 = time.time()
    names, poses, boxes = cross_reach(P, joints, steps)
    envelope = {leg: clash.union_box([b[n] for b in boxes[leg] for n in names[leg]])
                for leg in LEGS}
    if not quiet:
        print(f"=== leg reach envelopes ({steps}^3 poses per leg) ===")
        for leg in LEGS:
            e = envelope[leg]
            print(f"  {leg}  X {e[0]:7.1f}..{e[1]:7.1f}"
                  f"   Y {e[2]:7.1f}..{e[3]:7.1f}   Z {e[4]:7.1f}..{e[5]:7.1f}")

    report = []
    problems = 0
    for a, b in itertools.combinations(LEGS, 2):
        gap = box_gap(envelope[a], envelope[b])
        if gap > 0:
            if not quiet:
                print(f"\n  {a} × {b}: envelopes clear by {gap:.1f} mm — "
                      f"no joint combination can bring them together")
            report.append({"legs": [a, b], "envelope_gap": gap, "poses": []})
            continue
        # The envelopes interpenetrate, so combinations have to be tested. Box
        # arithmetic first: only a combination whose part boxes actually meet is
        # worth placing real geometry for.
        candidates = []
        for ia, ba in enumerate(boxes[a]):
            for ib, bb in enumerate(boxes[b]):
                for na in names[a]:
                    for nb in names[b]:
                        if box_gap(ba[na], bb[nb]) <= 0:
                            candidates.append((ia, ib))
                            break
                    else:
                        continue
                    break
        if not quiet:
            print(f"\n  {a} × {b}: envelopes overlap by {-gap:.1f} mm; "
                  f"{len(candidates)} of {len(poses[a]) * len(poses[b])} "
                  f"combinations put parts in contact")
        combos = [{**poses[a][ia], **poses[b][ib]} for ia, ib in candidates]
        rows: list[dict] = []
        if combos:
            keep = (lambda x, y, a=a, b=b:
                    {leg_of(P, x), leg_of(P, y)} == {a, b})
            rows, _ = sweep(P, combos, f"{a} × {b} contact combinations",
                            keep=keep, quiet=quiet,
                            bound=poses[a] + poses[b])
            problems += sum(1 for r in rows if r.get("blocked"))
        report.append({"legs": [a, b], "envelope_gap": gap,
                       "combinations": len(candidates), "pairs": rows})

    # ...and every leg against the body it hangs off.
    for leg in LEGS:
        keep = (lambda x, y, leg=leg:
                {leg_of(P, x), leg_of(P, y)} == {leg, None})
        rows, _ = sweep(P, poses[leg], f"{leg} × body", keep=keep, quiet=quiet)
        problems += sum(1 for r in rows if r.get("blocked"))
        report.append({"legs": [leg, "body"], "pairs": rows})

    if not quiet:
        print(f"cross sweep: {time.time() - t0:.1f}s")
    return report, problems


# -------------------------------------------------------------------- main ---
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--samples", type=int, default=24,
                    help="phases of the stride to test (default 24)")
    ap.add_argument("--grid", default=None,
                    help="two or more joint names, comma separated")
    ap.add_argument("--steps", type=int, default=None,
                    help="samples per axis (default 8 for --grid, 3 for --cross:"
                         " --cross is three axes per leg and squares them, so it"
                         " goes as steps^6 — 3 is already ~30 min)")
    ap.add_argument("--pose", default=None,
                    help="joint=DEGREES,... — one configuration, as render.py")
    ap.add_argument("--cross", action="store_true",
                    help="leg against leg and leg against body, over the limits")
    ap.add_argument("--ground", action="store_true",
                    help="let the floor count as a collision (off: feet stand on it)")
    args = ap.parse_args()

    P = kin.parts()
    joints = kin.joints()
    report: dict = {"unit": "mm, mm^3, degrees; 0 = the authored rest pose"}
    problems = 0

    if args.cross:
        report["cross"], problems = cross_sweep(P, joints,
                                                max(2, args.steps or 3))
    elif args.pose:
        pose = parse_pose(args.pose)
        unknown = set(pose) - set(joints)
        if unknown:
            raise SystemExit(f"collide: no such joint(s): {sorted(unknown)}")
        rows, _ = sweep(P, [pose], "one pose: " + args.pose, ground=args.ground)
        report["pose"] = {"angles_deg": {k: degrees(v) for k, v in pose.items()},
                          "pairs": rows}
        problems = sum(1 for r in rows if r.get("blocked"))
    elif args.grid:
        names = [n.strip() for n in args.grid.split(",") if n.strip()]
        unknown = [n for n in names if n not in joints]
        if unknown:
            raise SystemExit(f"collide: no such joint(s): {unknown}")
        steps = max(2, args.steps or 8)
        poses = grid_poses(joints, names, steps)
        rows, _ = sweep(P, poses, f"grid {' × '.join(names)} "
                                  f"({steps} steps each)", ground=args.ground)
        report["grid"] = {"joints": names, "steps": steps, "pairs": rows}
        problems = sum(1 for r in rows if r.get("blocked"))
    else:
        poses = gait_poses(joints, max(2, args.samples))
        driven = sorted({k for p in poses for k in p})
        rows, _ = sweep(P, poses,
                        f"gait · {len(poses)} phases · {len(driven)} joints commanded",
                        ground=args.ground)
        report["gait"] = {"samples": len(poses), "joints": driven, "pairs": rows}
        problems = sum(1 for r in rows if r.get("blocked"))

    kin.OUT.mkdir(parents=True, exist_ok=True)
    (kin.OUT / "collide.json").write_text(json.dumps(report, indent=2))
    print(f"wrote {kin.OUT / 'collide.json'}")
    if problems:
        print(f"{problems} pair(s) closed up — make room in the part, or the "
              f"limit that reaches there is wrong")
        return 1
    print("OK — nothing collides anywhere in the sweep")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
