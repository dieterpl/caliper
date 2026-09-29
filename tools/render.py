#!/usr/bin/env python3
"""Draw the design to a PNG, so the agent building it can actually look at it.

There is no usable browser on this machine, so the app's viewer is not available
to whoever is editing the CAD — which has meant working entirely blind, with
`fitcheck.py`'s millimetres as the only evidence that anything is where it was
meant to be. This renders the same scene offline (tools/raster.py does the
pixels) and writes a PNG that can be read directly.

    .venv/bin/python tools/render.py                      # 4 views, out/views/model.png
    .venv/bin/python tools/render.py --view iso --size 1400
    .venv/bin/python tools/render.py --section 'y>142'    # cut through the leg plane
    .venv/bin/python tools/render.py --only 'fl_*' --hide belts
    .venv/bin/python tools/render.py --pose fl_knee=-30,fl_hip_pitch=10
    .venv/bin/python tools/render.py --joints --clash     # anchors, and fitcheck's blobs

And the camera can be aimed, which is how you look at ONE part closely rather
than at the whole design from four fixed corners:

    .venv/bin/python tools/render.py --focus hip_bracket --persp
    .venv/bin/python tools/render.py --eye 300,-400,250 --target 0,0,120 --persp
    .venv/bin/python tools/render.py --azim 35 --elev 20 --zoom 2
    .venv/bin/python tools/render.py --view around        # all four corners

By default views are ORTHOGRAPHIC and carry a scale bar, so a distance can be
read off the picture rather than guessed. `--persp` trades that away for depth
that actually reads: parallel edges converge, and it stops being ambiguous which
of two overlapping parts is in front. Measure in ortho, judge shape in
perspective — under `--persp` the bar is only true at the target and says so.

`--section` is the one to reach for when hardware might be buried inside a part:
it cuts the model open at a plane and paints the exposed interior, which is
exactly the failure (a motor 24 cm³ inside the beam) that looked fine in every
shaded view until someone measured it.

Geometry is re-tessellated coarsely rather than loaded from out/model.glb: the
export's 0.1 mm tolerance makes triangles far smaller than a pixel, which a
point-sampling rasterizer simply drops. See tools/raster.py.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from fnmatch import fnmatch
from math import atan, atan2, asin, cos, degrees, radians, sin, tan
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import kin  # noqa: E402  (adds cad/ to the path and populates SCENE)
import raster  # noqa: E402

TESS_TOL, TESS_ANG = 1.0, 0.6      # mm / rad: coarse on purpose, see the docstring
BG = (16, 18, 24)
CUT = (150, 60, 60)                # exposed interior of a sectioned part
GRID = (44, 50, 62)
INK = (215, 222, 235)
MARK = (240, 70, 70)
AXIS = (90, 200, 255)
LIGHT = np.array([0.35, 0.55, 0.75])
LIGHT /= np.linalg.norm(LIGHT)
AMBIENT = 0.32
GROUP_COLOR = {"frame": "#334155", "links": "#94a3b8", "motors": "#0f172a",
               "belts": "#111827", "shell": "#1e293b", "controllers": "#15803d",
               "feet": "#0a0a0a"}


def angles_to_dir(azim, elev):
    """Look direction for a camera at azimuth/elevation around its target.

    Azimuth runs in the world XY plane from +X toward +Y, elevation up from it,
    both in degrees. The camera sits at target + dist*(the offset below) and
    looks back down it, so azim/elev reproduce the presets exactly: (0,0) is
    `front`, (90,0) is `side`, (_,90) is `top`.
    """
    a, e = radians(azim), radians(elev)
    off = np.array([cos(e) * cos(a), cos(e) * sin(a), sin(e)])
    return -off


def dir_to_angles(look):
    """The inverse, for reporting what a preset or an --eye actually was."""
    off = -np.asarray(look, float)
    off = off / (np.linalg.norm(off) or 1.0)
    return degrees(atan2(off[1], off[0])), degrees(asin(np.clip(off[2], -1, 1)))


VIEWS = {                          # name -> direction the camera looks along
    "front": ((-1, 0, 0), "FRONT  LOOKING -X"),
    "side": ((0, -1, 0), "SIDE  LOOKING -Y"),
    "top": ((0, 0, -1), "TOP  LOOKING -Z"),
    "iso": ((-0.72, -0.55, -0.42), "ISO"),
    # The other four faces, named as tools/draft.py names them. `right` is the
    # same view as `side`; both names work, because the skill says `side` and
    # the line-drawing tool says `right`.
    "back": ((1, 0, 0), "BACK  LOOKING +X"),
    "left": ((0, 1, 0), "LEFT  LOOKING +Y"),
    "right": ((0, -1, 0), "RIGHT  LOOKING -Y"),
    "bottom": ((0, 0, 1), "BOTTOM  LOOKING +Z"),
    # The four corners. `iso` is hand-tuned and sits near `iso-fr`; it is left
    # exactly as it was so the default sheet does not move.
    "iso-fr": (angles_to_dir(45, 30), "ISO FR"),
    "iso-fl": (angles_to_dir(-45, 30), "ISO FL"),
    "iso-br": (angles_to_dir(135, 30), "ISO BR"),
    "iso-bl": (angles_to_dir(225, 30), "ISO BL"),
}

DEFAULT_VIEWS = ["front", "side", "top", "iso"]   # what `--view all` means
AROUND_VIEWS = ["iso-fr", "iso-br", "iso-bl", "iso-fl"]


def hex_rgb(h: str):
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], float)


_TESS: dict = {}


def tessellate(part):
    """(vertices, faces) for a part in its own frame, memoised by identity —
    hardware.py hands out one shared solid per distinct motor and pulley."""
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
    names = [n for n, p in P.items()
             if (not only or match(p, only)) and not (hide and match(p, hide))]
    return sorted(names)


def build(P, pose, names):
    """World triangle soup: (M,3,3) vertices, (M,3) face normals, (M,3) colours."""
    locs = kin.placements(pose)
    tris, cols = [], []
    for n in names:
        p = P[n]
        v, f = tessellate(p.part)
        if len(f) == 0:
            continue
        w = kin.transform(locs[n], v)
        tris.append(w[f])
        rgb = hex_rgb(p.color or GROUP_COLOR.get(p.group, "#64748b"))
        cols.append(np.tile(rgb, (len(f), 1)))
    if not tris:
        return np.zeros((0, 3, 3)), np.zeros((0, 3)), np.zeros((0, 3))
    tri = np.vstack(tris)
    col = np.vstack(cols)
    nrm = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    ln = np.linalg.norm(nrm, axis=1, keepdims=True)
    nrm = nrm / np.where(ln == 0, 1, ln)
    return tri, nrm, col


def basis(view_dir, up_hint=None):
    """(right, up, view) — an orthonormal camera frame, never mirrored.

    `up_hint` replaces the default world-up reference, which is +Z except when
    the camera looks along it (top/bottom), where it falls back to +X. Note the
    cross product order: `cross(up_hint, view)`, not the more usual
    `cross(view, up_hint)` — the other order mirrors every existing view.
    """
    v = np.array(view_dir, float)
    v /= np.linalg.norm(v)
    if up_hint is None:
        ref = np.array([0.0, 0.0, 1.0])
        if abs(np.dot(ref, v)) > 0.999:
            ref = np.array([1.0, 0.0, 0.0])
    else:
        ref = np.array(up_hint, float)
        n = np.linalg.norm(ref)
        if n == 0:
            raise SystemExit("render: --up cannot be the zero vector")
        ref = ref / n
        if abs(np.dot(ref, v)) > 0.999:
            raise SystemExit("render: --up is parallel to the view direction")
    right = np.cross(ref, v)
    right /= np.linalg.norm(right)
    up = np.cross(v, right)
    return right, up, v


@dataclass
class Camera:
    """Where the picture is taken from. Orthographic when `fov` is None.

    Screen space is raster.Canvas's: x right, y down, z into the screen, and
    smaller is nearer. Under perspective the depth written into that z is
    **-1/depth**, not the depth: the rasterizer interpolates it with SCREEN
    space barycentrics, and 1/depth is the one function of depth that is
    exactly affine in screen space. Writing plain depth instead z-fights
    through millimetres of wall as soon as a face is foreshortened.
    """

    right: np.ndarray
    up: np.ndarray
    fwd: np.ndarray                     # unit, points INTO the screen
    target: np.ndarray
    eye: np.ndarray | None = None       # None until fit() solves for it
    fov: float | None = None            # vertical degrees; None -> orthographic
    dist: float | None = None
    scale: float = 1.0                  # ortho: px per mm.  persp: focal, px
    cx: float = 0.0                     # pane centre, px
    cy: float = 0.0
    mx: float = 0.0                     # ortho only: fit centre, mm
    my: float = 0.0
    znear: float = 1e-3

    # -- projection --------------------------------------------------------
    def project(self, pts):
        """(px, py, zkey, depth) for world points, flattened to (N,).

        `depth` is millimetres along the view axis. Anything at or behind
        `znear` must be dropped by the caller: this rasterizer has no clipper,
        so a triangle straddling the eye would smear across the whole frame.
        """
        p = np.asarray(pts, float).reshape(-1, 3)
        if self.fov is None:
            x, y, d = p @ self.right, p @ self.up, p @ self.fwd
            return (self.cx + (x - self.mx) * self.scale,
                    self.cy - (y - self.my) * self.scale, d, d)
        q = p - self.eye
        x, y, d = q @ self.right, q @ self.up, q @ self.fwd
        dd = np.maximum(d, self.znear)      # keeps the arithmetic finite; the
        return (self.cx + self.scale * x / dd,   # caller culls on real depth
                self.cy - self.scale * y / dd,
                -1.0 / dd, d)

    def px_per_mm(self):
        """Pixels per mm — at the target plane, when there is perspective."""
        return self.scale if self.fov is None else self.scale / self.dist

    # -- framing -----------------------------------------------------------
    def fit(self, pts, ox, oy, w, h, zoom=1.0, pad=0.86):
        """Frame `pts` into the pane at (ox, oy, w, h).

        Exactly one of {fov, dist} is solved for; whichever the flags pinned
        down stays put. `zoom` > 1 always means bigger in frame.
        """
        self.cx, self.cy = ox + w / 2, oy + h / 2
        if self.fov is None:
            sx, sy = pts @ self.right, pts @ self.up
            lo = np.array([sx.min(), sy.min()])
            hi = np.array([sx.max(), sy.max()])
            span = np.maximum(hi - lo, 1e-6)
            self.scale = zoom * min(w * pad / span[0], h * pad / span[1])
            self.mx, self.my = (lo + hi) / 2
            return self

        if self.eye is not None:                # eye pinned: solve the lens
            q = pts - self.eye
            a, b, d = q @ self.right, q @ self.up, q @ self.fwd
            ok = d > 1e-6
            if not ok.any():
                raise SystemExit("render: nothing is in front of the camera")
            a, b, d = a[ok], b[ok], d[ok]
            ax = np.abs(a / d).max() or 1e-9
            by = np.abs(b / d).max() or 1e-9
            self.scale = zoom * min((w * pad / 2) / ax, (h * pad / 2) / by)
            self.fov = degrees(2 * atan((h / 2) / self.scale))
            self.dist = float(np.linalg.norm(self.target - self.eye)) or 1.0
        else:                                   # lens pinned: solve the stand-off
            tan_y = tan(radians(self.fov) / 2)
            tan_x = tan_y * w / h
            q = pts - self.target
            a, b, c = q @ self.right, q @ self.up, q @ self.fwd
            need = np.maximum(np.abs(a) / (pad * tan_x),
                              np.abs(b) / (pad * tan_y)) - c
            self.dist = max(float(need.max()), float((-c).max()), 1e-3) / zoom
            self.eye = self.target - self.fwd * self.dist
            self.scale = (h / 2) / tan_y
        self.znear = max(1e-3, 0.002 * self.dist)
        return self

    def describe(self):
        """One line naming the shot, so a picture can be taken again."""
        if self.fov is None:
            return f"ortho  {self.px_per_mm():.4g} px/mm"
        e, t = self.eye, self.target
        return (f"eye {e[0]:.4g} {e[1]:.4g} {e[2]:.4g}  "
                f"target {t[0]:.4g} {t[1]:.4g} {t[2]:.4g}  "
                f"dist {self.dist:.4g}  fov {self.fov:.4g}")


def nice_bar(mm_per_px, width_px):
    """A round number of mm about a quarter of the pane wide."""
    target = width_px * 0.25 * mm_per_px
    for step in (1, 2, 5, 10, 20, 50, 100, 200, 500, 1000):
        if step >= target:
            return step
    return 1000


def parse_section(spec):
    """'y>142' | 'y<142' | 'y=142' -> (axis index, value, sign).

    sign +1 removes material above the plane, -1 below it. Plain '=' removes
    what is above, which is the half you are usually looking through.
    """
    if not spec:
        return None
    for op, sign in ((">", 1), ("<", -1), ("=", 1)):
        if op in spec:
            ax, val = spec.split(op, 1)
            ax = ax.strip().lower()
            if ax not in "xyz" or len(ax) != 1:
                raise SystemExit(f"render: section axis must be x, y or z, got {ax!r}")
            return "xyz".index(ax), float(val), sign
    raise SystemExit(f"render: cannot parse --section {spec!r} (want e.g. 'y>142')")


def parse_pose(spec):
    if not spec:
        return {}
    pose = {}
    for item in spec.split(","):
        name, _, val = item.partition("=")
        if not val:
            raise SystemExit(f"render: --pose wants joint=degrees, got {item!r}")
        pose[name.strip()] = radians(float(val))
    return pose


def draw_pane(canvas, ox, oy, w, h, tri, nrm, col, cam, label,
              section, markers):
    """One view, drawn into a sub-rectangle of the canvas. Returns the number
    of triangles the near plane ate (always 0 when orthographic)."""
    if len(tri) == 0:
        return 0
    px, py, zkey, depth = cam.project(tri)
    scr = np.stack([px, py, zkey], 1).reshape(-1, 3, 3)
    depth = depth.reshape(-1, 3)

    if cam.fov is None:
        facing = (nrm @ cam.fwd) < 0
        near = np.ones(len(tri), bool)
    else:
        # Per triangle, not per view: with a perspective camera every triangle
        # is seen along a slightly different ray, and the single view vector
        # that works for a parallel projection starts keeping front faces at
        # the edge of a wide lens and dropping back faces that face you.
        facing = np.einsum("ij,ij->i", nrm, cam.eye - tri.mean(1)) > 0
        near = depth.min(1) > cam.znear

    shade = AMBIENT + (1 - AMBIENT) * np.clip(np.abs(nrm @ LIGHT), 0, 1)
    colors = np.clip(col * shade[:, None], 0, 255).astype(np.uint8)
    if section is None:
        keep, clip = facing & near, None
    else:
        # Back faces stay in: with the near half cut away they ARE the surface
        # you see, and painting them differently is what makes a section read
        # as a cut rather than as a hole.
        ax, val, sign = section
        keep = near.copy()
        colors = np.where(facing[:, None], colors,
                          np.array(CUT, np.uint8)[None, :]).astype(np.uint8)
        clip = (tri[:, :, ax] - val) * sign
        if cam.fov is not None:
            # raster.py sums this with SCREEN-space barycentrics, which is not
            # where the plane really falls under perspective — the cut bows by
            # centimetres inside a big foreshortened facet. But the value is
            # only ever sign-tested, and the perspective-correct expression is
            # (sum w*A/d) / (sum w/d) with a strictly positive denominator, so
            # dividing by depth here makes the existing sum exact. This works
            # ONLY because there is one attribute and only its sign is read.
            clip = clip / np.maximum(depth, cam.znear)
    if cam.fov is not None:
        keep &= np.isfinite(scr).all((1, 2))
    canvas.triangles(scr[keep], colors[keep],
                     None if clip is None else clip[keep],
                     bounds=(ox, oy, ox + w, oy + h))

    # ---- overlays -------------------------------------------------------
    if markers:
        mx, my, _, md = cam.project(np.array([m[0] for m in markers], float))
        for (pt, color, tag), x, y, d in zip(markers, mx, my, md):
            if d <= cam.znear:
                continue        # behind the eye: it would land mirrored, and
                                # a marker in the wrong place is worse than none
            if ox <= x < ox + w and oy <= y < oy + h:
                canvas.cross(int(x), int(y), color, r=6)
                if tag:
                    raster.text(canvas, int(x) + 8, int(y) - 4, tag, color, scale=1)

    ppm = cam.px_per_mm()
    bar = nice_bar(1.0 / ppm, w)
    bx, by = ox + 14, oy + h - 18
    canvas.rect(bx, by, bx + bar * ppm, by + 3, INK)
    canvas.rect(bx, by - 4, bx + 2, by + 7, INK)
    canvas.rect(bx + bar * ppm - 2, by - 4, bx + bar * ppm, by + 7, INK)
    # Under perspective a scale bar is only true at one depth, so say which.
    # (raster.GLYPHS has no '/', ',' or '°' — keep label text to A-Z 0-9 -+.:=)
    raster.text(canvas, bx, by - 20,
                f"{bar:g} MM" if cam.fov is None else f"{bar:g} MM AT TARGET",
                INK, scale=2)
    raster.text(canvas, ox + 14, oy + 12, label, INK, scale=2)
    row = 32
    if cam.fov is not None:
        raster.text(canvas, ox + 14, oy + row,
                    f"PERSP FOV {cam.fov:.0f} DIST {cam.dist:.0f}", AXIS, scale=2)
        row += 20
    if section is not None:
        ax, val, sign = section
        raster.text(canvas, ox + 14, oy + row,
                    f"CUT {'XYZ'[ax]}{'>' if sign > 0 else '<'}{val:g}", CUT, scale=2)
    return int((~near).sum())


def parse_vec3(spec, flag):
    if spec is None:
        return None
    bits = [b for b in spec.replace(" ", ",").split(",") if b]
    try:
        if len(bits) != 3:
            raise ValueError
        return np.array([float(b) for b in bits], float)
    except ValueError:
        raise SystemExit(f"render: {flag} wants X,Y,Z in mm, got {spec!r}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--view", default=None,
                    help=f"{' | '.join(VIEWS)} | all | around (default all, "
                         f"which is {', '.join(DEFAULT_VIEWS)})")
    ap.add_argument("--size", type=int, default=1200,
                    help="image edge in pixels (default 1200)")
    ap.add_argument("--out", default=None,
                    help="output PNG (default out/views/model.png, or "
                         "out/views/view.png once the camera is aimed)")
    ap.add_argument("--pose", default=None,
                    help="joint=DEGREES,... — zero is the authored rest pose")
    ap.add_argument("--only", action="append", help="glob on part name or group")
    ap.add_argument("--hide", action="append", help="glob on part name or group")
    ap.add_argument("--section", default=None, help="cut plane, e.g. 'y>142'")
    ap.add_argument("--ground", action="store_true",
                    help="include the floor (a 40 m slab: it frames out the design)")
    ap.add_argument("--joints", action="store_true", help="mark joint anchors")
    ap.add_argument("--clash", action="store_true",
                    help="mark the intersections in out/fitcheck.json")
    cam_g = ap.add_argument_group(
        "camera", "where the picture is taken from. Without any of these it is "
                  "the orthographic sheet it has always been.")
    cam_g.add_argument("--eye", default=None,
                       help="camera position X,Y,Z in mm (one pane)")
    cam_g.add_argument("--target", default=None,
                       help="what to look at, X,Y,Z in mm (default: the middle "
                            "of what is drawn)")
    cam_g.add_argument("--azim", type=float, default=None,
                       help="camera bearing in degrees, +X toward +Y (one pane)")
    cam_g.add_argument("--elev", type=float, default=None,
                       help="camera elevation in degrees above the XY plane")
    cam_g.add_argument("--dist", type=float, default=None,
                       help="how far the eye stands off the target, mm")
    cam_g.add_argument("--persp", action="store_true",
                       help="perspective instead of orthographic — depth reads, "
                            "but distances no longer measure")
    cam_g.add_argument("--fov", type=float, default=None,
                       help="vertical field of view in degrees (implies --persp; "
                            "default 45)")
    cam_g.add_argument("--zoom", type=float, default=1.0,
                       help="tighten the framing; >1 is bigger in frame")
    cam_g.add_argument("--focus", action="append",
                       help="frame on the parts matching this glob, while still "
                            "drawing the rest around them")
    cam_g.add_argument("--up", default=None,
                       help="which way is up in the picture, X,Y,Z")
    args = ap.parse_args()

    P = kin.parts()
    pose = parse_pose(args.pose)
    section = parse_section(args.section)
    names = visible(P, args.only, args.hide)
    if not args.ground:
        # The floor is 40 m across (parts/ground.py). Auto-framing on it shrinks
        # the design to a speck, so it stays out unless it is asked for.
        names = [n for n in names if P[n].group != "ground"]
    if not names:
        print("render: --only/--hide left nothing to draw", file=sys.stderr)
        return 2

    tri, nrm, col = build(P, pose, names)
    print(f"render: {len(names)} parts, {len(tri)} triangles")

    markers = []
    if args.joints:
        for name, j in kin.joints().items():
            markers.append((j.anchor, AXIS, name))
    if args.clash:
        path = kin.OUT / "fitcheck.json"
        if not path.exists():
            print("render: no out/fitcheck.json — run tools/fitcheck.py first",
                  file=sys.stderr)
        else:
            data = json.loads(path.read_text())
            for pair in data.get("pairs", []):
                if pair.get("kind") not in ("clash", "rotating"):
                    continue
                for blob in pair.get("blobs", []):
                    markers.append((blob["center"], MARK,
                                    f"{pair['a']}/{pair['b']}"))

    # ---- what to frame on ------------------------------------------------
    if args.focus:
        focused = [n for n in visible(P, args.focus, args.hide) if n in set(names)]
        if not focused:
            print(f"render: --focus {', '.join(args.focus)} matched none of "
                  f"the {len(names)} parts being drawn", file=sys.stderr)
            return 2
        fit_pts = build(P, pose, focused)[0].reshape(-1, 3)
        print(f"render: framing on {len(focused)} part(s): {', '.join(focused[:6])}"
              + (" ..." if len(focused) > 6 else ""))
    else:
        fit_pts = tri.reshape(-1, 3)

    # ---- the camera ------------------------------------------------------
    eye = parse_vec3(args.eye, "--eye")
    target = parse_vec3(args.target, "--target")
    up_hint = parse_vec3(args.up, "--up")
    aimed = args.azim is not None or args.elev is not None
    persp = args.persp or args.fov is not None

    if eye is not None and aimed:
        raise SystemExit("render: --eye already places the camera; "
                         "drop --azim/--elev (or drop --eye)")
    if args.dist is not None and eye is not None:
        raise SystemExit("render: --eye already places the camera; drop --dist")
    if args.dist is not None and not persp:
        raise SystemExit("render: --dist needs --persp — an orthographic view "
                         "has a direction but no stand-off")
    if args.fov is not None and (eye is not None or args.dist is not None):
        raise SystemExit("render: --fov and --eye/--dist both fix the framing; "
                         "there is nothing left to fit. Use one or the other.")
    if args.zoom <= 0:
        raise SystemExit(f"render: --zoom must be positive, got {args.zoom}")
    if target is None:
        target = (fit_pts.min(0) + fit_pts.max(0)) / 2

    spec = args.view
    if spec is None:
        # Aiming the camera by hand is a request for one picture, so it does not
        # need `--view` turned off as well. An explicit --view still wins, and
        # still has to make sense.
        spec = "front" if (eye is not None or aimed) else "all"
    want = (DEFAULT_VIEWS if spec == "all" else
            AROUND_VIEWS if spec == "around" else
            [v.strip() for v in spec.split(",")])
    bad = [v for v in want if v not in VIEWS]
    if bad:
        raise SystemExit(f"render: unknown view(s) {bad}; have {list(VIEWS)}, "
                         f"or aim the camera with --eye / --azim --elev")
    if (eye is not None or aimed) and len(want) > 1:
        raise SystemExit("render: --eye/--azim/--elev describe one camera, but "
                         f"--view asks for {len(want)} panes. Pick one.")

    def camera_for(view_name):
        """The camera for one pane, before it is fitted to that pane."""
        if eye is not None:
            fwd = target - eye
            n = np.linalg.norm(fwd)
            if n < 1e-9:
                raise SystemExit("render: --eye and --target are the same point")
            fwd = fwd / n
        elif aimed:
            az, el = dir_to_angles(VIEWS[view_name][0])
            fwd = angles_to_dir(args.azim if args.azim is not None else az,
                                args.elev if args.elev is not None else el)
        else:
            fwd = np.array(VIEWS[view_name][0], float)
        right, up, fwd = basis(fwd, up_hint)
        cam = Camera(right=right, up=up, fwd=fwd, target=target)
        if persp:
            cam.fov = args.fov if args.fov is not None else 45.0
            if not 0 < cam.fov < 180:
                raise SystemExit(f"render: --fov must be in 0..180, got {cam.fov}")
            if eye is not None:
                cam.eye = eye       # pinned: fit() solves the lens that frames it
            elif args.dist is not None:
                if args.dist <= 0:
                    raise SystemExit("render: --dist must be positive")
                cam.eye = target - fwd * args.dist
        return cam

    def label_for(view_name):
        if eye is not None:
            return "EYE " + " ".join(f"{c:.0f}" for c in eye)
        if aimed:
            az, el = dir_to_angles(VIEWS[view_name][0])
            return (f"AZIM {args.azim if args.azim is not None else az:.0f}  "
                    f"ELEV {args.elev if args.elev is not None else el:.0f}")
        return VIEWS[view_name][1]

    if len(want) == 1:
        cols, rows = 1, 1
    else:
        cols = 2
        rows = (len(want) + 1) // 2
    pw = args.size // cols
    ph = args.size // cols          # square panes, so mm read the same both ways
    canvas = raster.Canvas(pw * cols, ph * rows, BG)

    culled = 0
    for i, name in enumerate(want):
        ox, oy = (i % cols) * pw, (i // cols) * ph
        canvas.rect(ox, oy, ox + pw, oy + 1, GRID)
        canvas.rect(ox, oy, ox + 1, oy + ph, GRID)
        cam = camera_for(name).fit(fit_pts, ox, oy, pw, ph, args.zoom)
        culled += draw_pane(canvas, ox, oy, pw, ph, tri, nrm, col,
                            cam, label_for(name), section, markers)
        if persp and len(want) == 1:
            print(f"render: {cam.describe()}")
            if cam.fov > 120:
                print(f"render: {cam.fov:.0f} degrees is a fish-eye — the eye is "
                      f"very close. Back it off for a picture you can judge.",
                      file=sys.stderr)

    if culled:
        print(f"render: the near plane cut {culled} triangle(s)")
        lo, hi = tri.reshape(-1, 3).min(0), tri.reshape(-1, 3).max(0)
        if cam.eye is not None and (cam.eye > lo).all() and (cam.eye < hi).all():
            print("render: the eye is inside the design — raise --dist, or "
                  "move --eye out of the geometry", file=sys.stderr)

    aimed_at_all = any(v is not None for v in
                       (args.eye, args.target, args.azim, args.elev, args.dist,
                        args.fov, args.focus, args.up)) or args.persp or args.zoom != 1.0
    if args.out:
        out = Path(args.out)
    elif aimed_at_all:
        # model.png is the hub card's picture of this design. A shot from some
        # exploratory angle is not that, so it goes somewhere else by default.
        out = kin.OUT / "views" / "view.png"
    else:
        out = kin.OUT / "views" / "model.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    raster.write_png(out, canvas.rgb)
    print(f"render: wrote {out}  ({canvas.rgb.shape[1]}x{canvas.rgb.shape[0]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
