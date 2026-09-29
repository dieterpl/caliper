// A character grid — the model behind a `.art` file. One char per cell, rows of
// equal width. This is deliberately plain text: it is exactly what `caliper
// draft` prints, so a grid drawn by hand and one emitted from the CAD model are
// the same file. Pure and browserless, so it can be unit-tested on its own.

export interface Grid {
  w: number;
  h: number;
  cells: string[]; // h strings, each exactly w chars wide
}

/** Text -> rectangular grid: split on newlines, pad every row to the widest. */
export function parse(text: string): Grid {
  const lines = text.replace(/\n$/, "").split("\n");
  const w = Math.max(1, ...lines.map((l) => l.length));
  const cells = lines.map((l) => l.padEnd(w, " ").slice(0, w));
  return { w, h: cells.length, cells };
}

/** Grid -> text: trailing spaces trimmed per row (invisible, and it keeps the
 *  file clean), a single terminating newline. `parse` fills them back in, so a
 *  ragged block round-trips. */
export function serialize(g: Grid): string {
  return g.cells.map((r) => r.replace(/[ ]+$/, "")).join("\n") + "\n";
}

/** A copy with one cell set to `ch` (first char only; empty -> space). Returns
 *  the SAME grid when nothing changes, so callers can skip needless work. */
export function setCell(g: Grid, x: number, y: number, ch: string): Grid {
  if (x < 0 || y < 0 || x >= g.w || y >= g.h) return g;
  const c = ch.length ? ch[0] : " ";
  const row = g.cells[y];
  if (row[x] === c) return g;
  const cells = g.cells.slice();
  cells[y] = row.slice(0, x) + c + row.slice(x + 1);
  return { ...g, cells };
}

/** Grow or crop to w×h, keeping the top-left anchored; new space is blank. */
export function resize(g: Grid, w: number, h: number): Grid {
  w = Math.max(1, Math.floor(w));
  h = Math.max(1, Math.floor(h));
  const cells: string[] = [];
  for (let y = 0; y < h; y++) {
    cells.push((g.cells[y] ?? "").padEnd(w, " ").slice(0, w));
  }
  return { w, h, cells };
}

// The drawing alphabet, light -> solid. A cell's fill opacity is its rank here;
// anything not in the ramp (space, letters, a legend, `=== VIEW: … ===`) has no
// fill and stays readable text. Kept beside the grid model so it is testable.
export const RAMP = ".:-=+*o#@█";

/** Fill opacity in [0,1] for a character: 0 for space/letters, up to 1 solid. */
export function ink(ch: string): number {
  const i = RAMP.indexOf(ch);
  return i < 0 ? 0 : (i + 1) / RAMP.length;
}

/** An empty w×h grid of spaces. */
export function blank(w: number, h: number): Grid {
  w = Math.max(1, Math.floor(w));
  h = Math.max(1, Math.floor(h));
  return { w, h, cells: Array.from({ length: h }, () => " ".repeat(w)) };
}
