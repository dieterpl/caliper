"""GT2 pulleys and belt, and the plain stock a joint turns on.

Pulley geometry uses a shared parametric family: smooth pitch cylinders with
flanges and the catalogue bore. It is an assembly proxy, not a tooth profile
for manufacturing. Entries retain their mass, price and mating interfaces.

`caliper bom --geometry` lists what is still drawn by the design.
"""

from functools import partial

from catalog import hole, part, shaft
from subcomponents.geometry import pulley_envelope, timing_pulley

GT2_PITCH = 2.0     # mm per tooth


def _pulley(teeth, width, bore, mass, price, provenance="datasheet", **kw):
    # Pitch diameter is the formula, not a measurement: teeth * pitch / pi.
    pd = teeth * GT2_PITCH / 3.141592653589793
    return part(
        f"pulley/GT2-{teeth}T-{width:g}", "transmission/pulley",
        dict(teeth=teeth, width=width, bore=bore, pitch_d=round(pd, 2), profile="GT2"),
        mass=mass,
        provides=[hole("bore", bore, "H7/h6", depth=width)],
        provenance=provenance,
        source=dict(mpn=f"GT2-{teeth}T-{width:g}mm", unit_price=price),
        solid=partial(timing_pulley, teeth, width, bore, GT2_PITCH),
        envelope=partial(pulley_envelope, teeth, width, bore, GT2_PITCH),
        **kw,
    )


_pulley(15, 9.0, 8.0, 0.010, 3.20, note="drive pulley on the motor")
_pulley(16, 9.0, 8.0, 0.011, 2.90, note="idler, riding the slack side")
_pulley(30, 9.0, 8.0, 0.024, 4.10, note="1:1 transfer down a link")
_pulley(90, 9.0, 14.0, 0.086, 9.50, note="driven; 6:1 against the 15T")

part(
    "belt/GT2-9", "transmission/belt",
    dict(width=9.0, pitch=GT2_PITCH, thickness=1.8, profile="GT2"),
    mass=0.006,                       # per 200 mm loop, the usual length here
    provenance="datasheet",
    source=dict(mpn="GT2-9mm closed loop", unit_price=2.40),
    note="sold by loop length -- measure the span on the part before ordering",
)

# The joint shaft. Its diameter is NOT an independent choice: it is the bore of
# whichever bearing the design selected, which is why `SHAFT_D` ended up defined
# twice in odrive-quad -- 6.0 in config.py for the motor's own output stub, and
# 8.0 in printing.py derived from the 608. One name, two meanings. Two entries
# here, each with its own part number, is what makes the difference sayable.
part(
    "stock/shaft-8", "stock/shaft",
    dict(d=8.0, material="1.4301 stainless", cut_to_length=True),
    mass=0.0004,                      # per mm
    provides=[shaft("od", 8.0, "H7/h6")],
    provenance="measured", verified="2026-08-12",
    source=dict(mpn="Ø8 h6 ground shaft", unit_price=0.02),
    note="priced per mm; cut to length at assembly",
)

part(
    "stock/dowel-5", "stock/dowel",
    dict(d=5.0, length=16.0, material="hardened steel"),
    mass=0.0025,
    provides=[shaft("od", 5.0, "press")],
    provenance="datasheet",
    source=dict(mpn="Ø5×16 dowel", unit_price=0.09),
    note="locates a split line so the bolts do not have to",
)
