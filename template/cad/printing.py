"""The printed machine: fits, fasteners and the catalogue of parts to make.

`parts/` owns the SHAPE of the design and `config.py` its dimensions. This module
owns everything that exists only because the thing gets printed — wall
thickness, hole compensation, bearing seats, heat-set bosses, split lines — and
assembles those into the list of solids `caliper print` turns into STLs.

Nothing here is imported by `model.py`, so the viewer's export loop never pays
for any of it, and a bore added for a bolt cannot perturb the physics.

Never put a hole size inline in a part: take it from the fits block below, so
one calibration coupon corrects the whole set.

The catalogue starts empty — there is nothing to print until you decide which
solids are printed parts rather than bought ones. Add one with `printed(...)`;
the commented example at the bottom is a working shape.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from build123d import Cylinder, Pos

from parts.hardware import along_x, along_y

# ------------------------------------------------------------------ fits ----
# One block, because these are the numbers a calibration coupon exists to
# correct. Print a coupon, measure it, change them here once.
WALL = 2.4          # 6 x 0.4 mm perimeters
FIT_SLIP = 0.20     # clearance where a printed part must slide onto something
FIT_PRESS = 0.05    # a bearing seat is its OD minus this, pressed in cold
BORE_COMP = 0.15    # FDM holes come out undersize; every round hole is grown by it

M3_CLEAR, M4_CLEAR = 3.4, 4.5
M3_INSERT, M4_INSERT = 4.0, 5.6       # heat-set bore...
M3_INSERT_D, M4_INSERT_D = 5.7, 8.0   # ...and how deep it sits

BED = (215.0, 215.0, 240.0)   # printable envelope, less clips and skirt
DENSITY = 1.24                # PLA, g/cm3
INFILL = 0.35                 # solid fraction at 4 perimeters + 20% gyroid

# (bore, OD, width)
BEARING = {"608": (8.0, 22.0, 7.0), "6001": (12.0, 28.0, 8.0)}
BEARING_KIND = "608"
SHAFT_D = BEARING[BEARING_KIND][0]


def bore(d: float) -> float:
    """A round hole's cut diameter: nominal, plus what the process loses."""
    return d + BORE_COMP


def hole(d: float, depth: float, at=(0, 0, 0), axis="z"):
    """A cutter for one round hole of nominal diameter `d`, centred on `at`."""
    c = Cylinder(bore(d) / 2, depth)
    if axis == "x":
        c = along_x(1) * c
    elif axis == "y":
        c = along_y(1) * c
    return Pos(at) * c


def bearing_seat(at=(0, 0, 0), axis="z", kind=BEARING_KIND, through=True, depth=None):
    """Cutter for a bearing pocket, plus the shaft clearance behind it.

    The pocket is the race's OD less FIT_PRESS — a printed seat wants a cold
    press, not a slip fit, or the outer race walks under load. BORE_COMP is
    deliberately NOT added: it compensates a hole that prints small, and a seat
    that prints small is exactly what a press fit needs.
    """
    d_in, d_out, w = BEARING[kind]
    depth = w + 0.2 if depth is None else depth
    cut = Pos((0, 0, depth / 2)) * Cylinder((d_out - FIT_PRESS) / 2, depth)
    if through:
        cut += Cylinder(bore(d_in + 2 * FIT_SLIP) / 2, 200)
    if axis == "x":
        cut = along_x(1) * cut
    elif axis == "y":
        cut = along_y(1) * cut
    return Pos(at) * cut


def insert_boss(size=3, at=(0, 0, 0), axis="z", wall=2.6, depth=None):
    """(boss, cutter) for one heat-set insert: a collar and the bore for it."""
    d = M3_INSERT if size == 3 else M4_INSERT
    deep = (M3_INSERT_D if size == 3 else M4_INSERT_D) if depth is None else depth
    boss = Cylinder(d / 2 + wall, deep + 1.5)
    cut = Pos((0, 0, 1.0)) * Cylinder(d / 2, deep + 2)   # no BORE_COMP: brass sets its own
    if axis == "x":
        boss, cut = along_x(1) * boss, along_x(1) * cut
    elif axis == "y":
        boss, cut = along_y(1) * boss, along_y(1) * cut
    return Pos(at) * boss, Pos(at) * cut


# ------------------------------------------------------------ catalogue ----
@dataclass
class PrintPart:
    name: str
    build: Callable            # -> a solid in its ASSEMBLY frame
    qty: int = 1
    material: str = "PLA"
    orient: tuple = (0.0, 0.0, 0.0)   # Rot(x,y,z) that lays it on the bed
    supports: str = ""                # empty means none needed
    note: str = ""
    tags: list = field(default_factory=list)


CATALOGUE: list[PrintPart] = []


def printed(name, build, **kw) -> PrintPart:
    p = PrintPart(name=name, build=build, **kw)
    CATALOGUE.append(p)
    return p


# Parts arrive in their ASSEMBLY frame — the frame `parts/` authored them in.
# Each entry carries the rotation that lays it on the bed; `caliper print` then
# drops it to z=0. So `orient` describes the print, and nothing about the print
# leaks back into the model.
#
# def _foot_pad():
#     from build123d import Sphere
#     from config import FOOT_R
#     return Sphere(FOOT_R) - Pos((0, 0, -FOOT_R)) * hole(SHAFT_D, 30)
#
# printed("foot_pad", _foot_pad, qty=4, material="TPU",
#         note="soft, so the feet grip and the impacts stop ringing the frame")

BOM: list[tuple] = []          # bought parts: (qty, description)
OPEN_ISSUES: list[str] = []    # what is not resolved yet, printed in the manifest
