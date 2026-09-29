"""Motors and the boards that drive them.

These are the expensive rows, and the ones where a count being wrong costs real
money -- which is the argument for deriving the count rather than remembering
it. odrive-quad's hand-written BOM said `("ODrive S1", 4, "3 axes each would be
4 boards for 12 -- check your wiring")`: a quantity with an unresolved question
about that quantity in the note column, because there was nowhere structured to
put one. `drives_axes` below is that structure, and `caliper bom` does the
division itself.
"""

from functools import partial

from catalog import part, shaft
from subcomponents.geometry import (
    bldc_motor, board_envelope, driver_board, motor_envelope,
)


def _clearance(fits):
    """Radial/axial hardware gap in mm; no printer-specific globals."""
    if fits is None:
        return 0.2
    if isinstance(fits, dict):
        return fits.get("HARDWARE_CLEARANCE", 0.2)
    return getattr(fits, "HARDWARE_CLEARANCE", 0.2)


def _motor_cutter(d, length, shaft_d, shaft_length, fits=None):
    return motor_envelope(d, length, shaft_d, shaft_length, _clearance(fits))


def _board_cutter(w, h, t, fits=None):
    return board_envelope(w, h, t, _clearance(fits))


def _motor(id, family, spec, **kw):
    dimensions = tuple(spec[k] for k in ("d", "length", "shaft_d", "shaft_length"))
    return part(id, family, spec,
                solid=partial(bldc_motor, *dimensions),
                envelope=partial(motor_envelope, *dimensions),
                cutter=partial(_motor_cutter, *dimensions), **kw)


def _board(id, family, spec, **kw):
    dimensions = tuple(spec[k] for k in ("w", "h", "t"))
    return part(id, family, spec,
                solid=partial(driver_board, *dimensions),
                envelope=partial(board_envelope, *dimensions),
                cutter=partial(_board_cutter, *dimensions), **kw)


_motor(
    "motor/MN5008", "actuator/bldc",
    dict(d=55.6, length=27.0, shaft_d=6.0, shaft_length=8.0, bolt_circle_r=12.5, kv=340),
    mass=0.135,
    provides=[shaft("output", 6.0, "H7/h6", depth=8.0)],
    provenance="datasheet",
    source=dict(mpn="T-Motor Antigravity MN5008", unit_price=42.00),
    note="pancake outrunner; drives from the BELL FACE bolt circle, not the stub",
)

_motor(
    "motor/GB36-1", "actuator/bldc",
    dict(d=36.0, length=38.0, shaft_d=8.0, shaft_length=20.0, bolt_circle_r=12.5, kv=100),
    mass=0.190,
    provides=[shaft("output", 8.0, "H7/h6", depth=20.0)],
    provenance="guessed",
    source=dict(mpn="GB36-1", unit_price=31.00),
    note="a smaller, slower alternative -- numbers are an estimate, not a sheet",
)

_board(
    "board/ODrive-S1", "electronics/driver",
    dict(w=70.0, h=70.0, t=16.0, drives_axes=1, v_max=56),
    mass=0.090,
    provenance="datasheet",
    source=dict(mpn="ODrive S1", unit_price=169.00),
    note="one axis per board; an S1 is not the 3-axis part it is often taken for",
)
