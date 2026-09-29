#!/usr/bin/env python3
"""Write this design out in the formats other programs read.

    caliper bundle                                # STEP + STL into out/export/
    caliper bundle --formats step,stl,3mf --parts # ...plus one file per part
    caliper bundle --formats glb --force          # rebuild even if nothing moved

`caliper export` rebuilds `out/` for the app: a GLB the viewport can draw and a
scene graph the physics reads. This is the other direction — the files you hand
to a slicer, a CAD package or a colleague, named after the design rather than
after `model`, so a download is `robot-arm.stl` and not `model.stl`.

Everything lands in `out/export/`, which is gitignored like the rest of `out/`.

Two things are deliberate:

  * **The floor is not part of the design.** A body that is `fixed` and that no
    joint touches is scenery — the 40 m ground slab every walking model stands
    on. It is dropped, or an STL of a small bracket arrives 40 m wide. A fixed
    body a joint hangs off (an arm's bolted base) is kept, because it is the
    machine. `--all` turns the filter off; a model made of one fixed solid keeps
    it, since dropping everything is never what was meant.
  * **Meshes go through `tools/meshkit.py`**, at print tessellation rather than
    the viewer's, so what comes out of here can be sliced and matches what
    `caliper print` writes for the same solid.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import time
from pathlib import Path

import trimesh

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from meshkit import ANG, TOL, check_mesh, to_mesh  # noqa: E402
from paths import CAD, ROOT, require_cad  # noqa: E402

OUT = ROOT / "out" / "export"

# id -> (file extension, built from solids rather than meshes)
FORMATS: dict[str, tuple[str, bool]] = {
    "step": ("step", True),    # solid CAD: FreeCAD, Fusion, SolidWorks
    "stl":  ("stl",  False),   # the mesh every slicer eats
    "3mf":  ("3mf",  False),   # parts and colours kept apart, for modern slicers
    "obj":  ("obj",  False),   # mesh interchange
    "ply":  ("ply",  False),   # mesh + vertex colour
    "glb":  ("glb",  False),   # exactly what the viewport draws
}

SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def human(n: int) -> str:
    return f"{n / 1e6:.1f} MB" if n >= 1e6 else f"{n / 1e3:.0f} KB" if n >= 1000 else f"{n} B"


def newest_source() -> float:
    """When the CAD last changed — everything in out/export/ is stale before it."""
    return max((p.stat().st_mtime for p in CAD.rglob("*")
                if p.is_file() and (p.suffix == ".py" or p.name == "project.json")), default=0.0)


def hex_to_rgba(h: str | None):
    if not h:
        return None
    h = h.lstrip("#")
    return [int(h[i:i + 2], 16) for i in (0, 2, 4)] + [255]


class Part:
    """One thing that gets a file: a rigid body or a piece of decor."""

    def __init__(self, name, solid, origin, color, kind):
        self.name = name
        self.solid = solid
        self.origin = tuple(origin)
        self.color = color
        self.kind = kind          # body | decor
        self._mesh = None

    @property
    def file_stem(self) -> str:
        return SAFE.sub("_", self.name) or "part"

    def mesh(self, tol, ang):
        """The part's mesh, placed where it sits in the world."""
        if self._mesh is None:
            m = to_mesh(self.solid, tol, ang)
            m.apply_translation(self.origin)
            rgba = hex_to_rgba(self.color)
            if rgba:
                m.visual.face_colors = rgba
            self._mesh = m
        return self._mesh

    def placed(self):
        """The solid, moved to where it sits in the world."""
        from build123d import Pos
        return Pos(self.origin) * self.solid


def collect(include_all: bool) -> tuple[list[Part], list[str]]:
    """The design's parts, and the names of whatever was left out."""
    require_cad()
    if str(CAD) not in sys.path:
        sys.path.insert(0, str(CAD))

    import model  # noqa: F401  — importing it populates SCENE
    from scene import SCENE

    if not SCENE.bodies:
        raise SystemExit("cad/model.py declared no bodies — nothing to write out.")

    jointed = set()
    for j in SCENE.joints:
        jointed.add(j.a)
        jointed.add(j.b)

    kept, dropped = [], []
    for b in SCENE.bodies:
        if not include_all and b.type == "fixed" and b.name not in jointed:
            dropped.append(b.name)
            continue
        kept.append(Part(b.name, b.part, b.origin, b.color, "body"))

    # Everything was scenery: a single fixed solid is still the design.
    if not kept:
        kept = [Part(b.name, b.part, b.origin, b.color, "body") for b in SCENE.bodies]
        dropped = []

    for d in SCENE.decor:
        kept.append(Part(d.name, d.part, d.origin, d.color, "decor"))
    return kept, dropped


def assembled_mesh(parts, tol, ang):
    """Every part welded into one mesh, in world position."""
    return trimesh.util.concatenate([p.mesh(tol, ang) for p in parts])


def scene_of(parts, tol, ang):
    """A trimesh Scene keeping each part its own object — what 3MF is for."""
    s = trimesh.Scene()
    for p in parts:
        s.add_geometry(p.mesh(tol, ang), node_name=p.name, geom_name=p.name)
    return s


def write_step(solids, path: Path) -> None:
    from build123d import Compound, export_step
    export_step(Compound(children=list(solids)), path.as_posix())


def build(fmt: str, parts, args, dropped) -> str:
    """Write one format. Returns a short note about how it was made."""
    ext = FORMATS[fmt][0]
    target = OUT / f"{ROOT.name}.{ext}"

    if fmt == "glb":
        src = ROOT / "out" / "model.glb"
        if not src.is_file():
            raise SystemExit(
                "no out/model.glb yet — run `caliper export` first.")
        if (CAD / "project.json").is_file():
            from scene import SCENE
            metadata = ROOT / "out/scene.json"
            if (not metadata.is_file()
                    or json.loads(metadata.read_text()).get("project") != SCENE.project
                    or src.stat().st_mtime < newest_source()):
                raise SystemExit("viewer artifacts belong to a different scene or configuration; "
                                 "run `caliper export` with the same --scene and --set arguments")
        shutil.copyfile(src, target)
        return "copied from out/model.glb"

    if fmt == "step":
        # The watcher already wrote an assembled STEP. Reuse it only when it
        # holds the same parts we would have written — with the ground slab
        # dropped it does not, and a 40 m floor in someone's CAD is not a
        # detail they will thank us for.
        src = ROOT / "out" / "model.step"
        if (not (CAD / "project.json").is_file() and not dropped
                and src.is_file() and src.stat().st_mtime >= newest_source()):
            shutil.copyfile(src, target)
            return "copied from out/model.step"
        write_step([p.placed() for p in parts], target)
        return f"rebuilt from {len(parts)} parts"

    if fmt == "3mf":
        try:
            data = scene_of(parts, args.tol, args.ang).export(file_type="3mf")
        except ImportError as e:
            # trimesh's 3MF writer needs networkx and lxml, and imports them
            # only when asked — so this is the one format that can fail on an
            # otherwise working install. Both are in requirements.txt.
            raise SystemExit(
                f"3MF needs a package this python does not have: {e}. "
                "Rebuild the image (docker compose up --build), or install "
                "networkx and lxml into the venv you are running.")
        target.write_bytes(data)
        return f"{len(parts)} objects, colours kept"

    mesh = assembled_mesh(parts, args.tol, args.ang)
    data = mesh.export(file_type=ext)
    target.write_bytes(data.encode() if isinstance(data, str) else data)
    return f"{len(mesh.faces)} triangles"


def build_parts(fmt: str, parts, args) -> int:
    """One file per part, world-placed so re-importing the set reassembles it."""
    ext = FORMATS[fmt][0]
    into = OUT / "parts"
    into.mkdir(parents=True, exist_ok=True)
    n = 0
    for p in parts:
        path = into / f"{p.file_stem}.{ext}"
        if fmt == "step":
            write_step([p.placed()], path)
        else:
            data = p.mesh(args.tol, args.ang).export(file_type=ext)
            path.write_bytes(data.encode() if isinstance(data, str) else data)
        n += 1
    return n


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Write the design out as STEP/STL/3MF/OBJ/PLY/GLB.")
    ap.add_argument("--formats", default="step,stl",
                    help=f"comma separated: {', '.join(FORMATS)} (default step,stl)")
    ap.add_argument("--parts", action="store_true",
                    help="also write one file per part into out/export/parts/")
    ap.add_argument("--all", action="store_true",
                    help="include the ground slab and other jointless fixed scenery")
    ap.add_argument("--tol", type=float, default=TOL,
                    help=f"mesh tolerance in mm (default {TOL})")
    ap.add_argument("--ang", type=float, default=ANG, help=argparse.SUPPRESS)
    ap.add_argument("--force", action="store_true",
                    help="rebuild formats that are already newer than cad/")
    args = ap.parse_args()

    wanted = [f.strip().lower() for f in args.formats.split(",") if f.strip()]
    unknown = [f for f in wanted if f not in FORMATS]
    if unknown:
        print(f"bundle: unknown format(s): {', '.join(unknown)}", file=sys.stderr)
        print(f"known: {', '.join(FORMATS)}", file=sys.stderr)
        return 2
    if not wanted:
        print("bundle: no formats asked for", file=sys.stderr)
        return 2

    source_t = newest_source()
    # Named scenes can change geometry without changing source timestamps.
    # Build from the selected scene rather than reusing another scene's files.
    todo = wanted if args.force or (CAD / "project.json").is_file() else [
        f for f in wanted
        if not (OUT / f"{ROOT.name}.{FORMATS[f][0]}").is_file()
        or (OUT / f"{ROOT.name}.{FORMATS[f][0]}").stat().st_mtime < source_t
    ]
    fresh = [f for f in wanted if f not in todo]
    # Per-part files are not tracked individually; asking for them builds them.
    if not todo and not args.parts:
        for f in fresh:
            path = OUT / f"{ROOT.name}.{FORMATS[f][0]}"
            print(f"{f:6} {path.name:28} {human(path.stat().st_size):>9}  already current")
        print("\nOK (nothing to rebuild — use --force to redo them)")
        return 0

    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.time()   # before collect(): tessellation is most of the wall clock
    parts, dropped = collect(args.all)

    # Mesh once, warn once: a part that is not watertight will not slice, and
    # the person who finds out should be whoever exported it, not the printer.
    warnings = []
    if any(not FORMATS[f][1] for f in todo) or args.parts:
        for p in parts:
            bad = check_mesh(p.mesh(args.tol, args.ang))
            if bad:
                warnings.append({"part": p.name, "problems": bad})

    files = []
    print(f"{'format':6} {'file':28} {'size':>9}  note")
    print("-" * 78)
    for f in fresh:
        path = OUT / f"{ROOT.name}.{FORMATS[f][0]}"
        print(f"{f:6} {path.name:28} {human(path.stat().st_size):>9}  already current")
        files.append({"format": f, "path": path.name, "bytes": path.stat().st_size,
                      "kind": "assembled"})

    for f in todo:
        note = build(f, parts, args, dropped)
        path = OUT / f"{ROOT.name}.{FORMATS[f][0]}"
        size = path.stat().st_size
        print(f"{f:6} {path.name:28} {human(size):>9}  {note}")
        files.append({"format": f, "path": path.name, "bytes": size, "kind": "assembled"})

    if args.parts:
        for f in wanted:
            if f == "glb":
                continue   # the GLB is already one node per part
            n = build_parts(f, parts, args)
            print(f"{f:6} {'parts/*.' + FORMATS[f][0]:28} {'':>9}  {n} files")
            files += [{"format": f, "path": f"parts/{p.file_stem}.{FORMATS[f][0]}",
                       "bytes": (OUT / "parts" / f"{p.file_stem}.{FORMATS[f][0]}").stat().st_size,
                       "kind": "part"} for p in parts]

    print("-" * 78)
    print(f"{len(parts)} parts in {time.time() - t0:.1f} s -> {OUT}")
    if dropped:
        print(f"left out (fixed, no joint): {', '.join(dropped)}  — pass --all to keep them")
    for w in warnings:
        print(f"  ! {w['part']}: {'; '.join(w['problems'])}")

    (OUT / "bundle.json").write_text(json.dumps({
        "design": ROOT.name,
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "tol": args.tol,
        "parts": [{"name": p.name, "kind": p.kind} for p in parts],
        "excluded": dropped,
        "files": files,
        "warnings": warnings,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
