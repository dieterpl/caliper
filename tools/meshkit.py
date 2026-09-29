"""build123d solid -> a mesh you can hand to a slicer, and what is wrong with it.

Two tools need this and they must agree: `printparts.py` writes one STL per
printed part, `bundle.py` writes the whole design in whatever format someone
asked for. If they tessellated differently, the same part would be watertight in
one and not in the other, which is the kind of disagreement nobody debugs.

Nothing here knows what a design is made of — it takes a solid and gives back a
mesh.
"""

from __future__ import annotations

import numpy as np
import trimesh

# Viewer tolerance (0.1 mm / 0.3 rad) shows facets as ridges in a bearing seat,
# so anything meant to be MADE is tessellated an order finer.
TOL, ANG = 0.02, 0.1

MERGE_DIGITS = 5    # 1e-5 mm; far below any feature, far above float noise


def to_mesh(solid, tol: float = TOL, ang: float = ANG):
    """build123d solid -> a WATERTIGHT trimesh.

    `tessellate()` emits each face with its own copy of the shared edge
    vertices, so the raw result is one shell per face -- a 20 mm cube arrives as
    24 vertices and 6 "bodies", and every watertight test fails. Merging on
    position is what stitches it back into a solid, and it must be done with an
    explicit tolerance: the default comparison leaves the duplicates in place.
    Skipping this is how a mesh that looks perfect in a viewer slices into
    nonsense.
    """
    verts, tris = solid.tessellate(tol, ang)
    v = np.array([[p.X, p.Y, p.Z] for p in verts], dtype=np.float64)
    f = np.array(tris, dtype=np.int64)
    m = trimesh.Trimesh(vertices=v, faces=f, process=False)
    m.merge_vertices(digits_vertex=MERGE_DIGITS)
    m.update_faces(m.nondegenerate_faces())
    m.remove_unreferenced_vertices()
    if not m.is_winding_consistent:
        m.fix_normals()
    return m


def check_mesh(mesh) -> list[str]:
    """Everything wrong with a mesh, as a list of short strings."""
    bad = []
    if not mesh.is_watertight:
        bad.append("not watertight")
    if not mesh.is_winding_consistent:
        bad.append("winding inconsistent")
    if mesh.volume <= 0:
        bad.append(f"volume {mesh.volume:.1f} <= 0")
    if mesh.body_count != 1:
        bad.append(f"{mesh.body_count} disconnected bodies")
    return bad
