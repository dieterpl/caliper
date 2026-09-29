"""Screws and heat-set inserts.

The two families where the quantity is genuinely hard to keep straight by hand,
because they are used everywhere and in pairs: a screw into a printed part is
almost always a screw AND an insert, and a BOM that has thirty of one and twenty
of the other is telling you something. `caliper bom` pairs them and says so.

Insert bores are `requires` rather than `provides`: brass sets its own diameter
on the way in, so the number that matters is the hole the printed part must
offer it.
"""

from catalog import hole, part, shaft

# (size, clearance hole, insert bore, insert depth)
_METRIC = {3: (3.4, 4.0, 5.7), 4: (4.5, 5.6, 8.0)}


def _shcs(size, length, mass, price):
    clear, _, _ = _METRIC[size]
    return part(
        f"fastener/M{size}-{length}-SHCS", "fastener/screw",
        dict(size=size, length=length, head="socket cap", clearance_d=clear),
        mass=mass,
        provides=[shaft("thread", float(size), "clear", depth=float(length))],
        provenance="datasheet",
        source=dict(mpn=f"M{size}×{length} SHCS A2", unit_price=0.06 if size == 3 else 0.09),
        note=f"needs a Ø{clear} clearance hole in the part it passes through",
    )


def _insert(size, mass, price):
    _, bore, depth = _METRIC[size]
    return part(
        f"insert/M{size}-heatset", "fastener/insert",
        dict(size=size, bore=bore, depth=depth),
        mass=mass,
        provides=[hole("thread", float(size), "nominal", depth=depth)],
        requires=[hole("bore", bore, "nominal", depth=depth)],
        provenance="measured", verified="2026-08-12",
        source=dict(mpn=f"M{size} heat-set insert", unit_price=price),
        note="no bore compensation: the brass sets its own diameter going in",
    )


_shcs(3, 10, 0.0012, 0.06)
_shcs(4, 16, 0.0034, 0.09)
_insert(3, 0.0008, 0.05)
_insert(4, 0.0019, 0.08)
