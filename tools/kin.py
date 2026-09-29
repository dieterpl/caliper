"""Forward kinematics over the declared scene, for the offline tools.

`web/src/viewer/physics.js` poses the model in the browser; nothing did it in
Python, so every static check only ever saw the rest pose. This walks the joint
tree the same way, so `rom.py` can drive a joint through its limits and
`render.py` can draw a configuration that is not the one the model was authored
in.

Two things it also does, which every tool here wanted anyway:

  * `parts()` flattens bodies and decor into one dict with a common shape, so a
    caller does not care which of the two it is holding, and
  * `placements()` returns a world `Location` per part, which is what places
    geometry (`loc * part`) and points (`transform()`) alike.

Angles are in JOINT space, the same frame `out/scene.json` uses: `_rebase()` in
cad/parts/leg.py has already shifted Go2's absolute angles onto the crouch the
model is built in, so 0.0 means "standing", not "legs straight".
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from math import degrees
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from paths import CAD, OUT, ROOT, require_cad  # noqa: E402,F401  (re-exported: tools use kin.OUT)

require_cad()
if str(CAD) not in sys.path:
    sys.path.insert(0, str(CAD))

from build123d import Location, Pos  # noqa: E402

import model  # noqa: F401,E402  (populates SCENE)
from scene import SCENE  # noqa: E402


@dataclass
class Part:
    """One placeable thing: a rigid body, or hardware bolted to one."""
    name: str
    part: object            # build123d solid, in its own local frame
    origin: tuple           # rest world position of that frame
    owner: str              # the rigid body this moves with (itself, if a body)
    kind: str               # "body" | "decor"
    group: str
    color: str | None
    mass: float


def parts() -> dict[str, Part]:
    """Every body and decor, keyed by name."""
    out: dict[str, Part] = {}
    for b in SCENE.bodies:
        out[b.name] = Part(b.name, b.part, tuple(b.origin), b.name, "body",
                           b.group, b.color, b.mass)
    for d in SCENE.decor:
        out[d.name] = Part(d.name, d.part, tuple(d.origin), d.parent, "decor",
                           d.group, d.color, d.mass)
    return out


def joints() -> dict[str, object]:
    """Joints by name. Every joint gets a name at declaration (cad/scene.py)."""
    return {j.name: j for j in SCENE.joints}


def tree() -> tuple[dict[str, tuple[str, object]], dict[str, list[str]]]:
    """(body -> (parent body, joint), body -> child bodies).

    A body with no entry in the first map is a root: `chassis` floats, `ground`
    is welded to nothing. Nothing here checks for cycles because the DSL cannot
    express one — a joint names its child, and a child is declared once.
    """
    parent: dict[str, tuple[str, object]] = {}
    children: dict[str, list[str]] = {}
    for j in SCENE.joints:
        parent[j.b] = (j.a, j)
        children.setdefault(j.a, []).append(j.b)
    return parent, children


def _joint_location(j, theta: float) -> Location:
    """The joint's own motion, about its rest-pose world anchor.

    A revolute joint's `anchor`/`axis` are given in world coordinates at rest
    (see the frame rule in the cad skill), so the rotation is conjugated by the
    anchor: translate to it, spin, translate back.
    """
    if not theta:
        return Location()
    if j.type == "revolute":
        return (Pos(j.anchor)
                * Location((0, 0, 0), j.axis, degrees(theta))
                * Pos(tuple(-c for c in j.anchor)))
    if j.type == "prismatic":
        n = sum(c * c for c in j.axis) ** 0.5 or 1.0
        return Pos(tuple(theta * c / n for c in j.axis))
    return Location()   # fixed joints do not move


def placements(pose: dict[str, float] | None = None) -> dict[str, Location]:
    """World `Location` per part name, for a set of joint angles.

    `pose` maps joint NAME -> angle (radians for revolute, mm for prismatic);
    anything absent is left at zero, which is the pose the model was authored
    in. A part's placement is its chain of joint motions applied to the rest
    origin, so with an empty pose this is exactly `Pos(part.origin)`.
    """
    pose = pose or {}
    unknown = set(pose) - set(joints())
    if unknown:
        raise KeyError(f"no such joint(s): {sorted(unknown)}")

    parent, _ = tree()
    chain: dict[str, Location] = {}

    def frame(bodyname: str) -> Location:
        """Accumulated joint motion above this body."""
        hit = chain.get(bodyname)
        if hit is not None:
            return hit
        link = parent.get(bodyname)
        if link is None:
            loc = Location()
        else:
            up, j = link
            loc = frame(up) * _joint_location(j, pose.get(j.name, 0.0))
        chain[bodyname] = loc
        return loc

    return {p.name: frame(p.owner) * Pos(p.origin) for p in parts().values()}


def subtree(joint_name: str) -> set[str]:
    """Every part name that MOVES when this joint moves — bodies and their decor."""
    j = joints()[joint_name]
    _, children = tree()
    bodies: set[str] = set()
    stack = [j.b]
    while stack:
        n = stack.pop()
        if n in bodies:
            continue
        bodies.add(n)
        stack.extend(children.get(n, ()))
    return {p.name for p in parts().values() if p.owner in bodies}


def matrix(loc: Location):
    """`Location` -> 4x4 numpy matrix, for transforming raw point arrays."""
    import numpy as np
    t = loc.wrapped.Transformation()
    m = np.eye(4)
    for i in range(3):
        for k in range(4):
            m[i, k] = t.Value(i + 1, k + 1)
    return m


def transform(loc: Location, pts):
    """Apply a placement to an Nx3 array of points."""
    import numpy as np
    m = matrix(loc)
    p = np.asarray(pts, dtype=np.float64)
    return p @ m[:3, :3].T + m[:3, 3]


def placed(pose: dict[str, float] | None = None) -> dict[str, object]:
    """Every part as a solid in world space. The expensive one — each call
    transforms real OCCT geometry, so ask for it once and reuse it."""
    locs = placements(pose)
    return {p.name: locs[p.name] * p.part for p in parts().values()}
