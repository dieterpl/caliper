"""Parameterized hardware, in mm, centered at the origin with output along +Z.

These are assembly proxies, not manufacturing drawings: pulley teeth and motor
mounting patterns are deliberately omitted. No workspace config is imported.
Cached shapes are shared; transform them with Locations rather than mutating.
"""

from functools import lru_cache
from math import isfinite, pi


def _positive(**dimensions):
    for name, value in dimensions.items():
        if not isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be finite and positive, got {value!r}")


@lru_cache(maxsize=128)
def bldc_motor(diameter, length, shaft_diameter, shaft_length):
    """Cylindrical can centered on Z=0; shaft starts at Z=length/2."""
    from build123d import Cylinder, Pos

    _positive(diameter=diameter, length=length, shaft_diameter=shaft_diameter,
              shaft_length=shaft_length)
    if shaft_diameter >= diameter:
        raise ValueError("shaft_diameter must be smaller than diameter")
    return Cylinder(diameter / 2, length) + (
        Pos(0, 0, (length + shaft_length) / 2)
        * Cylinder(shaft_diameter / 2, shaft_length))


@lru_cache(maxsize=128)
def driver_board(width, height, thickness):
    """Box envelope centered at the origin, board in XY, thickness along Z."""
    from build123d import Box

    _positive(width=width, height=height, thickness=thickness)
    return Box(width, height, thickness)


@lru_cache(maxsize=128)
def timing_pulley(teeth, width, bore, pitch=2.0):
    """Smooth pitch-cylinder proxy, centered on Z, with 1 mm thick flanges."""
    from build123d import Cylinder, Pos

    _positive(teeth=teeth, width=width, pitch=pitch)
    if isinstance(teeth, bool) or int(teeth) != teeth:
        raise ValueError("teeth must be a positive integer")
    radius = teeth * pitch / (2 * pi)
    if not isfinite(bore) or not 0 <= bore < 2 * radius:
        raise ValueError("bore must be finite, nonnegative and smaller than pitch diameter")
    shape = Cylinder(radius, width)
    for side in (-1, 1):
        shape += Pos(0, 0, side * (width / 2 + 0.5)) * Cylinder(radius + 1.2, 1)
    if bore:
        shape -= Cylinder(bore / 2, width + 4)
    return shape


@lru_cache(maxsize=128)
def motor_envelope(diameter, length, shaft_diameter, shaft_length, clearance=0.0):
    """Occupied motor space, expanded radially and axially by clearance."""
    from build123d import Cylinder, Pos

    # Validate the original dimensions even when clearance would hide an error.
    bldc_motor(diameter, length, shaft_diameter, shaft_length)
    _clearance(clearance)
    return Cylinder(diameter / 2 + clearance, length + 2 * clearance) + (
        Pos(0, 0, (length + shaft_length) / 2)
        * Cylinder(shaft_diameter / 2 + clearance, shaft_length + 2 * clearance))


def _clearance(value):
    if not isfinite(value) or value < 0:
        raise ValueError("clearance must be finite and nonnegative")


@lru_cache(maxsize=128)
def board_envelope(width, height, thickness, clearance=0.0):
    _positive(width=width, height=height, thickness=thickness)
    _clearance(clearance)
    return driver_board(width + 2 * clearance, height + 2 * clearance,
                        thickness + 2 * clearance)


@lru_cache(maxsize=128)
def pulley_envelope(teeth, width, bore, pitch=2.0):
    """Conservative full cylinder: includes the bore as reserved shaft space."""
    from build123d import Cylinder

    timing_pulley(teeth, width, bore, pitch)
    return Cylinder(teeth * pitch / (2 * pi) + 1.2, width + 2)
