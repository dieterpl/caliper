"""The floor. The viewer's physics has gravity but creates no ground, so it
lives here."""

from build123d import Box, Pos

from config import C_GROUND
from scene import body

SLAB_T = 60.0


def ground(size: float = 40000.0):
    """A fixed slab whose TOP face is exactly z=0.

    Big on purpose. At a walking pace of ~225 mm/s a 4 m slab runs out after
    eight seconds, and a long simcheck run then reports a spectacular "collapse"
    that is really the robot stepping off the edge of the world. A slab is eight
    vertices, so the size costs nothing.
    """
    return body("ground", Pos((0, 0, -SLAB_T / 2)) * Box(size, size, SLAB_T),
                type="fixed", origin=(0, 0, 0), color=C_GROUND,
                friction=1.0, group="ground")
