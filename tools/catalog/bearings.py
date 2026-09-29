"""Deep-groove ball bearings.

The one family that is fully modelled -- solid, cutter and envelope -- because
it is the one where all three have to agree or the part does not assemble, and
because every workspace on this machine was already carrying its own two-entry
copy of this table:

    BEARING = {"608": (8.0, 22.0, 7.0), "6001": (12.0, 28.0, 8.0)}

A tuple you have to remember the field order of, duplicated in six files. Here
the same numbers arrive as an entry that also knows what it weighs, what pocket
it needs, and what a 608 costs.
"""

from catalog import hole, part, shaft


def _fit(fits, name, default):
    """Read one fit off the calling workspace's printing.py, however it is held.

    A pocket is a function of the real part AND of the printer that makes its
    housing, so the cutter cannot bake these in -- FIT_PRESS after a calibration
    coupon must move every seat in every design.
    """
    if fits is None:
        return default
    if isinstance(fits, dict):
        return fits.get(name, default)
    return getattr(fits, name, default)


def _race(bore, od, width, shield):
    from build123d import Cylinder, Pos
    ring = Cylinder(od / 2, width) - Cylinder(bore / 2, width + 2)
    if shield:
        # The shield face, a hair proud of the races, is what makes a render of
        # this read as a bearing rather than as a washer.
        for s in (1, -1):
            ring += Pos((0, 0, s * (width / 2 - 0.4))) * (
                Cylinder(od / 2 - 1.2, 0.8) - Cylinder(bore / 2 + 1.2, 0.8))
    return ring


def _seat(bore, od, width, fits):
    """The pocket plus the shaft clearance behind it.

    The outer race wants a cold press, so the pocket is OD less FIT_PRESS.
    BORE_COMP is deliberately NOT added: it compensates a hole that prints
    small, and a seat that prints small is exactly what a press fit needs.
    """
    from build123d import Cylinder, Pos
    press = _fit(fits, "FIT_PRESS", 0.05)
    slip = _fit(fits, "FIT_SLIP", 0.20)
    comp = _fit(fits, "BORE_COMP", 0.15)
    cut = Pos((0, 0, 0.1)) * Cylinder((od - press) / 2, width + 0.2)
    cut += Cylinder((bore + 2 * slip + comp) / 2, 200)
    return cut


def _envelope(od, width):
    from build123d import Cylinder
    return Cylinder(od / 2, width)      # a bearing sweeps nothing; it just sits


def _bearing(id, bore, od, width, mass, shield, provenance, verified="", **kw):
    spec = dict(bore=bore, od=od, width=width, shield=shield)
    return part(
        id, "bearing/deep-groove", spec,
        mass=mass,
        # Both sides of the bearing are mating features and both get named: the
        # bore is the hole a shaft turns in, and the outer race is itself a
        # MALE surface that a housing's seat closes on. Describing only the
        # housing's obligation left nothing to pair that obligation against.
        provides=[hole("bore", bore, "H7/h6", depth=width),
                  shaft("od", od, "press", depth=width)],
        requires=[hole("seat", od, "press", depth=width)],
        provenance=provenance, verified=verified,
        solid=lambda s=spec: _race(s["bore"], s["od"], s["width"], s["shield"]),
        cutter=lambda fits=None, s=spec: _seat(s["bore"], s["od"], s["width"], fits),
        envelope=lambda s=spec: _envelope(s["od"], s["width"]),
        **kw,
    )


# 608 is the skateboard bearing: the one that is in every drawer, and the reason
# an 8 mm joint shaft is the path of least resistance on a printed machine.
_bearing("bearing/608ZZ", 8.0, 22.0, 7.0, 0.012, "ZZ",
         "measured", "2026-08-12",
         source=dict(mpn="608ZZ", unit_price=0.40),
         note="metal shields; the cheap default")

_bearing("bearing/608-2RS", 8.0, 22.0, 7.0, 0.012, "2RS",
         "datasheet",
         source=dict(mpn="608-2RS", unit_price=0.55),
         note="rubber seals: more drag, keeps swarf out")

_bearing("bearing/688ZZ", 8.0, 16.0, 5.0, 0.006, "ZZ",
         "datasheet",
         source=dict(mpn="688ZZ", unit_price=0.70),
         note="same Ø8 bore in a much smaller housing, when the boss is tight")

_bearing("bearing/6001ZZ", 12.0, 28.0, 8.0, 0.022, "ZZ",
         "datasheet",
         source=dict(mpn="6001ZZ", unit_price=0.80),
         note="the step up when a Ø8 shaft is bending")
