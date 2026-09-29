"""A software rasterizer, and a PNG writer, in numpy and the standard library.

There is no browser on this machine that can load the viewer, no PIL, no
matplotlib and no GPU — so if the agent building this design is ever going to
SEE it, the pixels have to be computed here. This module knows nothing about
the design: it takes triangles and gives back an RGB array.

Speed comes from batching rather than cleverness. Triangles are bucketed by
their screen-space bounding box and each bucket is rasterized in one vectorized
pass over a fixed sample grid; depth is resolved by sorting the resulting
fragments by (pixel, z) and keeping the first of each pixel. The handful of
triangles too big for the largest bucket fall back to a per-triangle loop,
which is affordable precisely because there are so few of them.

One thing to know if the output ever looks moth-eaten: point sampling drops
triangles smaller than a pixel. The CAD export tessellates to 0.1 mm, which at
these image sizes is a median triangle 0.02 px across — invisible to any
sampler. Render from a COARSE tessellation (tol ~1 mm), not from out/model.glb.
"""

from __future__ import annotations

import struct
import zlib

import numpy as np

# Bucket edge lengths in pixels. A triangle goes in the first bucket that can
# contain it; each bucket costs edge^2 samples per triangle, so the smallest one
# that fits is the cheapest.
BUCKETS = (2, 6, 18, 54)


def write_png(path, rgb: np.ndarray) -> None:
    """Write an (H, W, 3) uint8 array as a PNG."""
    h, w, _ = rgb.shape
    raw = np.zeros((h, w * 3 + 1), dtype=np.uint8)
    raw[:, 1:] = rgb.reshape(h, w * 3)      # filter byte 0 (None) per scanline

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw.tobytes(), 6))
           + chunk(b"IEND", b""))
    with open(path, "wb") as fh:
        fh.write(png)


class Canvas:
    """An RGB image with a z-buffer, drawn into in screen coordinates.

    Screen space is x right, y down, z INTO the screen (smaller is nearer).
    """

    def __init__(self, w: int, h: int, background=(18, 20, 26)):
        self.w, self.h = w, h
        self.rgb = np.tile(np.array(background, np.uint8), (h, w, 1))
        self.z = np.full(h * w, np.inf)

    # -- fragment plumbing -------------------------------------------------
    def _blend(self, pix, zs, cols):
        """Keep the nearest fragment per pixel, and paint it."""
        if len(pix) == 0:
            return
        order = np.lexsort((zs, pix))
        pix, zs, cols = pix[order], zs[order], cols[order]
        first = np.empty(len(pix), bool)
        first[0] = True
        first[1:] = pix[1:] != pix[:-1]
        pix, zs, cols = pix[first], zs[first], cols[first]
        win = zs < self.z[pix]
        pix, zs, cols = pix[win], zs[win], cols[win]
        self.z[pix] = zs
        flat = self.rgb.reshape(-1, 3)
        flat[pix] = cols

    def triangles(self, tri: np.ndarray, colors: np.ndarray,
                  clip: np.ndarray | None = None, bounds=None) -> None:
        """Draw triangles.

        `tri` is (N, 3, 3) of screen-space vertices, `colors` (N, 3) uint8.
        `clip`, if given, is (N, 3) of signed distances to a section plane:
        a vertex with a positive value is on the cut-away side. Triangles
        entirely cut away vanish; the ones straddling the plane are drawn only
        where they survive, which is what exposes the interior.

        `bounds` is (x0, y0, x1, y1), a scissor rectangle in pixels. Without it
        a triangle is clipped only to the canvas, so a caller drawing several
        views into one image relies on nothing ever overflowing its own pane —
        which stops being true the moment a camera is aimed by hand rather than
        auto-framed. Pass the pane and geometry cannot leak into its neighbour.
        """
        if len(tri) == 0:
            return
        bw = tri[:, :, 0].max(1) - tri[:, :, 0].min(1)
        bh = tri[:, :, 1].max(1) - tri[:, :, 1].min(1)
        size = np.maximum(bw, bh)
        done = np.zeros(len(tri), bool)
        for edge in BUCKETS:
            sel = (~done) & (size <= edge)
            done |= sel
            if sel.any():
                self._batch(tri[sel], colors[sel], edge,
                            None if clip is None else clip[sel], bounds)
        if (~done).any():
            self._big(tri[~done], colors[~done],
                      None if clip is None else clip[~done], bounds)

    def _scissor(self, bounds):
        """(x0, y0, x1, y1) clamped to the canvas; x1/y1 are exclusive."""
        if bounds is None:
            return 0, 0, self.w, self.h
        x0, y0, x1, y1 = bounds
        return (max(0, int(x0)), max(0, int(y0)),
                min(self.w, int(x1)), min(self.h, int(y1)))

    # -- the two rasterizers ----------------------------------------------
    def _batch(self, tri, colors, edge, clip, bounds=None):
        """One vectorized pass: every triangle sampled on its own edge×edge grid.

        A triangle smaller than a pixel would fall between the sample points, so
        the grid is anchored on the triangle's own bounding box and always
        includes its centroid — a sub-pixel triangle still lands one fragment
        rather than none.
        """
        n = len(tri)
        x0 = np.floor(tri[:, :, 0].min(1))
        y0 = np.floor(tri[:, :, 1].min(1))
        off = np.arange(edge)
        gx, gy = np.meshgrid(off, off)
        px = x0[:, None] + gx.ravel()[None, :] + 0.5
        py = y0[:, None] + gy.ravel()[None, :] + 0.5
        cx = tri[:, :, 0].mean(1)[:, None]
        cy = tri[:, :, 1].mean(1)[:, None]
        px = np.concatenate([px, cx], 1)
        py = np.concatenate([py, cy], 1)

        a, b, c = tri[:, 0], tri[:, 1], tri[:, 2]
        det = ((b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1])
               - (b[:, 1] - a[:, 1]) * (c[:, 0] - a[:, 0]))[:, None]
        det = np.where(np.abs(det) < 1e-12, np.nan, det)
        w1 = ((px - a[:, 0:1]) * (c[:, 1:2] - a[:, 1:2])
              - (py - a[:, 1:2]) * (c[:, 0:1] - a[:, 0:1])) / det
        w2 = ((b[:, 0:1] - a[:, 0:1]) * (py - a[:, 1:2])
              - (b[:, 1:2] - a[:, 1:2]) * (px - a[:, 0:1])) / det
        w0 = 1.0 - w1 - w2
        bx0, by0, bx1, by1 = self._scissor(bounds)
        ix, iy = px.astype(np.int64), py.astype(np.int64)
        m = ((w0 >= 0) & (w1 >= 0) & (w2 >= 0)
             & (ix >= bx0) & (ix < bx1) & (iy >= by0) & (iy < by1))
        m &= np.isfinite(w0)
        if clip is not None:
            m &= (w0 * clip[:, 0:1] + w1 * clip[:, 1:2] + w2 * clip[:, 2:3]) <= 0
        if not m.any():
            return
        z = w0 * a[:, 2:3] + w1 * b[:, 2:3] + w2 * c[:, 2:3]
        pix = (iy * self.w + ix)[m]
        cols = np.repeat(colors, px.shape[1], 0).reshape(n, px.shape[1], 3)[m]
        self._blend(pix, z[m], cols)

    def _big(self, tri, colors, clip, bounds=None):
        """Per-triangle fallback for the few that cover a lot of screen."""
        bx0, by0, bx1, by1 = self._scissor(bounds)
        for k in range(len(tri)):
            t = tri[k]
            if not np.isfinite(t).all():
                # A vertex at or behind a perspective eye projects to inf/nan.
                # int(floor(inf)) raises, and a nan bbox evades every bucket
                # test above, so this is the one place it would land.
                continue
            x0 = max(bx0, int(np.floor(t[:, 0].min())))
            x1 = min(bx1 - 1, int(np.ceil(t[:, 0].max())))
            y0 = max(by0, int(np.floor(t[:, 1].min())))
            y1 = min(by1 - 1, int(np.ceil(t[:, 1].max())))
            if x1 < x0 or y1 < y0:
                continue
            px, py = np.meshgrid(np.arange(x0, x1 + 1) + 0.5,
                                 np.arange(y0, y1 + 1) + 0.5)
            a, b, c = t[0], t[1], t[2]
            det = ((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]))
            if abs(det) < 1e-12:
                continue
            w1 = ((px - a[0]) * (c[1] - a[1]) - (py - a[1]) * (c[0] - a[0])) / det
            w2 = ((b[0] - a[0]) * (py - a[1]) - (b[1] - a[1]) * (px - a[0])) / det
            w0 = 1.0 - w1 - w2
            m = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
            if clip is not None:
                m &= (w0 * clip[k, 0] + w1 * clip[k, 1] + w2 * clip[k, 2]) <= 0
            if not m.any():
                continue
            z = w0 * a[2] + w1 * b[2] + w2 * c[2]
            iy, ix = np.nonzero(m)
            pix = (iy + y0) * self.w + (ix + x0)
            self._blend(pix, z[m], np.tile(colors[k], (m.sum(), 1)))

    # -- overlays ----------------------------------------------------------
    def line(self, p0, p1, color, width=1):
        """A 2D line, drawn over everything (no depth)."""
        x0, y0 = p0
        x1, y1 = p1
        n = int(max(abs(x1 - x0), abs(y1 - y0))) + 1
        xs = np.linspace(x0, x1, n).astype(int)
        ys = np.linspace(y0, y1, n).astype(int)
        for dx in range(width):
            for dy in range(width):
                x, y = xs + dx, ys + dy
                ok = (x >= 0) & (x < self.w) & (y >= 0) & (y < self.h)
                self.rgb[y[ok], x[ok]] = color

    def rect(self, x0, y0, x1, y1, color):
        x0, x1 = sorted((max(0, int(x0)), min(self.w, int(x1))))
        y0, y1 = sorted((max(0, int(y0)), min(self.h, int(y1))))
        self.rgb[y0:y1, x0:x1] = color

    def cross(self, x, y, color, r=5):
        self.line((x - r, y), (x + r, y), color)
        self.line((x, y - r), (x, y + r), color)


# ------------------------------------------------------------------ text ----
# A 3x5 bitmap font, because a label that cannot be drawn is a picture that
# cannot be read. Only the glyphs the views actually use.
GLYPHS = {
    "0": ("111", "101", "101", "101", "111"),
    "1": ("010", "110", "010", "010", "111"),
    "2": ("111", "001", "111", "100", "111"),
    "3": ("111", "001", "111", "001", "111"),
    "4": ("101", "101", "111", "001", "001"),
    "5": ("111", "100", "111", "001", "111"),
    "6": ("111", "100", "111", "101", "111"),
    "7": ("111", "001", "010", "010", "010"),
    "8": ("111", "101", "111", "101", "111"),
    "9": ("111", "101", "111", "001", "111"),
    "-": ("000", "000", "111", "000", "000"),
    "+": ("000", "010", "111", "010", "000"),
    ".": ("000", "000", "000", "000", "010"),
    ":": ("000", "010", "000", "010", "000"),
    "=": ("000", "111", "000", "111", "000"),
    " ": ("000", "000", "000", "000", "000"),
    "A": ("111", "101", "111", "101", "101"),
    "B": ("110", "101", "110", "101", "110"),
    "C": ("111", "100", "100", "100", "111"),
    "D": ("110", "101", "101", "101", "110"),
    "E": ("111", "100", "111", "100", "111"),
    "F": ("111", "100", "111", "100", "100"),
    "G": ("111", "100", "101", "101", "111"),
    "H": ("101", "101", "111", "101", "101"),
    "I": ("111", "010", "010", "010", "111"),
    "J": ("001", "001", "001", "101", "111"),
    "K": ("101", "101", "110", "101", "101"),
    "L": ("100", "100", "100", "100", "111"),
    "M": ("101", "111", "111", "101", "101"),
    "N": ("101", "111", "111", "111", "101"),
    "O": ("111", "101", "101", "101", "111"),
    "P": ("111", "101", "111", "100", "100"),
    "Q": ("111", "101", "101", "111", "011"),
    "R": ("111", "101", "110", "101", "101"),
    "S": ("111", "100", "111", "001", "111"),
    "T": ("111", "010", "010", "010", "010"),
    "U": ("101", "101", "101", "101", "111"),
    "V": ("101", "101", "101", "101", "010"),
    "W": ("101", "101", "111", "111", "101"),
    "X": ("101", "101", "010", "101", "101"),
    "Y": ("101", "101", "010", "010", "010"),
    "Z": ("111", "001", "010", "100", "111"),
}


def text(canvas: Canvas, x: int, y: int, s: str, color=(220, 226, 235), scale=2):
    """Draw an uppercase label. Returns the x where it ends."""
    for ch in s.upper():
        g = GLYPHS.get(ch)
        if g:
            for row, bits in enumerate(g):
                for col, bit in enumerate(bits):
                    if bit == "1":
                        canvas.rect(x + col * scale, y + row * scale,
                                    x + (col + 1) * scale, y + (row + 1) * scale,
                                    color)
        x += 4 * scale
    return x
