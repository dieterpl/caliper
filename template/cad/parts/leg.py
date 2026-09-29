"""One leg: a thigh and a shank, each on a servo'd hinge.

The frame rule, which is what breaks models when it is broken: every link is
authored in its OWN frame, centred on the joint it pivots about, and then placed
with `origin`. A part authored at its world position orbits that offset instead
of spinning cleanly. Joint `anchor` and `axis` are world coordinates at the rest
pose.

Here that means each link hangs DOWN from its own local origin: the thigh's
(0,0,0) is the hip, the shank's is the knee.
"""

from build123d import Cylinder, Pos, Sphere

from config import (
    C_FOOT, C_LINK, FOOT_R, HIP_LIMITS, HIP_X, HIP_Y, HIP_Z, KNEE_LIMITS,
    KNEE_Z, LINK_R, M_SHANK, M_THIGH, SERVO_DAMP, SERVO_STIFF, SHANK_L, THIGH_L,
)
from scene import body, motor, revolute


def servo(target=0.0):
    """A position servo holding `target` — what stands the robot up."""
    return motor(target_pos=target, stiffness=SERVO_STIFF, damping=SERVO_DAMP)


def leg(name: str, sx: int, sy: int):
    """Build one leg. `sx`/`sy` are ±1: front/back and left/right."""
    hip = (sx * HIP_X, sy * HIP_Y, HIP_Z)
    knee = (sx * HIP_X, sy * HIP_Y, KNEE_Z)

    # Hangs from its local origin, so (0,0,0) is the hip pivot.
    thigh = Pos((0, 0, -THIGH_L / 2)) * Cylinder(LINK_R, THIGH_L)
    body(f"{name}_thigh", thigh, mass=M_THIGH, origin=hip,
         color=C_LINK, group="legs")

    # Same again for the shank, with the foot pad on its end. The foot is a
    # sphere resting ON the floor, so its centre sits one radius above z=0 and
    # the leg lengths in config.py already account for that.
    shank = Pos((0, 0, -SHANK_L / 2)) * Cylinder(LINK_R * 0.8, SHANK_L)
    shank += Pos((0, 0, -SHANK_L)) * Sphere(FOOT_R)
    body(f"{name}_shank", shank, mass=M_SHANK, origin=knee,
         color=C_FOOT, friction=1.5, group="legs")

    # Both hinges pitch about world Y. Zero is the standing pose the geometry
    # was authored in, so the servos hold the robot exactly as drawn.
    revolute("chassis", f"{name}_thigh", anchor=hip, axis=(0, 1, 0),
             motor=servo(), limits=HIP_LIMITS, name=f"{name}_hip")
    revolute(f"{name}_thigh", f"{name}_shank", anchor=knee, axis=(0, 1, 0),
             motor=servo(), limits=KNEE_LIMITS, name=f"{name}_knee")
