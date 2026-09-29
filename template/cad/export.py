"""Run model.py and emit the viewer + physics artifacts.

    out/model.glb   one named mesh node per body (mesh in body-local coords,
                    node translated to the body origin)
    out/model.step  assembled CAD compound for interchange / download
    out/scene.json  the physics graph (settings + bodies + joints) for Rapier
    out/collision.json  per-body convex hull points, for headless simcheck

Run as a fresh process each time (the watch loop does exactly this) so the
module-global SCENE always starts clean.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import trimesh

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = ROOT / "out"

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))


def _hex_to_rgba(h: str) -> list[int]:
    h = h.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return [r, g, b, 255]


_TESS_CACHE: dict = {}


def _tessellate(shape, tol: float = 0.1, ang: float = 0.3):
    """build123d Shape -> (vertices Nx3, faces Mx3).

    Memoised on object identity: parts/hardware.py hands out one shared solid per
    distinct motor/pulley, so twelve motors tessellate once. Safe because nothing
    mutates a part after it is declared -- placement happens via Pos() on a copy.
    """
    key = id(shape)
    hit = _TESS_CACHE.get(key)
    if hit is not None:
        return hit
    verts, tris = shape.tessellate(tol, ang)
    v = np.array([[p.X, p.Y, p.Z] for p in verts], dtype=np.float64)
    f = np.array(tris, dtype=np.int64)
    _TESS_CACHE[key] = (v, f)
    return v, f


def main() -> int:
    OUT.mkdir(exist_ok=True)

    # Importing model.py populates SCENE as a side effect.
    import model  # noqa: F401
    from scene import SCENE

    if not SCENE.bodies:
        print("export: model.py declared no bodies", file=sys.stderr)
        return 1

    gscene = trimesh.Scene()
    scene_json: dict = {"settings": SCENE.settings, "bodies": [], "joints": [], "decor": []}
    if hasattr(SCENE, "project"):
        scene_json["project"] = SCENE.project
    step_solids = []
    hulls: dict[str, list[float]] = {}

    # Decor is bolted to a body, so its mass loads that body. Roll it in before
    # the bodies are serialised, otherwise 5 kg of motors would weigh nothing.
    by_name = {b.name: b for b in SCENE.bodies}
    extra_mass: dict[str, float] = {}
    for d in SCENE.decor:
        if d.parent not in by_name:
            print(f"export: decor {d.name!r} has unknown parent {d.parent!r}", file=sys.stderr)
            return 1
        extra_mass[d.parent] = extra_mass.get(d.parent, 0.0) + d.mass

    for b in SCENE.bodies:
        v, f = _tessellate(b.part)
        mesh = trimesh.Trimesh(vertices=v, faces=f, process=False)
        if b.color:
            mesh.visual.face_colors = _hex_to_rgba(b.color)
        transform = trimesh.transformations.translation_matrix(b.origin)
        gscene.add_geometry(mesh, node_name=b.name, geom_name=b.name, transform=transform)

        # STEP: bake the origin so the compound is assembled in world space.
        from build123d import Pos
        step_solids.append(Pos(b.origin) * b.part)

        # Hull points in body-local coords, so a headless harness can build the
        # same colliders the browser derives from the GLB (tools/simcheck.mjs).
        hulls[b.name] = mesh.convex_hull.vertices.reshape(-1).tolist()

        scene_json["bodies"].append({
            "name": b.name,
            "mesh": b.name,
            "type": b.type,
            "mass": b.mass + extra_mass.get(b.name, 0.0),
            "collider": b.collider,
            "origin": list(b.origin),
            "color": b.color,
            "friction": b.friction,
            "group": b.group,
        })

    # Decor: GLB nodes named "decor:<name>" so the viewer can parent them to
    # their host body. Never colliders, never rigid bodies.
    for d in SCENE.decor:
        v, f = _tessellate(d.part)
        mesh = trimesh.Trimesh(vertices=v, faces=f, process=False)
        if d.color:
            mesh.visual.face_colors = _hex_to_rgba(d.color)
        node = f"decor:{d.name}"
        gscene.add_geometry(mesh, node_name=node, geom_name=node,
                            transform=trimesh.transformations.translation_matrix(d.origin))

        from build123d import Pos
        step_solids.append(Pos(d.origin) * d.part)

        scene_json["decor"].append({
            "name": d.name,
            "mesh": node,
            "parent": d.parent,
            "origin": list(d.origin),
            "mass": d.mass,
            "color": d.color,
            "group": d.group,
        })

    for j in SCENE.joints:
        jd = {"type": j.type, "name": j.name, "a": j.a, "b": j.b,
              "anchor": list(j.anchor), "axis": list(j.axis)}
        if j.motor:
            jd["motor"] = j.motor
        if j.limits:
            jd["limits"] = list(j.limits)
        if j.drive:
            jd["drive"] = j.drive
        scene_json["joints"].append(jd)

    # --- write artifacts ---
    glb_path = OUT / "model.glb"
    gscene.export(glb_path.as_posix())

    try:
        from build123d import Compound, export_step
        export_step(Compound(children=step_solids), (OUT / "model.step").as_posix())
    except Exception as exc:  # STEP is nice-to-have; never block the viewer artifacts
        print(f"export: STEP skipped ({exc})", file=sys.stderr)

    (OUT / "scene.json").write_text(json.dumps(scene_json, indent=2))
    (OUT / "collision.json").write_text(json.dumps(hulls))

    print(f"export: {len(scene_json['bodies'])} bodies, "
          f"{len(scene_json['joints'])} joints, "
          f"{len(scene_json['decor'])} decor -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
