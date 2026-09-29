#!/usr/bin/env python3
"""Static placement checks on the assembled design.

`simcheck.mjs` answers "does it work?". This answers "is it built somewhere a
real one could bolt to?" — which is the question that went unasked while motors
ended up buried in the chassis, floating above it, and mirrored the wrong way
round on the right-hand legs.

    .venv/bin/python tools/fitcheck.py

Overlaps are found in two stages: a cheap axis-aligned bounding-box sweep, then
a real boolean intersection on whatever survives it. AABBs alone are far too
conservative here — an L-shaped bracket's box swallows everything in its corner —
so the boolean is what decides, and the reported number is solid mm^3 of metal
sharing space with other metal.

Every finding also reports WHERE, because a volume alone cannot be acted on: an
intersection is printed with the centroid and size of each blob of shared solid,
and parts that merely come close are printed with the two facing points and the
gap between them. That pair of points is the useful output — it is where a mount,
a boss or a joint anchor would go. Everything lands in `out/fitcheck.json` as
well, so it can be read as data instead of scraped from this table.

Legitimate overlaps are exempted rather than tolerated, by an explicit list:
  * two bodies joined by a joint (links always overlap at their pivot),
  * a body and the hardware bolted to it,
  * the exemptions a workspace declares in its own `cad/config.py` (see below) —
    parts deliberately placed inside or above the body.
Keep those lists short. Every entry is a check being switched off.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import kin  # noqa: E402  (adds cad/ to the path and populates SCENE)
from scene import SCENE  # noqa: E402

# The can-envelope check only means something for a model that declares what its
# motors are. This tool is shared by every workspace, so a model without them
# skips that section instead of failing to import.
try:
    from config import MOTOR_D, MOTOR_L  # noqa: E402
except ImportError:
    MOTOR_D = MOTOR_L = None

# The exemptions below are one design's vocabulary. This tool is shared by every
# workspace, so it may not carry them: they are read from the workspace's own
# config.py if it declares any.
try:
    import config as _config  # noqa: E402
except ImportError:
    _config = None


def _exempt(name):
    """A tuple of names a workspace exempts, or () if it exempts nothing.

    Defaulting to nothing is the point: a design that says nothing gets every
    check, rather than inheriting some other design's list of parts that are
    allowed to overlap.
    """
    value = getattr(_config, name, None) if _config else None
    return tuple(value) if value else ()

TOL = 0.5          # mm; ignore paper-thin AABB grazes
CAN_SLACK = 20.0   # mm of shaft a motor is allowed to show beyond its can
MIN_VOL = 5.0      # mm^3 of shared solid before it counts as a real clash
# A shaft or belt HAS to enter the part it drives -- that is the coupling, not a
# collision. Anything deeper than this is a part buried in another, not a joint.
COUPLING_VOL = 3000.0
# Groups whose parts drive another part, so shaft or belt entering the thing it
# turns is read as that coupling. e.g. DRIVETRAIN = ("motors", "belts")
DRIVETRAIN = _exempt("DRIVETRAIN")
# How close two parts have to come before the gap between them is worth naming.
# Wide enough to catch "these were meant to bolt together", narrow enough that
# the whole design is not one long list of things near other things.
NEAR_MM = 8.0
# Running clearance allowed between two bodies that pivot against each other.
# Enough for a bearing's outer race to sit between them, tight enough that a
# joint whose bodies simply do not reach each other still shows up.
JOINT_GAP = 3.0
NEAR_SHOWN = 20    # console only; out/fitcheck.json always carries them all

# Parts deliberately housed inside the body, by name suffix and by group — an
# actuator meant to sit in the shell, boards recessed into a deck. Anything not
# named here that intersects the body volume is a mistake.
INSIDE_BODY = _exempt("INSIDE_BODY")
INSIDE_GROUPS = _exempt("INSIDE_GROUPS")
# Groups allowed to break the body's roofline.
ABOVE_BODY = _exempt("ABOVE_BODY")
# Groups whose parts are not single manufactured pieces (a belt is two spans by
# construction), so the one-part-one-solid check does not apply to them.
ONE_PIECE_EXEMPT = _exempt("ONE_PIECE_EXEMPT")
# The part whose volume the two sections above are measured against. A design
# with no such part — most designs — skips both.
BODY_PART = (getattr(_config, "BODY_PART", None) if _config else None) or "chassis"


def aabb(part, origin):
    b = part.bounding_box()
    ox, oy, oz = origin
    return (b.min.X + ox, b.max.X + ox,
            b.min.Y + oy, b.max.Y + oy,
            b.min.Z + oz, b.max.Z + oz)


def intersection(p1, p2):
    """Blobs of solid two placed parts have in common, largest first.

    Each blob is (volume, centre, size) in world mm — which is what turns "these
    two clash" into "these two meet HERE, over a patch this big". None if OCCT
    cannot answer; an empty list means genuinely clear.
    """
    try:
        inter = p1 & p2
    except Exception:  # noqa: BLE001 - a failed boolean is "unknown", not "clear"
        return None
    if inter is None:
        return []
    try:
        solids = inter.solids()
    except Exception:  # noqa: BLE001 - empty results have no solids
        return []
    blobs = []
    for s in solids:
        v = s.volume
        if v <= 0:
            continue
        c, b = s.center(), s.bounding_box()
        blobs.append((v, (c.X, c.Y, c.Z),
                      (b.size.X, b.size.Y, b.size.Z)))
    blobs.sort(key=lambda t: -t[0])
    return blobs


def nearest(p1, p2):
    """(gap, point on p1, point on p2) — the pair of facing points."""
    try:
        d, a, b = p1.distance_to_with_closest_points(p2)
    except Exception:  # noqa: BLE001
        return None
    return d, (a.X, a.Y, a.Z), (b.X, b.Y, b.Z)


def overlap(a, b, tol=TOL):
    """Per-axis overlap depth, or None if the boxes are clear on any axis."""
    d = []
    for i in (0, 2, 4):
        lo, hi = max(a[i], b[i]), min(a[i + 1], b[i + 1])
        if hi - lo <= tol:
            return None
        d.append(hi - lo)
    return d


def box_gap(a, b):
    """Widest per-axis separation of two AABBs; <= 0 means they overlap."""
    return max(max(a[i] - b[i + 1], b[i] - a[i + 1]) for i in (0, 2, 4))


def in_box(pt, box, tol=TOL):
    """Is a world point inside an AABB?"""
    return all(box[2 * k] - tol <= pt[k] <= box[2 * k + 1] + tol for k in range(3))


def fmt_pt(p):
    return f"({p[0]:.1f}, {p[1]:.1f}, {p[2]:.1f})"


def fmt_blob(v, c, s):
    return f"{v:9.0f} mm³ at {fmt_pt(c)}  box {s[0]:.1f}×{s[1]:.1f}×{s[2]:.1f}"


def main() -> int:
    P = kin.parts()
    placed = kin.placed()                       # world geometry, rest pose
    boxes = {n: aabb(p.part, p.origin) for n, p in P.items()}

    # Bodies that are jointed together are *meant* to interpenetrate at the pivot.
    joined = {frozenset((j.a, j.b)) for j in SCENE.joints}

    problems = 0
    report: dict = {"envelope": {}, "pairs": [], "joints": [], "disconnected": []}

    # ------------------------------------------------------------- envelope --
    rob = [b for n, b in boxes.items() if n != "ground"]
    x0, x1 = min(r[0] for r in rob), max(r[1] for r in rob)
    y0, y1 = min(r[2] for r in rob), max(r[3] for r in rob)
    z0, z1 = min(r[4] for r in rob), max(r[5] for r in rob)
    print("=== envelope (ground excluded) ===")
    print(f"  length X {x0:8.1f} ..{x1:8.1f}   = {x1 - x0:7.1f} mm")
    print(f"  width  Y {y0:8.1f} ..{y1:8.1f}   = {y1 - y0:7.1f} mm")
    print(f"  height Z {z0:8.1f} ..{z1:8.1f}   = {z1 - z0:7.1f} mm")
    report["envelope"] = {"x": [x0, x1], "y": [y0, y1], "z": [z0, z1]}

    skew = abs(abs(y0) - abs(y1))
    report["envelope"]["y_skew"] = skew
    if skew > 1.0:
        print(f"  !! ASYMMETRIC about Y by {skew:.1f} mm — a mirrored mount is wrong")
        problems += 1
    else:
        print(f"  symmetric about Y (skew {skew:.2f} mm)")

    # ------------------------------------------------------- motor envelope --
    print("\n=== motors ===")
    if MOTOR_D is None:
        print("  config.py declares no MOTOR_D/MOTOR_L — skipping the can check")
    for name in sorted(P) if MOTOR_D is not None else ():
        if not name.endswith("_motor"):
            continue
        a = boxes[name]
        # The axial extent is the dimension FURTHEST from the can diameter --
        # these are pancakes, so the can is wider than it is long, and sorting by
        # size picks out two diameters and calls the larger one the length.
        dims = [a[1] - a[0], a[3] - a[2], a[5] - a[4]]
        ax = max(range(3), key=lambda i: abs(dims[i] - MOTOR_D))
        length = dims[ax]
        girth = max(dims[i] for i in range(3) if i != ax)
        bad = length > MOTOR_L + CAN_SLACK + TOL or abs(girth - MOTOR_D) > 2.0
        print(f"  {name:22} Ø{girth:5.1f} × {length:5.1f} long"
              f"   {'!! expected Ø%.0f × %.0f' % (MOTOR_D, MOTOR_L) if bad else ''}")
        problems += bad

    # -------------------------------------------------- one part, one solid --
    # A body fused from primitives that never touch is several disconnected
    # lumps. Physics cannot tell (one rigid body, one hull) and neither can the
    # viewer, but it is not a thing anyone can make -- the motor beam floated
    # 12 mm off its bracket like this, and the head's neck stopped 1 mm short of
    # the skull.
    print("\n=== disconnected parts ===")
    loose = 0
    for name in sorted(P):
        p = P[name]
        # A belt IS two spans by construction: `belt()` draws the straight runs
        # and leaves the wrap to the pulley solids.
        if p.group in ONE_PIECE_EXEMPT or p.part is None:
            continue
        n = len(p.part.solids())
        if n > 1:
            vols = sorted((s.volume for s in p.part.solids()), reverse=True)
            report["disconnected"].append({"name": name, "solids": n,
                                           "volumes": vols})
            print(f"  !! {name:22} is {n} separate solids"
                  f"   {', '.join(f'{v:.0f}' for v in vols[:4])} mm³")
            loose += 1
    print("  none" if not loose else "")
    problems += loose

    # ------------------------------------------------------ inside the body --
    body_box = boxes.get(BODY_PART)
    if body_box:
        print(f"\n=== parts intersecting the {BODY_PART} volume ===")
        found = False
        for name in sorted(P):
            p = P[name]
            if name in (BODY_PART, "ground"):
                continue
            if (INSIDE_BODY and name.endswith(INSIDE_BODY)) or p.group in INSIDE_GROUPS:
                continue
            if frozenset((p.owner, BODY_PART)) in joined:
                continue
            a = boxes[name]
            if overlap(a, body_box):
                print(f"  !! {name:22} owner={p.owner:12} Y {a[2]:7.1f}..{a[3]:7.1f}"
                      f"  Z {a[4]:7.1f}..{a[5]:7.1f}")
                found = True
                problems += 1
        if not found:
            print("  none")

        top = body_box[5]
        above = [(n, boxes[n][5]) for n in P
                 if boxes[n][5] > top + TOL and P[n].group not in ABOVE_BODY]
        print(f"\n=== above the {BODY_PART} top ({top:.1f}) ===")
        for n, z in sorted(above, key=lambda t: -t[1]):
            print(f"  !! {n:22} reaches Z {z:7.1f}")
            problems += 1
        if not above:
            print("  none")

    # ------------------------------------------------------- jointed pairs --
    # The clearance map below EXEMPTS jointed bodies, on the grounds that links
    # overlap at their pivot. That exemption hid three interferences at once --
    # the shank inside the fork plates (8223 mm^3), the bracket arm through the
    # inner plate (8615) and the chassis boss inside the bracket hub (4524) --
    # every one of them two concentric parts that ROTATE against each other. So
    # the pair is measured here instead of ignored.
    print("\n=== jointed pairs (these rotate against each other) ===")
    rotating = 0
    for j in SCENE.joints:
        if j.type == "fixed" or j.a not in placed or j.b not in placed:
            continue
        if "ground" in (j.a, j.b):
            continue
        blobs = intersection(placed[j.a], placed[j.b])
        if blobs is None:
            print(f"  ?? {j.a:12} vs {j.b:12}  boolean failed, inspect by hand")
            rotating += 1
            continue
        vol = sum(v for v, _c, _s in blobs)
        if vol > MIN_VOL:
            report["pairs"].append({
                "a": j.a, "b": j.b, "kind": "rotating", "joint": j.name,
                "volume": vol,
                "blobs": [{"volume": v, "center": list(c), "size": list(s)}
                          for v, c, s in blobs]})
            print(f"  !! {j.a:12} vs {j.b:12}  {vol:9.0f} mm³ shared at the rest pose"
                  f"   {fmt_blob(*blobs[0])}")
            rotating += 1
    print("  none" if not rotating else "")
    problems += rotating

    # -------------------------------------------------------- clearance map --
    print("\n=== overlaps between parts with different owners ===")
    names = sorted(P)
    hits = clear = 0
    couplings = []
    near = []
    for i, n1 in enumerate(names):
        if n1 == "ground":
            continue
        p1, a1 = P[n1], boxes[n1]
        for n2 in names[i + 1:]:
            p2, a2 = P[n2], boxes[n2]
            if n2 == "ground" or p1.owner == p2.owner:
                continue
            # Two jointed BODIES are meant to interpenetrate at their pivot. That
            # licence does not extend to the hardware bolted to them: a motor has
            # no business inside the neighbouring link.
            jointed = frozenset((n1, n2)) in joined
            if p1.kind == "body" and p2.kind == "body" and jointed:
                continue
            # A drivetrain is meant to touch itself: belts wrap their pulleys, and
            # a belt spanning two links necessarily reaches both ends.
            if p1.group == "belts" and p2.group == "belts":
                continue
            if not overlap(a1, a2):
                # Not touching -- but if the boxes are close, WHERE they come
                # closest is exactly the information a connection point needs.
                gap = box_gap(a1, a2)
                if gap <= NEAR_MM:
                    got = nearest(placed[n1], placed[n2])
                    if got and got[0] <= NEAR_MM:
                        near.append((got[0], n1, n2, got[1], got[2]))
                        report["pairs"].append({
                            "a": n1, "b": n2, "kind": "near",
                            "distance": got[0], "closest": [got[1], got[2]],
                        })
                continue
            blobs = intersection(placed[n1], placed[n2])
            drives = (p1.group in DRIVETRAIN and p2.group == "links") or \
                     (p2.group in DRIVETRAIN and p1.group == "links")
            if blobs is None:
                print(f"  ?? {n1:22} × {n2:22}  boolean failed, inspect by hand")
                report["pairs"].append({"a": n1, "b": n2, "kind": "unknown"})
                hits += 1
                continue
            vol = sum(b[0] for b in blobs)
            entry = {"a": n1, "b": n2, "volume": vol,
                     "blobs": [{"volume": v, "center": list(c), "size": list(s)}
                               for v, c, s in blobs]}
            if drives and MIN_VOL < vol <= COUPLING_VOL:
                entry["kind"] = "coupling"
                couplings.append((n1, n2, blobs))
            elif vol > MIN_VOL:
                entry["kind"] = "clash"
                print(f"  !! {n1:22} × {n2:22}  {len(blobs)} blob(s)")
                for v, c, s in blobs:
                    print(f"       {fmt_blob(v, c, s)}")
                hits += 1
            else:
                entry["kind"] = "contact"
                clear += 1
            report["pairs"].append(entry)
    print(f"  {hits} real clash(es); {clear} AABB candidate(s) cleared by boolean"
          if hits or clear else "  none")
    problems += hits

    if couplings:
        print("\n=== drive couplings (a shaft/belt entering what it drives) ===")
        for n1, n2, blobs in couplings:
            v, c, s = blobs[0]
            print(f"  {n1:22} → {n2:22}  {fmt_blob(v, c, s)}")

    # -------------------------------------------------------- near misses ----
    # Not a fault: this is the map of what is close to what, and the two points
    # named on each line are where those parts face each other.
    if near:
        near.sort()
        print(f"\n=== parts within {NEAR_MM:.0f} mm (candidate connection points) ===")
        for d, n1, n2, pa, pb in near[:NEAR_SHOWN]:
            print(f"  {n1:22} ~ {n2:22} {d:6.2f} mm  "
                  f"{fmt_pt(pa)} -> {fmt_pt(pb)}")
        if len(near) > NEAR_SHOWN:
            print(f"  ... {len(near) - NEAR_SHOWN} more, see out/fitcheck.json")

    # ------------------------------------------------------- joint anchors ---
    # A joint whose two bodies do not touch is a mechanism with a gap in it: the
    # solver happily welds them across thin air, so nothing downstream notices.
    print("\n=== joints ===")
    for j in SCENE.joints:
        if j.a not in placed or j.b not in placed:
            print(f"  !! {j.name:16} names an unknown body ({j.a} / {j.b})")
            problems += 1
            continue
        got = nearest(placed[j.a], placed[j.b])
        d = got[0] if got else None
        inside = [n for n in (j.a, j.b) if in_box(j.anchor, boxes[n])]
        rec = {"name": j.name, "type": j.type, "a": j.a, "b": j.b,
               "anchor": list(j.anchor), "distance": d,
               "anchor_inside": inside}
        report["joints"].append(rec)
        # A FIXED joint's bodies should meet. A revolute's must NOT: they turn
        # against each other, so the metal has to clear and a bearing carries the
        # load across the gap. Wanting them to touch is what left the chassis
        # boss 4524 mm³ inside the bracket hub, so the two rules differ.
        limit = TOL if j.type == "fixed" else JOINT_GAP
        if d is None:
            print(f"  ?? {j.name:16} distance query failed")
        elif d > limit:
            print(f"  !! {j.name:16} {j.a} and {j.b} are {d:.1f} mm APART"
                  f"  (nearest {fmt_pt(got[1])})")
            problems += 1
        elif not inside:
            print(f"  !! {j.name:16} anchor {fmt_pt(j.anchor)} lies outside both bodies")
            problems += 1
        else:
            print(f"  {j.name:16} bodies meet at the anchor")

    kin.OUT.mkdir(parents=True, exist_ok=True)
    (kin.OUT / "fitcheck.json").write_text(json.dumps(report, indent=2))
    print(f"\nwrote {kin.OUT / 'fitcheck.json'}")
    print(f"{'OK' if not problems else f'{problems} placement problem(s)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
