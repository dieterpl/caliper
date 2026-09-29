"""The CAD -> physics contract.

`model.py` imports these helpers to declare rigid *bodies* (build123d parts) and
the *joints*/motors connecting them. `export.py` reads the populated `SCENE` and
writes `out/model.glb` (named mesh per body) + `out/scene.json` (physics graph).

Author each body's geometry in its own LOCAL frame (around the joint it pivots
on), then give the body an `origin` = where that frame sits in the world. Joint
`anchor`/`axis` are given in WORLD coordinates at the rest pose.

`decor()` declares cosmetic hardware bolted to a body — motors, pulleys, belts.
It renders and toggles independently but never becomes a rigid body; its mass is
rolled into its parent so the physics still feels it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Body:
    name: str
    part: object                       # a build123d Solid/Part/Compound
    type: str = "dynamic"              # dynamic | fixed | kinematic
    mass: float = 1.0
    collider: str = "hull"            # hull | box | trimesh
    origin: tuple = (0.0, 0.0, 0.0)   # world position of the body's local frame
    color: Optional[str] = None       # e.g. "#3b82f6"
    friction: float = 0.7             # contact friction; feet want ~1.5
    group: str = "frame"              # UI visibility group


@dataclass
class Decor:
    """Cosmetic hardware rigidly attached to a body: motors, pulleys, belts.

    Rendered and toggled as its own node, but NOT a rigid body — it never
    reaches Rapier. `mass` is rolled into the parent body at export, so a motor
    still loads the link it is bolted to.
    """
    name: str
    part: object
    parent: str                        # body this is bolted to
    origin: tuple = (0.0, 0.0, 0.0)   # world position of this part's frame
    mass: float = 0.0                  # added to the parent body's mass
    color: Optional[str] = None
    group: str = "hardware"


@dataclass
class Joint:
    type: str                          # revolute | prismatic | fixed
    a: str                             # parent body name
    b: str                             # child body name
    anchor: tuple = (0.0, 0.0, 0.0)   # world point the joint pivots about
    axis: tuple = (0.0, 0.0, 1.0)     # world axis of rotation/translation
    motor: Optional[dict] = None
    limits: Optional[tuple] = None     # (lo, hi) in rad (revolute) or units (prismatic)
    # Appended last on purpose: the helpers below build Joint(...) positionally.
    name: Optional[str] = None         # stable handle, so a drive can address it
    drive: Optional[dict] = None       # periodic target, see gait()


DEFAULT_SETTINGS = {
    "timestep": 1.0 / 240.0,   # small steps keep stiff position servos stable
    "substeps": 4,             # physics steps per rendered frame
    "gravity": -2000.0,        # mm/s^2, deliberately gentler than reality
    "solver_iters": 8,
    # Seconds spent blending from the built rest pose into the gait. A trot has
    # its two diagonal pairs at opposite points of the stride, so at t=0 they get
    # opposite step commands -- a yaw kick that the robot, having nothing that
    # steers, then keeps forever. Ramping in costs one stride and removes it.
    # This works only because joint zero IS the standing pose (parts/leg.py):
    # scaling a target towards zero means "stand", not "straighten your legs".
    "gait_ramp": 1.5,
}


class Scene:
    def __init__(self) -> None:
        self.bodies: list[Body] = []
        self.joints: list[Joint] = []
        self.decor: list[Decor] = []
        self.settings: dict = dict(DEFAULT_SETTINGS)

    def reset(self) -> None:
        self.bodies.clear()
        self.joints.clear()
        self.decor.clear()
        self.settings = dict(DEFAULT_SETTINGS)


# One module-global scene, populated as a side effect of importing model.py.
SCENE = Scene()


def body(name: str, part, **kw) -> Body:
    b = Body(name=name, part=part, **kw)
    SCENE.bodies.append(b)
    return b


def decor(name: str, part, parent: str, **kw) -> Decor:
    d = Decor(name=name, part=part, parent=parent, **kw)
    SCENE.decor.append(d)
    return d


def revolute(a: str, b: str, anchor, axis=(0.0, 0.0, 1.0), motor=None, limits=None,
             name=None, drive=None) -> Joint:
    j = Joint("revolute", a, b, tuple(anchor), tuple(axis), motor, limits,
              name or f"{a}->{b}", drive)
    SCENE.joints.append(j)
    return j


def prismatic(a: str, b: str, anchor, axis=(0.0, 0.0, 1.0), motor=None, limits=None,
              name=None, drive=None) -> Joint:
    j = Joint("prismatic", a, b, tuple(anchor), tuple(axis), motor, limits,
              name or f"{a}->{b}", drive)
    SCENE.joints.append(j)
    return j


def fixed(a: str, b: str, anchor=(0.0, 0.0, 0.0)) -> Joint:
    j = Joint("fixed", a, b, tuple(anchor), name=f"{a}->{b}")
    SCENE.joints.append(j)
    return j


def motor(target_pos=0.0, target_vel=0.0, stiffness=0.0, damping=1.0) -> dict:
    """A drive on a joint.

    stiffness > 0 makes it a POSITION servo (a PD loop holding `target_pos`);
    stiffness == 0 leaves it a plain velocity motor chasing `target_vel`.
    """
    return {
        "target_pos": target_pos,
        "target_vel": target_vel,
        "stiffness": stiffness,
        "damping": damping,
    }


def gait(period, amplitude, phase=0.0, offset=0.0) -> dict:
    """A periodic target angle for a position servo:

        theta(t) = offset + amplitude * sin(2*pi * (t/period + phase))

    `phase` is in cycles (0.5 = half a cycle out of step), which is how the
    diagonal pairs of a trot are declared.
    """
    return {
        "period": period,
        "amplitude": amplitude,
        "phase": phase,
        "offset": offset,
    }


def trajectory(period, samples, phase=0.0) -> dict:
    """A sampled target angle: one stride of `samples`, wrapped and interpolated.

    Use this when the joint follows a real path (see cad/gait.py) rather than a
    sine. `phase` is in cycles, like gait().
    """
    return {
        "period": period,
        "phase": phase,
        "samples": [float(s) for s in samples],
    }


def sim(**kw) -> dict:
    """Override world settings: timestep, substeps, gravity, solver_iters."""
    unknown = set(kw) - set(DEFAULT_SETTINGS)
    if unknown:
        raise ValueError(f"sim(): unknown setting(s) {sorted(unknown)}")
    SCENE.settings.update(kw)
    return SCENE.settings
