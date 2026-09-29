import { useEffect, useRef, useState } from "react";
import { Minus, Plus, Eraser, Trash2, Undo2, Redo2, Type } from "lucide-react";
import {
  parse,
  serialize,
  setCell,
  resize,
  blank,
  ink,
  type Grid,
} from "@/lib/grid";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

// The painted cell fills its background to the character's ink (see lib/grid),
// and the glyph is still drawn on top — so the ramp reads as tone, the densest
// chars read as solid, and any letter NOT in the ramp (a legend, a view label,
// a `=== VIEW: … ===` marker) has no fill and stays plainly readable.
const BRUSHES = ["█", "#", "@", "*", "+", "=", "-", ":", "."];

export default function GridEditor({
  initialText,
  readOnly,
  onChange,
}: {
  initialText: string;
  readOnly?: boolean;
  onChange: (text: string) => void;
}) {
  const [grid, setGrid] = useState<Grid>(() => parse(initialText));
  const [brush, setBrush] = useState(BRUSHES[0]);
  const [cell, setCellPx] = useState(12);
  // Paint drops one brush char per click/drag; text places a caret and types.
  const [tool, setTool] = useState<"paint" | "text">("paint");
  const painting = useRef(false);

  // The typing caret. The ref is the source of truth so a fast run of keys
  // advances against the latest position (state batches, a ref does not); the
  // mirror state only draws the ring. `anchor` is the column a run started at,
  // so Enter returns there; `typed` gates one snapshot per run, so a whole
  // typed run is a single Undo — like a paint stroke.
  const caretRef = useRef<{ x: number; y: number } | null>(null);
  const [caretUi, setCaretUi] = useState<{ x: number; y: number } | null>(null);
  const anchorRef = useRef(0);
  const typedRef = useRef(false);
  const setCaret = (c: { x: number; y: number } | null) => {
    caretRef.current = c;
    setCaretUi(c);
  };
  // Mirror the grid so a fast drag paints against the latest state, not the
  // stale one captured before the next render.
  const gref = useRef(grid);
  gref.current = grid;
  // The text we are in sync with — re-seed only when it differs (a fresh load or
  // an external change), never on the echo of our own edits.
  const synced = useRef(serialize(grid));

  // Undo/redo: snapshots kept in refs (always fresh for the key handler); a
  // small state mirror drives the buttons' enabled state.
  const undoRef = useRef<Grid[]>([]);
  const redoRef = useRef<Grid[]>([]);
  const [hist, setHist] = useState({ u: 0, r: 0 });
  const syncHist = () =>
    setHist({ u: undoRef.current.length, r: redoRef.current.length });

  useEffect(() => {
    if (initialText === synced.current) return;
    const g = parse(initialText);
    synced.current = initialText;
    gref.current = g;
    undoRef.current = [];
    redoRef.current = [];
    typedRef.current = false;
    setCaret(null);
    setGrid(g);
    syncHist();
  }, [initialText]);

  const commit = (next: Grid) => {
    if (next === gref.current) return;
    const text = serialize(next);
    synced.current = text;
    gref.current = next;
    setGrid(next);
    onChange(text);
  };

  // Push the current grid so one Undo reverts a whole stroke (or a clear/resize).
  const snapshot = () => {
    undoRef.current.push(gref.current);
    if (undoRef.current.length > 200) undoRef.current.shift();
    redoRef.current = [];
    syncHist();
  };
  const undo = () => {
    const prev = undoRef.current.pop();
    if (!prev) return;
    redoRef.current.push(gref.current);
    commit(prev);
    syncHist();
  };
  const redo = () => {
    const next = redoRef.current.pop();
    if (!next) return;
    undoRef.current.push(gref.current);
    commit(next);
    syncHist();
  };
  const edit = (next: Grid) => {
    snapshot();
    commit(next);
  };

  function paint(x: number, y: number, erase: boolean) {
    if (readOnly) return;
    commit(setCell(gref.current, x, y, erase ? " " : brush));
  }

  function cellAt(e: React.MouseEvent): [number, number] | null {
    const el = (e.target as HTMLElement).closest<HTMLElement>("[data-x]");
    if (!el) return null;
    return [Number(el.dataset.x), Number(el.dataset.y)];
  }

  // Typing into the grid, when the text tool holds a caret. Ctrl/⌘ is left to
  // the window undo/redo handler below (this returns early on it).
  function onGridKey(e: React.KeyboardEvent) {
    if (readOnly || tool !== "text" || e.ctrlKey || e.metaKey || e.altKey) return;
    const c = caretRef.current;
    if (!c) return;
    const cur = gref.current;
    const move = (x: number, y: number) => {
      typedRef.current = false; // a new spot begins a new undo group
      setCaret({ x, y });
    };
    switch (e.key) {
      case "Escape":
        e.preventDefault();
        return setCaret(null);
      case "ArrowLeft":
        e.preventDefault();
        return move(Math.max(0, c.x - 1), c.y);
      case "ArrowRight":
        e.preventDefault();
        return move(Math.min(cur.w - 1, c.x + 1), c.y);
      case "ArrowUp":
        e.preventDefault();
        return move(c.x, Math.max(0, c.y - 1));
      case "ArrowDown":
        e.preventDefault();
        return move(c.x, Math.min(cur.h - 1, c.y + 1));
      case "Enter":
        e.preventDefault();
        // Down a row, back to the column the run began at — like a line break.
        return setCaret({ x: anchorRef.current, y: Math.min(cur.h - 1, c.y + 1) });
      case "Backspace": {
        e.preventDefault();
        const x = Math.max(0, c.x - 1);
        if (!typedRef.current) (snapshot(), (typedRef.current = true));
        commit(setCell(cur, x, c.y, " "));
        return setCaret({ x, y: c.y });
      }
    }
    if (e.key.length === 1) {
      e.preventDefault();
      if (!typedRef.current) (snapshot(), (typedRef.current = true));
      commit(setCell(cur, c.x, c.y, e.key));
      // Advance, clamping at the last column so more typing overwrites the end.
      setCaret({ x: Math.min(cur.w - 1, c.x + 1), y: c.y });
    }
  }

  useEffect(() => {
    const up = () => (painting.current = false);
    window.addEventListener("mouseup", up);
    return () => window.removeEventListener("mouseup", up);
  }, []);

  // Ctrl/⌘+Z undo, ⇧ or Ctrl+Y redo. Bound once; the handlers read live refs.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (readOnly || !(e.ctrlKey || e.metaKey)) return;
      const k = e.key.toLowerCase();
      if (k === "z" && !e.shiftKey) {
        e.preventDefault();
        undo();
      } else if ((k === "z" && e.shiftKey) || k === "y") {
        e.preventDefault();
        redo();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [readOnly]);

  const g = grid;
  const brushBtn = (c: string) => (
    <button
      key={c}
      title={`paint ${c}`}
      disabled={readOnly}
      onClick={() => {
        setBrush(c);
        setTool("paint");
      }}
      className={cn(
        "flex h-6 w-6 items-center justify-center rounded border font-mono text-sm leading-none",
        tool === "paint" && brush === c
          ? "border-primary bg-primary/20 text-primary"
          : "border-border text-foreground hover:bg-accent",
      )}
    >
      {c}
    </button>
  );

  return (
    <div className="flex h-full flex-col">
      {/* toolbar */}
      <div className="flex flex-none flex-wrap items-center gap-1.5 border-b p-1.5">
        <Button size="xs" variant="ghost" disabled={readOnly || hist.u === 0}
          title="Undo (Ctrl+Z)" onClick={undo}>
          <Undo2 />
        </Button>
        <Button size="xs" variant="ghost" disabled={readOnly || hist.r === 0}
          title="Redo (Ctrl+Shift+Z)" onClick={redo}>
          <Redo2 />
        </Button>
        <span className="mx-1 h-5 w-px bg-border" />
        {BRUSHES.map(brushBtn)}
        <Button size="xs" variant={tool === "paint" && brush === " " ? "secondary" : "ghost"}
          disabled={readOnly} title="Erase — or right-drag"
          onClick={() => { setBrush(" "); setTool("paint"); }}>
          <Eraser /> erase
        </Button>
        <Button size="xs" variant={tool === "text" ? "secondary" : "ghost"}
          disabled={readOnly} title="Text — click a cell, then type"
          onClick={() => setTool("text")}>
          <Type /> text
        </Button>
        <Button size="xs" variant="ghost" disabled={readOnly} title="Erase all"
          onClick={() => edit(blank(g.w, g.h))}>
          <Trash2 /> clear
        </Button>
        <span className="mx-1 h-5 w-px bg-border" />
        <span className="font-mono text-xs text-muted-foreground">
          {g.w}×{g.h}
        </span>
        <div className="flex items-center gap-0.5">
          <Button size="xs" variant="outline" disabled={readOnly} title="Narrower"
            onClick={() => edit(resize(g, g.w - 1, g.h))}>
            <Minus />W
          </Button>
          <Button size="xs" variant="outline" disabled={readOnly} title="Wider"
            onClick={() => edit(resize(g, g.w + 1, g.h))}>
            <Plus />W
          </Button>
          <Button size="xs" variant="outline" disabled={readOnly} title="Shorter"
            onClick={() => edit(resize(g, g.w, g.h - 1))}>
            <Minus />H
          </Button>
          <Button size="xs" variant="outline" disabled={readOnly} title="Taller"
            onClick={() => edit(resize(g, g.w, g.h + 1))}>
            <Plus />H
          </Button>
        </div>
        <span className="mx-1 h-5 w-px bg-border" />
        <Button size="xs" variant="ghost" title="Smaller cells"
          onClick={() => setCellPx((p) => Math.max(6, p - 2))}>
          <Minus />
        </Button>
        <span className="w-8 text-center font-mono text-xs text-muted-foreground">
          {cell}px
        </span>
        <Button size="xs" variant="ghost" title="Bigger cells"
          onClick={() => setCellPx((p) => Math.min(40, p + 2))}>
          <Plus />
        </Button>
        {readOnly && (
          <span className="ml-auto text-xs text-muted-foreground">read-only</span>
        )}
      </div>

      {/* canvas */}
      <div className="min-h-0 flex-1 overflow-auto bg-background p-3">
        <div
          className="art-grid inline-block outline-none"
          tabIndex={0}
          style={
            {
              "--cell": `${cell}px`,
              fontSize: `${Math.round(cell * 0.82)}px`,
            } as React.CSSProperties
          }
          onContextMenu={(e) => e.preventDefault()}
          onKeyDown={onGridKey}
          onMouseDown={(e) => {
            const c = cellAt(e);
            if (!c) return;
            e.preventDefault();
            if (tool === "text") {
              if (readOnly) return;
              e.currentTarget.focus(); // so keystrokes land here, not the page
              anchorRef.current = c[0];
              typedRef.current = false;
              setCaret({ x: c[0], y: c[1] });
              return;
            }
            painting.current = true;
            snapshot();
            paint(c[0], c[1], e.button === 2);
          }}
          onMouseOver={(e) => {
            if (!painting.current) return;
            const c = cellAt(e);
            if (c) paint(c[0], c[1], (e.buttons & 2) !== 0);
          }}
        >
          {g.cells.map((row, y) => (
            <div key={y} className="flex">
              {Array.from(row).map((c, x) => {
                const a = ink(c);
                const isCaret =
                  tool === "text" && caretUi?.x === x && caretUi?.y === y;
                const style: React.CSSProperties = {};
                if (a > 0) style.background = `hsl(var(--foreground) / ${a})`;
                if (isCaret)
                  style.boxShadow = "inset 0 0 0 1px hsl(var(--primary))";
                return (
                  <span
                    key={x}
                    data-x={x}
                    data-y={y}
                    className="art-cell"
                    style={style}
                  >
                    {c === " " ? "" : c}
                  </span>
                );
              })}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
