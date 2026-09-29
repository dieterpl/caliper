"""Reusable helpers that are not specific to any one part of this design.

Everything here returns build123d geometry in a LOCAL frame centred on the
part's own axis, so callers place it with `origin`. Nothing here declares
bodies — the caller decides whether a piece is a rigid body or `decor`.
"""

from functools import lru_cache

from build123d import Box, Rot, fillet


# Parts are authored with their axis along +Z and rotated into place by these,
# which point that +Z at a chosen world direction. Mounts must be mirrored
# left/right: one fixed rotation for both sides leaves the right-hand parts
# facing the wrong way, which is very hard to see and trivial to measure.
def along_x(sign=1):
    """Aim the part's axis down world +X (sign=1) or -X (sign=-1)."""
    return Rot(0, 90 * sign, 0)


def along_y(sign=1):
    """Aim the part's axis down world +Y (sign=1) or -Y (sign=-1)."""
    return Rot(-90 * sign, 0, 0)


def soften(part, r: float, label: str = ""):
    """Round a part's edges, backing off until OCCT accepts, then giving up.

    A fillet fails when its radius does not fit the shortest edge it is asked to
    round, and one bad edge fails the whole operation — so short edges are
    dropped first and the radius is then walked down. A traceback here would
    leave the browser showing the last good model, so the last resort is the
    sharp part rather than no part at all.
    """
    for radius in (r, r * 0.6, r * 0.35):
        edges = [e for e in part.edges() if e.length > radius * 2.2]
        if not edges:
            continue
        try:
            return fillet(edges, radius)
        except Exception:  # noqa: BLE001 - try a smaller radius before giving up
            continue
    print(f"soften: no valid fillet at r<={r} on {label or 'part'}, edges left sharp")
    return part


@lru_cache(maxsize=None)
def rounded_box(length: float, width: float, height: float, r: float = 4.0):
    """A box with its edges already rounded.

    Round the PRIMITIVES, then fuse. OCCT will happily fillet a lone box but
    routinely refuses a built-up compound, because fusing leaves tangencies and
    slivers that no radius fits.
    """
    return soften(Box(length, width, height), r, f"box {length}x{width}x{height}")
