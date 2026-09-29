"""Reusable catalogue geometry and explicit attachment to a workspace scene.

Importing or building geometry never declares scene nodes or counts hardware.
Only attach() records one unit in the catalogue BOM. Geometry is centered at
the origin; origin is a world position, matching scene.decor's contract.
"""

from dataclasses import dataclass
from functools import lru_cache
from math import isfinite

import catalog

from .geometry import bldc_motor, driver_board, timing_pulley


def _vector(values, name):
    values = tuple(values)
    if len(values) != 3 or not all(isfinite(v) for v in values):
        raise ValueError(f"{name} must contain three finite numbers")
    return values


@lru_cache(maxsize=128)
def _rotate(shape, rotation):
    from build123d import Rot
    return shape if rotation == (0, 0, 0) else Rot(*rotation) * shape


def along_x(sign=1):
    """Euler angles pointing local +Z toward world +/-X."""
    if sign not in (-1, 1):
        raise ValueError("sign must be -1 or 1")
    return (0, 90 * sign, 0)


def along_y(sign=1):
    """Euler angles pointing local +Z toward world +/-Y."""
    if sign not in (-1, 1):
        raise ValueError("sign must be -1 or 1")
    return (-90 * sign, 0, 0)


@dataclass(frozen=True)
class Component:
    entry: catalog.Part

    def solid(self, rotation=(0, 0, 0)):
        if self.entry.solid is None:
            raise ValueError(f"{self.entry.id} has no shared solid")
        return _rotate(self.entry.solid(), _vector(rotation, "rotation"))

    def envelope(self, rotation=(0, 0, 0)):
        if self.entry.envelope is None:
            raise ValueError(f"{self.entry.id} has no shared envelope")
        return _rotate(self.entry.envelope(), _vector(rotation, "rotation"))

    def cutter(self, fits=None, rotation=(0, 0, 0)):
        """Local pocket geometry; fits are supplied by the calling design."""
        if self.entry.cutter is None:
            raise ValueError(f"{self.entry.id} has no shared cutter")
        return _rotate(self.entry.cutter(fits), _vector(rotation, "rotation"))

    def attach(self, scene, name, parent, *, origin=(0, 0, 0),
               rotation=(0, 0, 0), color=None, group="hardware"):
        """Attach as decor, add catalogue mass, and count exactly one BOM unit.

        Pass the workspace's scene MODULE explicitly. No import of a global
        workspace scene/config occurs in this package. Parent must already exist.
        """
        if not any(b.name == parent for b in scene.SCENE.bodies):
            raise ValueError(f"unknown parent body {parent!r}")
        if any(n.name == name for n in (*scene.SCENE.bodies, *scene.SCENE.decor)):
            raise ValueError(f"duplicate scene node {name!r}")
        origin = _vector(origin, "origin")
        shape = self.solid(rotation)
        node = scene.decor(name, shape, parent=parent, origin=origin,
                           mass=self.entry.mass, color=color, group=group)
        catalog.use(self.entry.id, where=name)
        return node


def get(id):
    """Look up reusable hardware without recording usage or loading CAD."""
    return Component(catalog.get(id))


__all__ = ["Component", "get", "along_x", "along_y", "bldc_motor",
           "driver_board", "timing_pulley"]
