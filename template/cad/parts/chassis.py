"""The body the legs hang from."""

from config import BODY_H, BODY_L, BODY_R, BODY_W, BODY_Z, C_BODY, M_BODY
from parts.hardware import rounded_box
from scene import body


def chassis():
    """One rounded deck, centred on its own frame and placed at BODY_Z.

    Authored around (0,0,0) and positioned by `origin`, per the frame rule:
    whatever point of the part sits at its local origin is the point that lands
    on `origin`, and joint anchors are given in world coordinates.
    """
    return body(
        "chassis",
        rounded_box(BODY_L, BODY_W, BODY_H, BODY_R),
        mass=M_BODY,
        origin=(0, 0, BODY_Z),
        color=C_BODY,
        group="frame",
    )
