"""The parts catalogue: real things, with part numbers, that a design uses.

It is `catalog` and not `parts` for a concrete reason: every workspace already
has a `cad/parts/` package of sub-assemblies, and `cad/` sits ahead of the
image on the child's PYTHONPATH so that a design always wins a name clash. A
shared module called `parts` would therefore be shadowed in exactly the
workspaces that wanted it, and the failure would look like a missing function.

A *part* is not a solid. It is a thing you can order or make, and it has several
faces depending on who is asking:

  * `solid`      what it looks like            -> the render and the viewer
  * `cutter`     the pocket or hole it needs   -> the printed part that holds it
  * `envelope`   space nothing may enter       -> the clearance sweep
  * `mass`       what it weighs                -> scene.json and the physics
  * the BOM row  what to buy, and how many     -> `caliper bom`

Those five used to live in five places -- the solid in a workspace's
`parts/hardware.py`, the pocket in its `printing.py`, the clearance nowhere, the
mass hand-typed in `config.py`, and the BOM as a list of hand-counted strings at
the bottom of `printing.py`. Keeping them consistent was a person's job, and the
quantity column was arithmetic somebody did in their head: change the model and
the number silently stops being true.

Here one entry emits all of them, and the quantity is COUNTED. A design declares
`use(...)` where it puts the hardware; placing a fifth leg makes the bearing
count go up in the same second the render does.

This module is shared by every workspace, so -- like everything else in `tools/`
-- it may not know one model's names or constants. A 608ZZ is a fact about the
world; `MOTOR_D` is a fact about one robot and does not belong here.

Usage, from a workspace's cad/:

    from catalog import use, get

    use("bearing/608ZZ", 2, where="hip fork plates")
    b = get("bearing/608ZZ")
    plate -= b.cutter(fits)          # the pocket, sized by YOUR printer's fits

and then `caliper bom`.
"""

from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass, field
from typing import Callable, Optional

# --------------------------------------------------------------- interfaces --
# What a part offers to its neighbours and what it needs from them, in one
# vocabulary. `kind` says which side of a pair this is: a hole is the female
# side, a shaft the male one, and clearance is always hole - shaft. Fit codes
# mean the same thing in every design on every machine, which is exactly the
# property that makes them safe to share.

FITS: dict[str, tuple[float, float]] = {
    # name        (min clearance, max clearance) in mm, hole - shaft
    "press":      (-0.08, -0.005),   # interference: the hole is SMALLER
    "H7/h6":      (0.000, 0.035),    # a located running fit
    "slip":       (0.050, 0.400),    # slides on by hand
    "clear":      (0.200, 1.200),    # a bolt through a hole
    "nominal":    (-9e9, 9e9),       # unstated: never checked
}


@dataclass(frozen=True)
class Interface:
    """One mating feature of a part, in its own frame."""
    name: str                  # "bore", "od", "seat", "thread"
    kind: str                  # "hole" | "shaft"
    d: float                   # nominal diameter, mm
    fit: str = "nominal"       # a key of FITS
    depth: float = 0.0         # engagement length, mm; 0 = unstated

    def __str__(self) -> str:
        return f"{self.name} Ø{self.d:.2f} {self.fit}"


def hole(name: str, d: float, fit: str = "nominal", depth: float = 0.0) -> Interface:
    return Interface(name, "hole", d, fit, depth)


def shaft(name: str, d: float, fit: str = "nominal", depth: float = 0.0) -> Interface:
    return Interface(name, "shaft", d, fit, depth)


# -------------------------------------------------------------------- parts --

PROVENANCE = ("measured", "datasheet", "guessed")


@dataclass
class Part:
    """One catalogue entry: a real thing, with a part number.

    `spec` is the dimensions that define it. `solid`, `cutter` and `envelope`
    are callables rather than shapes so that a tool which only wants the BOM
    never pays for build123d, and so that `cutter` can take the calling
    workspace's fits -- a pocket is a function of the real part AND of the
    printer that makes its housing.
    """
    id: str
    family: str
    spec: dict
    mass: float = 0.0                       # kg, one unit
    provides: tuple = ()                    # Interface, offered to neighbours
    requires: tuple = ()                    # Interface, needed from the housing
    source: dict = field(default_factory=dict)   # mpn, supplier, unit_price
    provenance: str = "guessed"
    verified: str = ""                      # ISO date the numbers were checked
    note: str = ""

    solid: Optional[Callable] = None        # () -> build123d shape
    cutter: Optional[Callable] = None       # (fits) -> shape to subtract
    envelope: Optional[Callable] = None     # () -> shape nothing may enter

    def iface(self, name: str) -> Interface:
        for i in (*self.provides, *self.requires):
            if i.name == name:
                return i
        raise KeyError(f"{self.id} has no interface {name!r}; "
                       f"it has {[i.name for i in (*self.provides, *self.requires)]}")

    @property
    def mpn(self) -> str:
        return self.source.get("mpn") or self.id.split("/")[-1]

    @property
    def price(self) -> Optional[float]:
        return self.source.get("unit_price")

    def __str__(self) -> str:
        return self.id


CATALOG: dict[str, Part] = {}
_LOADED = False


def part(id: str, family: str, spec: dict, **kw) -> Part:
    """Register one catalogue entry. Called by the modules under tools/catalog/."""
    if kw.get("provenance", "guessed") not in PROVENANCE:
        raise ValueError(f"{id}: provenance must be one of {PROVENANCE}")
    for key in ("provides", "requires"):
        if key in kw:
            kw[key] = tuple(kw[key])
    p = Part(id=id, family=family, spec=dict(spec), **kw)
    if id in CATALOG:
        raise ValueError(f"duplicate catalogue entry {id!r}")
    CATALOG[id] = p
    return p


def _load() -> None:
    """Import every module under tools/catalog/, once, on first lookup."""
    global _LOADED
    if _LOADED:
        return
    _LOADED = True          # set first: an entry module importing `catalog`
                            # must not send us back round here
    for mod in pkgutil.iter_modules(__path__):
        importlib.import_module(f"{__name__}.{mod.name}")


def get(id: str) -> Part:
    _load()
    try:
        return CATALOG[id]
    except KeyError:
        near = [k for k in CATALOG if k.split("/")[0] == id.split("/")[0]]
        raise KeyError(
            f"no catalogue part {id!r}."
            + (f" In that family: {', '.join(sorted(near))}" if near else
               f" Families: {', '.join(sorted({k.split('/')[0] for k in CATALOG}))}")
        ) from None


def all_parts() -> list[Part]:
    _load()
    return sorted(CATALOG.values(), key=lambda p: p.id)


def find(**q) -> list[Part]:
    """Search the catalogue the way you actually search for a part.

    `find(provides=8.0)` is "what gives me a 8 mm bore", which is the question
    a name search cannot answer. `family=` and `provenance=` narrow it.
    """
    out = []
    for p in all_parts():
        if "family" in q and not p.family.startswith(q["family"]):
            continue
        if "provenance" in q and p.provenance != q["provenance"]:
            continue
        if "provides" in q and not any(abs(i.d - q["provides"]) < 1e-6 for i in p.provides):
            continue
        if "requires" in q and not any(abs(i.d - q["requires"]) < 1e-6 for i in p.requires):
            continue
        out.append(p)
    return out


# -------------------------------------------------------------------- usage --
# The design declares where it puts hardware; the counting is ours. This is the
# whole point of the tier: `use()` inside leg() runs once per leg, so four legs
# is four times the bearings without anybody multiplying anything.


@dataclass
class Usage:
    id: str
    qty: int
    where: str


USED: list[Usage] = []
MATES: list[tuple] = []


def reset() -> None:
    """Clear recorded usage. Each tool run imports the model fresh, but a tool
    that imports it twice (or a test) must not double-count."""
    USED.clear()
    MATES.clear()


def use(id: str, qty: int = 1, where: str = "") -> Part:
    """Record that the design uses `qty` of this part here. Returns the entry."""
    p = get(id)                      # raises now, with the family listed, rather
                                     # than printing a mystery row at BOM time
    USED.append(Usage(id, int(qty), where))
    return p


def mate(a: str, a_iface: str, b: str, b_iface: str, where: str = "") -> None:
    """Declare that two parts fit together, so the arithmetic can be checked.

    A clash check cannot see a wrong fit: if the pocket was never cut for the
    bigger bearing the solids do not overlap, they simply will not assemble.
    """
    MATES.append((a, a_iface, b, b_iface, where))


# ---------------------------------------------------------------------- bom --


@dataclass
class Row:
    part: Part
    qty: int
    where: list

    @property
    def mass(self) -> float:
        return self.part.mass * self.qty

    @property
    def cost(self) -> Optional[float]:
        return None if self.part.price is None else self.part.price * self.qty


def bom() -> list[Row]:
    """Aggregate recorded usage into one row per part, heaviest family first."""
    rows: dict[str, Row] = {}
    for u in USED:
        r = rows.get(u.id)
        if r is None:
            rows[u.id] = Row(get(u.id), u.qty, [u.where] if u.where else [])
        else:
            r.qty += u.qty
            if u.where and u.where not in r.where:
                r.where.append(u.where)
    return sorted(rows.values(), key=lambda r: (r.part.family, r.part.id))


def total_mass() -> float:
    return sum(r.mass for r in bom())


# -------------------------------------------------------------------- check --


@dataclass
class Problem:
    level: str          # "fail" | "warn"
    what: str
    detail: str


def check() -> list[Problem]:
    """What the catalogue can tell you before anything is printed."""
    out: list[Problem] = []

    for r in bom():
        p = r.part
        tight = [i for i in (*p.provides, *p.requires) if i.fit == "press"]
        # A guessed dimension may not carry an interference fit. Everything else
        # about a guess is survivable; this one is a part that will not go in.
        if p.provenance == "guessed" and tight:
            out.append(Problem(
                "fail", p.id,
                f"provenance is a guess, but it carries a press fit "
                f"({', '.join(str(i) for i in tight)}). Measure it before "
                f"drawing a pocket for it."))
        elif p.provenance == "guessed":
            out.append(Problem(
                "warn", p.id, "provenance is a guess; clearance fits only."))

    # A screw into a printed part is almost always a screw AND an insert. If the
    # two counts disagree, either some of those screws go into something else or
    # one of the numbers is wrong -- and before the counts were derived there was
    # no way to notice. odrive-quad's hand-written BOM had 40 M4 screws and 20
    # M4 inserts, which is the case this check exists for.
    by_size: dict[int, dict[str, int]] = {}
    for r in bom():
        fam = r.part.family
        if fam.endswith(("screw", "insert")):
            size = r.part.spec.get("size")
            if size is not None:
                slot = by_size.setdefault(size, {"screw": 0, "insert": 0})
                slot["screw" if fam.endswith("screw") else "insert"] += r.qty
    for size, n in sorted(by_size.items()):
        if n["screw"] and n["insert"] and n["screw"] != n["insert"]:
            out.append(Problem(
                "warn", f"M{size} screws and inserts",
                f"{n['screw']} screws against {n['insert']} inserts. A screw into "
                f"a printed part needs one; the difference is either a nut, a "
                f"through-hole, or a miscount."))

    for a, ai, b, bi, where in MATES:
        pa, pb = get(a), get(b)
        ia, ib = pa.iface(ai), pb.iface(bi)
        if ia.kind == ib.kind:
            out.append(Problem("fail", f"{a}:{ai} ↔ {b}:{bi}",
                               f"both sides are a {ia.kind}; a pair needs one of each"))
            continue
        h, s = (ia, ib) if ia.kind == "hole" else (ib, ia)
        clearance = h.d - s.d
        # The tighter of the two declared fits governs: a part that asks for a
        # press fit does not get to be satisfied by a slip one.
        want = h.fit if h.fit != "nominal" else s.fit
        lo, hi = FITS.get(want, FITS["nominal"])
        if not (lo <= clearance <= hi):
            out.append(Problem(
                "fail", f"{a}:{ai} ↔ {b}:{bi}",
                f"Ø{h.d:.2f} hole on a Ø{s.d:.2f} shaft is "
                f"{clearance:+.3f} mm; a {want} fit wants {lo:+.3f} to {hi:+.3f}"
                + (f" ({where})" if where else "")))
    return out
