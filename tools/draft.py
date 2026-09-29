#!/usr/bin/env python3
"""A three-view drawing of the design — as terminal text, or as a vector sheet.

`render.py` draws the model to a PNG, which the agent editing the CAD can read
through its image tool. This is the other two things a PNG is bad at:

  * seeing it with NO tool at all — the drawing printed straight into the
    terminal, in characters, where an agent working blind can just read it, and
  * a real DRAWING — the three standard views as clean vector line-art on one
    sheet, third-angle and to a single scale, that scales and prints without
    turning to mush the way a raster view does.

    caliper draft                     # six orthographic views as ASCII, to stdout
    caliper draft --out drawing.art   # the same as a .art file the app renders
    caliper draft --svg               # the same views as out/views/model.svg
    caliper draft --only 'fl_*'       # just one sub-assembly
    caliper draft --pose fl_knee=-30  # a configuration other than the rest pose
    caliper draft --svg --no-hidden   # visible edges only, no dashed lines

ASCII is the default because it needs nothing to look at — no browser, no image
viewer, no file to open. It is coarse; it is meant to answer "are the three
views roughly sane" in one glance, not to be measured. `--svg` is the opposite:
precise, scalable, printable, but the agent cannot SEE it (to a text tool an SVG
is a list of path coordinates), so it is for you and for handoff, not for the
loop.

Both are ORTHOGRAPHIC and share ONE scale across the three views, so a size in
one view is the same number of millimetres in the next. The SVG lays them out
in third angle — top above front, right beside it — with the columns and rows
that align a real drawing, a title block, and hidden edges dashed.

The line-art is silhouette + crease edges (a smooth cylinder shows its outline,
not its facets), with hidden portions found by z-testing each edge against a
depth buffer of the whole model — the same trick render.py's rasterizer uses,
turned to the question "is this edge behind something".
"""

from __future__ import annotations

import argparse
import datetime
import sys
from collections import defaultdict
from fnmatch import fnmatch
from math import cos, radians
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import kin      # noqa: E402  (adds cad/ to the path and populates SCENE)
import raster   # noqa: E402

# Finer than render.py's coarse-for-the-rasterizer tessellation: line-art needs
# smooth silhouettes and a facet angle well under the crease threshold, so the
# flats of a cylinder do not each draw an edge.
TESS_TOL, TESS_ANG = 0.4, 0.3

LIGHT = np.array([0.35, 0.55, 0.75])
LIGHT /= np.linalg.norm(LIGHT)
AMBIENT = 0.34
RAMP = ".:-=+*#%@"          # covered cell, dim surface -> bright surface
CHAR_ASPECT = 0.5          # a terminal cell is ~twice as tall as it is wide

# view -> (right axis, up axis, look-into-screen axis, label). Every basis is
# right-handed (right×up points back at the camera), so no view is mirrored — and
# front/top/right are also signed so they UNFOLD in third angle for the SVG
# sheet: front and top share the Y axis, front and right share Z, top and right
# share X. The opposite three (back/left/bottom) are their mirrors.
VIEWS = {
    "front":  (np.array([0.0, 1, 0]),  np.array([0.0, 0, 1]),  np.array([-1.0, 0, 0]), "FRONT"),
    "back":   (np.array([0.0, -1, 0]), np.array([0.0, 0, 1]),  np.array([1.0, 0, 0]),  "BACK"),
    "left":   (np.array([1.0, 0, 0]),  np.array([0.0, 0, 1]),  np.array([0.0, 1, 0]),  "LEFT"),
    "right":  (np.array([-1.0, 0, 0]), np.array([0.0, 0, 1]),  np.array([0.0, -1, 0]), "RIGHT"),
    "top":    (np.array([0.0, 1, 0]),  np.array([-1.0, 0, 0]), np.array([0.0, 0, -1]), "TOP"),
    "bottom": (np.array([0.0, 1, 0]),  np.array([1.0, 0, 0]),  np.array([0.0, 0, 1]),  "BOTTOM"),
}
ORDER = ["front", "top", "right"]                                  # the SVG sheet
ASCII_ORDER = ["front", "back", "left", "right", "top", "bottom"]  # the .art file


def look_desc(look) -> str:
    """'looking -Z' etc. — which way the camera faces, for a view's marker."""
    ax = int(np.argmax(np.abs(look)))
    return f"looking {'+' if look[ax] > 0 else '-'}{'XYZ'[ax]}"


# ----------------------------------------------------------------- geometry --
_TESS: dict = {}


def mesh(part):
    """(vertices, faces) in the part's own frame, memoised by identity."""
    hit = _TESS.get(id(part))
    if hit is None:
        v, f = part.tessellate(TESS_TOL, TESS_ANG)
        hit = (np.array([[p.X, p.Y, p.Z] for p in v], float),
               np.array(f, np.int64))
        _TESS[id(part)] = hit
    return hit


def visible(P, only, hide):
    """Part names surviving the --only / --hide globs (name or group)."""
    def match(p, pats):
        return any(fnmatch(p.name, g) or fnmatch(p.group, g) for g in pats)
    return sorted(n for n, p in P.items()
                  if (not only or match(p, only)) and not (hide and match(p, hide)))


def parse_pose(spec):
    if not spec:
        return {}
    pose = {}
    for item in spec.split(","):
        name, _, val = item.partition("=")
        if not val:
            raise SystemExit(f"draft: --pose wants joint=degrees, got {item!r}")
        pose[name.strip()] = radians(float(val))
    return pose


def geometry(P, pose, names):
    """World meshes: a list of (vertices Nx3, faces Mx3), one per drawn part."""
    locs = kin.placements(pose)
    out = []
    for n in names:
        v, f = mesh(P[n].part)
        if len(f):
            out.append((kin.transform(locs[n], v), f))
    return out


def face_normals(vw, f):
    n = np.cross(vw[f[:, 1]] - vw[f[:, 0]], vw[f[:, 2]] - vw[f[:, 0]])
    ln = np.linalg.norm(n, axis=1, keepdims=True)
    return n / np.where(ln == 0, 1, ln)


def part_edges(vw, f, crease_cos):
    """Feature edges of one part, as parallel arrays.

    An edge is kept-always (P0,P1,ALWAYS=True) when it is a boundary/non-manifold
    edge or a crease (dihedral sharper than the threshold); those do not depend
    on the view. Manifold edges carry their two face normals so the caller can
    add the view-dependent silhouette edges on top.
    """
    fn = face_normals(vw, f)
    emap: dict[tuple[int, int], list[int]] = defaultdict(list)
    for fi, (i, j, k) in enumerate(f.tolist()):
        for a, b in ((i, j), (j, k), (k, i)):
            emap[(a, b) if a < b else (b, a)].append(fi)

    P0, P1, N0, N1, AL = [], [], [], [], []
    nan = (np.nan, np.nan, np.nan)
    for (a, b), faces in emap.items():
        P0.append(vw[a]); P1.append(vw[b])
        if len(faces) != 2:
            N0.append(nan); N1.append(nan); AL.append(True)
        else:
            n0, n1 = fn[faces[0]], fn[faces[1]]
            N0.append(n0); N1.append(n1)
            AL.append(bool(np.dot(n0, n1) < crease_cos))
    if not P0:
        z = np.zeros((0, 3))
        return z, z, z, z, np.zeros(0, bool)
    return (np.array(P0), np.array(P1), np.array(N0), np.array(N1),
            np.array(AL, bool))


def all_edges(parts_wf, crease_cos):
    """part_edges over every part, concatenated."""
    chunks = [part_edges(vw, f, crease_cos) for vw, f in parts_wf]
    return tuple(np.concatenate([c[i] for c in chunks]) for i in range(5))


def project(pts, view):
    right, up, look, _ = view
    return pts @ right, pts @ up, pts @ look


def frame_of(allV, view):
    """(umin, umax, vmin, vmax) of the model in one view's screen plane."""
    u, w, _ = project(allV, view)
    return u.min(), u.max(), w.min(), w.max()


# ----------------------------------------------------------------- occlusion --
def depth_buffer(parts_wf, view, umin, vmax, scale, rw, rh):
    """A z-buffer of the whole model in one view, at `scale` px/mm."""
    right, up, look, _ = view
    canvas = raster.Canvas(rw, rh, (0, 0, 0))
    for vw, f in parts_wf:
        tri = vw[f]
        v = tri.reshape(-1, 3)
        px = (v @ right - umin) * scale
        py = (vmax - v @ up) * scale
        pz = v @ look
        scr = np.stack([px, py, pz], 1).reshape(-1, 3, 3)
        canvas.triangles(scr, np.zeros((len(tri), 3), np.uint8))
    return canvas.z          # flat rh*rw, +inf where nothing was drawn


def view_segments(P0, P1, view, zbuf, fr, scale, rw, rh, bias, box, S,
                  want_hidden, K=16):
    """A view's edges as (visible Nx4, hidden Mx4) segments, in sheet coords.

    Every kept edge is sampled at K points and z-tested against the depth buffer
    (a sample is visible when it is at or in front of the nearest surface, or
    over background). The samples are then collapsed into maximal
    same-visibility runs — so a fully visible edge stays one line, and a
    partially hidden one splits into a solid piece and a dashed piece — and each
    run is mapped straight into the sheet. All vectorised: a full assembly is
    tens of thousands of edges.
    """
    right, up, look, _ = view
    umin, umax, vmin, vmax = fr
    bx, by = box
    empty = np.zeros((0, 4))
    if len(P0) == 0:
        return empty, empty

    D = P1 - P0
    tmid = (np.arange(K) + 0.5) / K
    smp = P0[:, None, :] + tmid[None, :, None] * D[:, None, :]     # (E,K,3)
    u = smp @ right; w = smp @ up; z = smp @ look
    px = np.clip(((u - umin) * scale).astype(int), 0, rw - 1)
    py = np.clip(((vmax - w) * scale).astype(int), 0, rh - 1)

    # An edge on the model's outline projects onto the very boundary of the
    # depth buffer, where point-sampling can leave a one-pixel gap — reading
    # that gap as background would call a FAR outline edge "visible". So when the
    # sample's own pixel is empty, fall back to the nearest surface in a
    # plus-shaped neighbourhood (enough to bridge an axis-aligned gap); only
    # genuine background (pixel and neighbours empty) counts as nothing-behind.
    # The pixel's own z is used when it has one, so a curved silhouette (buffer
    # covered right up to the edge) is unaffected.
    def at(dx, dy):
        return zbuf[np.clip(py + dy, 0, rh - 1) * rw + np.clip(px + dx, 0, rw - 1)]
    center = at(0, 0)
    window = np.stack([center, at(-1, 0), at(1, 0), at(0, -1), at(0, 1)])
    near = np.where(np.isfinite(window), window, np.inf).min(0)
    zb = np.where(np.isfinite(center), center, near)
    vis = ~np.isfinite(zb) | (z <= zb + bias)                     # (E,K)

    # Maximal runs, vectorised: a run starts at column 0 and at every change of
    # visibility. np.nonzero yields the starts row-major (edge, then column), so
    # each run ends where the next start is — or at K, at an edge boundary.
    E = len(P0)
    start = np.ones((E, K), bool)
    start[:, 1:] = vis[:, 1:] != vis[:, :-1]
    ee, ii = np.nonzero(start)
    nxt = np.empty(len(ii), np.int64); nxt[:-1] = ii[1:]; nxt[-1] = K
    same = np.zeros(len(ee), bool); same[:-1] = ee[1:] == ee[:-1]
    end = np.where(same, nxt, K)
    t0 = (ii / K)[:, None]; t1 = (end / K)[:, None]
    seen = vis[ee, ii]

    A = P0[ee] + t0 * D[ee]
    B = P0[ee] + t1 * D[ee]
    segs = np.stack([bx + (A @ right - umin) * S, by + (vmax - A @ up) * S,
                     bx + (B @ right - umin) * S, by + (vmax - B @ up) * S], 1)
    return segs[seen], (segs[~seen] if want_hidden else empty)


# --------------------------------------------------------------------- ASCII --
def ascii_view(parts_wf, view, mm_per_col, aspect):
    """One view as a list of text lines, at the shared scale mm_per_col.

    `aspect` is the display cell's height/width: 2 for a terminal (chars are
    ~twice as tall as wide), 1 for the app's square grid cells. A row therefore
    spans `aspect * mm_per_col` mm, which is what keeps proportions honest.
    """
    right, up, look, _ = view
    umin_v, umax_v, wmin_v, wmax_v = frame_of(
        np.vstack([vw for vw, _ in parts_wf]), view)
    cols = max(1, round((umax_v - umin_v) / mm_per_col))
    rows = max(1, round((wmax_v - wmin_v) / (aspect * mm_per_col)))

    canvas = raster.Canvas(cols, rows, (0, 0, 0))
    for vw, f in parts_wf:
        tri = vw[f]
        n = face_normals(vw, f)
        lum = (255 * (AMBIENT + (1 - AMBIENT)
                      * np.clip(np.abs(n @ LIGHT), 0, 1))).astype(np.uint8)
        v = tri.reshape(-1, 3)
        px = (v @ right - umin_v) / mm_per_col
        py = (wmax_v - v @ up) / (aspect * mm_per_col)
        pz = v @ look
        scr = np.stack([px, py, pz], 1).reshape(-1, 3, 3)
        canvas.triangles(scr, np.repeat(lum[:, None], 3, 1))

    grey = canvas.rgb[:, :, 0].astype(float)
    covered = np.isfinite(canvas.z.reshape(rows, cols))
    lo, hi = 255 * AMBIENT * 0.9, 255.0
    t = np.clip((grey - lo) / max(hi - lo, 1), 0, 1)
    idx = np.clip((t * (len(RAMP) - 1)).astype(int), 0, len(RAMP) - 1)
    lines = []
    for r in range(rows):
        lines.append("".join(RAMP[idx[r, c]] if covered[r, c] else " "
                             for c in range(cols)).rstrip())
    return lines


def render_ascii(parts_wf, views, spans, name, pose, cols_budget, aspect):
    """The whole document: a legend, then each view under a `=== VIEW: … ===`
    marker. One scale for every view, so a size in one reads the same in the
    next, and `aspect` (cell height/width) keeps proportions right."""
    Yspan, Xspan, Zspan = spans
    allV = np.vstack([vw for vw, _ in parts_wf])

    def uspan(k):
        umin, umax, *_ = frame_of(allV, VIEWS[k])
        return umax - umin
    mm_per_col = max(uspan(k) for k in views) / max(1, cols_budget)

    # Legend: letters only, so the grid renderer shows it as readable text, not
    # as filled cells the way it paints the drawing characters.
    out = [
        f"DRAFT  {name}",
        f"scale  1 cell = {mm_per_col:.1f} mm   (square cells, {aspect:g} to 1)",
        f"bbox   {Yspan:.0f} wide  {Xspan:.0f} deep  {Zspan:.0f} tall   mm",
        f"views  {', '.join(VIEWS[k][3].lower() for k in views)}",
    ]
    if pose:
        out.append("pose   " + ", ".join(f"{k} {round(np.degrees(v))}"
                                          for k, v in pose.items()))
    for k in views:
        look, label = VIEWS[k][2], VIEWS[k][3]
        out.append("")
        out.append(f"=== VIEW: {label} ({look_desc(look)}) ===")
        out.extend(ascii_view(parts_wf, VIEWS[k], mm_per_col, aspect))
    return "\n".join(out) + "\n"


# ----------------------------------------------------------------------- SVG --
def nice_len(target):
    """A round number of mm not larger than `target` (for the scale bar)."""
    for step in (1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000):
        if step > target:
            break
        good = step
    return good if target >= 1 else 1


def path_data(segs):
    """SVG path data from an (N, 4) array of x0,y0,x1,y1 segments (vectorised —
    a complex assembly is hundreds of thousands of segments)."""
    if len(segs) == 0:
        return ""
    c = [np.char.mod("%.1f", segs[:, i]) for i in range(4)]
    d = np.char.add(np.char.add("M", c[0]), np.char.add(" ", c[1]))
    d = np.char.add(d, np.char.add(np.char.add("L", c[2]), np.char.add(" ", c[3])))
    return "".join(d.tolist())


def render_svg(parts_wf, views, spans, name, pose, size, crease_cos, hidden):
    Yspan, Xspan, Zspan = spans
    allV = np.vstack([vw for vw, _ in parts_wf])
    zrange = float(np.ptp(allV @ np.array([1.0, 1, 1])))  # rough model extent
    P0, P1, N0, N1, AL = all_edges(parts_wf, crease_cos)

    big = max(Yspan, Xspan, Zspan, 1.0)
    Mmm = 0.10 * big                     # sheet margin
    Gmm = 0.09 * big                     # gap between views
    sheetW_mm = Mmm + Yspan + Gmm + Xspan + Mmm
    sheetH_mm = Mmm + Xspan + Gmm + Zspan + Mmm
    S = size / max(sheetW_mm, sheetH_mm)
    W, H = sheetW_mm * S, sheetH_mm * S

    # Per-view: its frame, and where its box sits on the sheet. front and top
    # share the left edge and the Y axis; front and right share the top edge and
    # the Z axis — that shared placement is what makes the views line up.
    box = {}
    fr = {k: frame_of(allV, VIEWS[k]) for k in ORDER}
    top_y = Mmm * S
    row2_y = (Mmm + Xspan + Gmm) * S
    left_x = Mmm * S
    right_x = (Mmm + Yspan + Gmm) * S
    box["top"] = (left_x, top_y)
    box["front"] = (left_x, row2_y)
    box["right"] = (right_x, row2_y)

    parts_svg = []
    ink = max(0.7, min(W, H) * 0.0016)
    bias = max(0.3, 0.006 * max(zrange, 1.0))

    for k in views:
        umin, umax, vmin, vmax = fr[k]
        bx, by = box[k]
        uspan, vspan = umax - umin, vmax - vmin

        # depth buffer for this view (independent of the sheet resolution)
        res = 800
        bscale = (res - 1) / max(uspan, vspan, 1e-6)
        rw = max(1, int(uspan * bscale) + 1)
        rh = max(1, int(vspan * bscale) + 1)
        zbuf = depth_buffer(parts_wf, VIEWS[k], umin, vmax, bscale, rw, rh)

        # which edges this view draws: always-kept, plus silhouettes
        look = VIEWS[k][2]
        with np.errstate(invalid="ignore"):
            sil = (N0 @ look) * (N1 @ look) < 0
        keep = AL | sil
        vis_segs, hid_segs = view_segments(
            P0[keep], P1[keep], VIEWS[k], zbuf, fr[k], bscale, rw, rh, bias,
            box[k], S, hidden)

        parts_svg.append(
            f'  <rect class="vp" x="{bx:.1f}" y="{by:.1f}" '
            f'width="{uspan * S:.1f}" height="{vspan * S:.1f}"/>')
        parts_svg.append(
            f'  <text class="lbl" x="{bx + 3:.1f}" y="{by - 4:.1f}">{VIEWS[k][3]}</text>')
        if len(hid_segs):
            parts_svg.append(f'  <path class="hid" d="{path_data(hid_segs)}"/>')
        if len(vis_segs):
            parts_svg.append(f'  <path class="vis" d="{path_data(vis_segs)}"/>')

    # title block, in the empty quadrant above the right view
    tb_x, tb_y = right_x, top_y
    tb_w, tb_h = Xspan * S, Xspan * S
    fs = max(9.0, min(W, H) * 0.020)
    lines = [
        (name.upper(), fs * 1.15, "700"),
        ("3-VIEW  ·  THIRD ANGLE", fs, "400"),
        (f"{Yspan:.0f} W × {Xspan:.0f} D × {Zspan:.0f} H mm", fs, "400"),
    ]
    if pose:
        lines.append(("POSE " + ", ".join(f"{k}={round(np.degrees(v))}"
                                           for k, v in pose.items()), fs * 0.85, "400"))
    lines.append((datetime.date.today().isoformat(), fs * 0.85, "400"))

    tb = [f'  <rect class="tb" x="{tb_x:.1f}" y="{tb_y:.1f}" '
          f'width="{tb_w:.1f}" height="{tb_h:.1f}"/>']
    ty = tb_y + fs * 1.6
    for text, sz, weight in lines:
        tb.append(f'  <text class="ti" x="{tb_x + fs * 0.6:.1f}" y="{ty:.1f}" '
                  f'font-size="{sz:.1f}" font-weight="{weight}">{text}</text>')
        ty += sz * 1.7

    # a scale bar along the bottom of the title block
    bar_mm = nice_len(Xspan * 0.6)
    bar_px = bar_mm * S
    bx0 = tb_x + fs * 0.6
    by0 = tb_y + tb_h - fs * 1.2
    tb.append(f'  <path class="vis" d="M{bx0:.1f} {by0:.1f}L{bx0 + bar_px:.1f} {by0:.1f}'
              f'M{bx0:.1f} {by0 - 4:.1f}L{bx0:.1f} {by0 + 4:.1f}'
              f'M{bx0 + bar_px:.1f} {by0 - 4:.1f}L{bx0 + bar_px:.1f} {by0 + 4:.1f}"/>')
    tb.append(f'  <text class="ti" x="{bx0:.1f}" y="{by0 - fs * 0.5:.1f}" '
              f'font-size="{fs * 0.85:.1f}" font-weight="400">{bar_mm:g} mm</text>')

    style = f"""
    .vis {{ fill:none; stroke:#161616; stroke-width:{ink:.2f};
            stroke-linecap:round; stroke-linejoin:round; }}
    .hid {{ fill:none; stroke:#9aa1ab; stroke-width:{ink * 0.75:.2f};
            stroke-dasharray:{ink * 4:.1f} {ink * 3:.1f}; stroke-linecap:round; }}
    .vp  {{ fill:none; stroke:#e3e3e3; stroke-width:{ink * 0.6:.2f}; }}
    .tb  {{ fill:none; stroke:#c8c8c8; stroke-width:{ink * 0.8:.2f}; }}
    .lbl {{ fill:#444; font:600 {fs * 0.9:.1f}px monospace; }}
    .ti  {{ fill:#222; font-family:monospace; }}"""

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W:.1f} {H:.1f}" '
        f'font-family="monospace">\n'
        f'  <style>{style}\n  </style>\n'
        f'  <rect x="0" y="0" width="{W:.1f}" height="{H:.1f}" fill="#ffffff"/>\n'
        f'  <rect x="{ink * 4:.1f}" y="{ink * 4:.1f}" '
        f'width="{W - ink * 8:.1f}" height="{H - ink * 8:.1f}" '
        f'fill="none" stroke="#333" stroke-width="{ink:.2f}"/>\n'
        + "\n".join(parts_svg) + "\n"
        + "\n".join(tb) + "\n</svg>\n")


# --------------------------------------------------------------------- main --
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--svg", action="store_true",
                    help="write a vector sheet instead of printing ASCII")
    ap.add_argument("--out", default=None,
                    help="write to a file instead of stdout: a .art grid the app "
                         "renders (ASCII mode), or the SVG (default out/views/model.svg)")
    ap.add_argument("--view", default="all",
                    help="front|back|left|right|top|bottom, comma-separated, or all "
                         "(default all: six views for ASCII, front/top/right for --svg)")
    ap.add_argument("--pose", default=None,
                    help="joint=DEGREES,... — zero is the authored rest pose")
    ap.add_argument("--only", action="append", help="glob on part name or group")
    ap.add_argument("--hide", action="append", help="glob on part name or group")
    ap.add_argument("--ground", action="store_true",
                    help="include the floor (a 40 m slab: it frames out the design)")
    ap.add_argument("--cols", type=int, default=58,
                    help="ASCII width of the widest view, in characters")
    ap.add_argument("--size", type=int, default=1000,
                    help="SVG sheet, longest edge in px (it is vector: this only "
                         "sets stroke and text proportions)")
    ap.add_argument("--crease", type=float, default=35.0,
                    help="dihedral angle (deg) above which an edge is drawn")
    ap.add_argument("--hidden", action=argparse.BooleanOptionalAction, default=True,
                    help="dash the edges hidden behind the model (SVG only)")
    args = ap.parse_args()

    P = kin.parts()
    pose = parse_pose(args.pose)
    names = visible(P, args.only, args.hide)
    if not args.ground:
        names = [n for n in names if P[n].group != "ground"]
    if not names:
        print("draft: --only/--hide left nothing to draw", file=sys.stderr)
        return 2

    parts_wf = geometry(P, pose, names)
    if not parts_wf:
        print("draft: nothing tessellated to draw", file=sys.stderr)
        return 2

    default_views = ORDER if args.svg else ASCII_ORDER
    want = default_views if args.view == "all" else [v.strip() for v in args.view.split(",")]
    bad = [v for v in want if v not in VIEWS]
    if bad:
        raise SystemExit(f"draft: unknown view(s) {bad}; have {list(VIEWS)}")
    if args.svg:
        # The third-angle sheet only lays out front/top/right; keep just those.
        want = [v for v in want if v in ORDER] or list(ORDER)

    allV = np.vstack([vw for vw, _ in parts_wf])
    Yspan = float(np.ptp(allV @ VIEWS["front"][0]))   # Y
    Zspan = float(np.ptp(allV @ VIEWS["front"][1]))   # Z
    Xspan = float(np.ptp(allV @ VIEWS["right"][0]))   # X
    spans = (Yspan, Xspan, Zspan)
    name = kin.ROOT.name

    if args.svg:
        svg = render_svg(parts_wf, want, spans, name, pose, args.size,
                         cos(radians(args.crease)), args.hidden)
        out = Path(args.out) if args.out else kin.OUT / "views" / "model.svg"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(svg)
        print(f"draft: wrote {out}  ({len(svg)} bytes, {len(want)} views)")
    else:
        # A .art for the app's square cells renders at 1:1; the terminal is ~2:1.
        art = render_ascii(parts_wf, want, spans, name, pose, args.cols,
                           1.0 if args.out else 2.0)
        if args.out:
            # A .art file the web app opens as an editable grid — the same
            # format a hand-drawn one uses, so a generated view can be tweaked.
            out = Path(args.out)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(art)
            print(f"draft: wrote {out}  ({len(art)} bytes, {len(want)} views)")
        else:
            sys.stdout.write(art)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
