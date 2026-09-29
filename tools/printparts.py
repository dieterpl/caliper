#!/usr/bin/env python3
"""Turn the printable catalogue into STLs, and refuse to write a bad one.

    .venv/bin/python tools/printparts.py            # write out/print/
    .venv/bin/python tools/printparts.py --check    # report only, no files
    .venv/bin/python tools/printparts.py --part fork_plate

`fitcheck.py` asks whether the design is assembled somewhere a real one could
bolt to. This asks the next question: can each piece of it actually be made, and
will it come off an Ender 3 Pro. Two gates decide, and both refuse rather than
warn, because an STL that exists is an STL somebody will print:

  * WATERTIGHT -- a mesh with holes or flipped winding slices into nonsense. A
    part that fails here is a modelling bug, not a print setting.
  * BED -- axis-aligned first, then rotated 45 degrees, which is what actually
    gets a 255 mm fork plate onto a 215 mm bed. If neither fits, the part is
    named along with how many mm it is over.

Tessellation is `tools/meshkit.py`'s, much finer than the viewer's (0.02 mm /
0.1 rad against 0.1/0.3): facets that read as smooth on screen are visible ridges
in a O22 bearing seat. `caliper bundle` writes its meshes through the same
helper, so a part is watertight in both or in neither.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from meshkit import check_mesh, to_mesh  # noqa: E402
from paths import CAD, ROOT, require_cad  # noqa: E402

OUT = ROOT / "out" / "print"
require_cad()
if str(CAD) not in sys.path:
    sys.path.insert(0, str(CAD))

from build123d import Rot  # noqa: E402
import printing  # noqa: E402
from printing import BED, BOM, CATALOGUE, DENSITY, INFILL, OPEN_ISSUES  # noqa: E402


def bought() -> list[tuple]:
    """The bought half of the manifest: (item, qty, note).

    A design that declares its hardware with `catalog.use()` gets these counted
    from the model; one that still keeps a hand-written `BOM` list in
    printing.py gets that, unchanged. Printed and bought parts are two sections
    of one manifest either way.
    """
    rows = getattr(printing, "bom_rows", None)
    if callable(rows):
        derived = rows()
        if derived:
            return derived
    return list(BOM)


def lay_on_bed(mesh):
    """Drop to z=0 and centre in XY -- where a slicer expects to find a part."""
    b = mesh.bounds
    mesh.apply_translation([-(b[0][0] + b[1][0]) / 2, -(b[0][1] + b[1][1]) / 2, -b[0][2]])
    return mesh


def bed_fit(size):
    """(verdict, note) for a footprint on the Ender's bed."""
    x, y, z = size
    if z > BED[2]:
        return False, f"{z - BED[2]:.0f} mm too tall"
    if x <= BED[0] and y <= BED[1]:
        return True, "axis-aligned"
    # 45 degrees: a rectangle's rotated footprint is (x+y)/sqrt(2) on both axes.
    diag = (x + y) / math.sqrt(2)
    if diag <= BED[0] and diag <= BED[1]:
        return True, f"diagonal ({diag:.0f} mm per axis)"
    over = max(x - BED[0], y - BED[1], diag - BED[0])
    return False, f"{over:.0f} mm over, even on the diagonal"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="report only, write nothing")
    ap.add_argument("--part", help="build one part by name")
    args = ap.parse_args()

    if not CATALOGUE:
        print("cad/printing.py declares no printed parts yet — nothing to make.\n"
              "Add one with printed(name, build_fn); the example in that file works.",
              file=sys.stderr)
        return 1

    wanted = [p for p in CATALOGUE if not args.part or p.name == args.part]
    if not wanted:
        print(f"no such part: {args.part!r}", file=sys.stderr)
        print("known:", ", ".join(p.name for p in CATALOGUE), file=sys.stderr)
        return 2
    if not args.check:
        OUT.mkdir(parents=True, exist_ok=True)

    problems = 0
    rows = []
    total_g = {}
    print(f"{'part':18} {'qty':>3}  {'size mm':22} {'g ea':>6} {'bed':22} status")
    print("-" * 100)

    for p in wanted:
        solid = p.build()
        if any(p.orient):
            solid = Rot(*p.orient) * solid
        mesh = lay_on_bed(to_mesh(solid))
        bad = check_mesh(mesh)
        size = mesh.extents
        ok, note = bed_fit(size)
        if not ok:
            bad.append(f"BED: {note}")
        grams = mesh.volume / 1000.0 * DENSITY * INFILL
        total_g[p.material] = total_g.get(p.material, 0.0) + grams * p.qty

        status = "ok" if not bad else "!! " + "; ".join(bad)
        problems += bool(bad)
        print(f"{p.name:18} {p.qty:3}  "
              f"{size[0]:6.1f} x{size[1]:6.1f} x{size[2]:6.1f}  "
              f"{grams:6.1f} {note:22} {status}")

        rows.append({
            "name": p.name, "qty": p.qty, "material": p.material,
            "size": [round(float(v), 2) for v in size],
            "volume_cm3": round(mesh.volume / 1000.0, 1),
            "grams_each": round(grams, 1),
            "orient": list(p.orient), "supports": p.supports,
            "bed": note, "note": p.note, "problems": bad,
        })

        if bad or args.check:
            continue
        mesh.export((OUT / f"{p.name}.stl").as_posix())

    print("-" * 100)
    for mat, g in sorted(total_g.items()):
        print(f"  {mat}: {g / 1000:.2f} kg over {sum(p.qty for p in wanted if p.material == mat)} pieces")

    if not args.check and not args.part:
        write_manifest(rows, total_g)
        print(f"\nwrote {OUT}/  ({len([r for r in rows if not r['problems']])} STLs + manifest)")

    print(f"\n{'OK' if not problems else f'{problems} part(s) not printable'}")
    return 0


def write_manifest(rows, total_g):
    (OUT / "manifest.json").write_text(json.dumps(
        {"parts": rows, "bom": [{"item": i, "qty": q, "note": n} for i, q, n in bought()],
         "open_issues": [{"title": t, "detail": d} for t, d in OPEN_ISSUES],
         "filament_g": {k: round(v, 1) for k, v in total_g.items()},
         "bed": list(BED)}, indent=2))

    L = ["# Printed parts", "",
         f"Ender 3 Pro, usable {BED[0]:.0f} x {BED[1]:.0f} x {BED[2]:.0f} mm. "
         f"Fits are set in `cad/printing.py`; print `calibration.stl` first and "
         f"measure it before committing to the set.", "",
         "| part | qty | material | size mm | g each | bed | supports |",
         "|---|---|---|---|---|---|---|"]
    for r in rows:
        s = r["size"]
        L.append(f"| `{r['name']}` | {r['qty']} | {r['material']} | "
                 f"{s[0]:.0f} x {s[1]:.0f} x {s[2]:.0f} | {r['grams_each']:.0f} | "
                 f"{r['bed']} | {r['supports'] or '--'} |")
    L += ["", "Filament: " + ", ".join(f"**{v / 1000:.2f} kg {k}**"
                                       for k, v in sorted(total_g.items())), ""]

    L += ["## Notes per part", ""]
    for r in rows:
        if r["note"]:
            L.append(f"- **{r['name']}** -- {r['note']}")
    L += ["", "## Bought", "", "| item | qty | note |", "|---|---|---|"]
    for item, qty, note in bought():
        L.append(f"| {item} | {qty} | {note} |")

    L += ["", "## Not resolved", "",
          "Printing an STL does not settle any of these. Each is a decision.", ""]
    for title, detail in OPEN_ISSUES:
        L += [f"### {title}", "", detail, ""]
    (OUT / "manifest.md").write_text("\n".join(L) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
