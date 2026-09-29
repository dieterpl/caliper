import { useEffect, useMemo, useRef, useState } from "react";
import { Save, X } from "lucide-react";
import { toast } from "sonner";
import { butai, workspaceFile } from "@/lib/api";
import { highlight, langOf, renderPatch } from "@/lib/highlight";
import { kindOf } from "@/lib/filekind";
import type { DocTarget } from "./FilesRail";
import GridEditor from "./GridEditor";
import SvgPreview from "./SvgPreview";
import ImagePreview from "./ImagePreview";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface Props {
  wsId: number;
  slug: string;
  target: DocTarget | null;
  onSaved: (path: string) => void;
  onClose: () => void;
  active?: boolean;
  onDirty?: (dirty: boolean) => void;
}

// The dock shows one file or one diff/commit. A file whose extension has a
// rendered form — a `.art` grid, a `.svg` picture — opens in that view, with
// its raw source and its git diff one toggle away; every other file is the
// syntax-highlighted editor as before. The editor is a highlighted <pre> behind
// a transparent <textarea> sharing exact metrics, so editing is native while
// the text underneath is coloured.
export default function Dock({ wsId, slug, target, onSaved, onClose, active = true, onDirty }: Props) {
  // What is loaded (file | diff | commit) and, for a file, how it is shown.
  const [view, setView] = useState<DocTarget | null>(target);
  const [mode, setMode] = useState<"render" | "source">("source");
  const [text, setText] = useState("");
  const [docHtml, setDocHtml] = useState<string | null>(null);
  const [readOnly, setReadOnly] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [placeholder, setPlaceholder] = useState("Pick a file from the tree.");
  useEffect(() => { onDirty?.(dirty); }, [dirty, onDirty]);
  useEffect(() => {
    if (!dirty) return;
    const guard = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", guard);
    return () => window.removeEventListener("beforeunload", guard);
  }, [dirty]);

  const taRef = useRef<HTMLTextAreaElement>(null);
  const preRef = useRef<HTMLPreElement>(null);
  const gutRef = useRef<HTMLPreElement>(null);

  // A new target: load it, and default a file to its rendered view when it has
  // one (a .art or .svg), else to source.
  useEffect(() => {
    setView(target);
    if (target && target.kind === "file")
      setMode(kindOf(target.path) === "code" ? "source" : "render");
  }, [target]);

  useEffect(() => {
    let live = true;
    setDocHtml(null);
    setDirty(false);
    if (!view) {
      setPlaceholder("Pick a file from the tree.");
      return;
    }
    (async () => {
      try {
        if (view.kind === "file") {
          // An image has no text form — the <img> fetches its bytes itself, so
          // don't pull it through the daemon's text endpoint (that would be
          // garbage) and leave it read-only.
          if (kindOf(view.path) === "image") {
            setReadOnly(true);
            setText("");
          } else {
            const f = await butai.file(wsId, view.path);
            if (!live) return;
            setReadOnly(!!f.truncated);
            setText(f.text || "");
          }
        } else if (view.kind === "diff") {
          const d = await butai.diff(wsId, view.path);
          if (!live) return;
          setDocHtml(renderPatch(d.patch || "(no differences)"));
        } else if (view.kind === "commit") {
          const d = await butai.show(wsId, view.rev);
          if (!live) return;
          setDocHtml(renderPatch(d.patch || "(empty commit)"));
        }
      } catch (e) {
        if (live) setPlaceholder("⚠ " + (e as Error).message);
      }
    })();
    return () => {
      live = false;
    };
  }, [view, wsId]);

  const lang = useMemo(
    () => (view && "path" in view ? langOf(view.path) : "text"),
    [view],
  );
  const highlighted = useMemo(() => highlight(text, lang) + "\n", [text, lang]);
  const gutter = useMemo(() => {
    const n = text.split("\n").length;
    let s = "";
    for (let i = 1; i <= n; i++) s += i + "\n";
    return s;
  }, [text]);

  function syncScroll() {
    if (!taRef.current) return;
    const top = taRef.current.scrollTop;
    const left = taRef.current.scrollLeft;
    if (preRef.current) {
      preRef.current.scrollTop = top;
      preRef.current.scrollLeft = left;
    }
    if (gutRef.current) gutRef.current.scrollTop = top;
  }

  async function save() {
    if (!view || view.kind !== "file" || readOnly) return;
    try {
      await butai.save(wsId, view.path, text);
      setDirty(false);
      onSaved(view.path);
    } catch (e) {
      toast.error("save failed: " + (e as Error).message);
    }
  }

  const isFile = view?.kind === "file";
  const path = view && "path" in view ? view.path : "";
  const kind = kindOf(path);
  // The rendered view (grid/preview); code files never have one.
  const rendering = isFile && mode === "render" && kind !== "code";
  const sourceView = isFile && view?.kind === "file" && !rendering;

  // Ctrl/Cmd+S saves whichever editable file is open — grid and preview included.
  useEffect(() => {
    if (!active || !isFile || readOnly) return;
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
        e.preventDefault();
        void save();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, isFile, readOnly, view, text, wsId]);

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Tab") {
      e.preventDefault();
      const ta = e.currentTarget;
      const s = ta.selectionStart;
      const en = ta.selectionEnd;
      const next = ta.value.slice(0, s) + "    " + ta.value.slice(en);
      setText(next);
      setDirty(true);
      requestAnimationFrame(() => {
        ta.selectionStart = ta.selectionEnd = s + 4;
      });
    }
  }

  const title =
    view == null
      ? "no file open"
      : view.kind === "commit"
        ? `${view.rev.slice(0, 7)}  ${view.subject}`
        : view.path + (dirty ? " ●" : "");

  // Which toggle buttons this target offers, and which is active.
  const activeTab = view?.kind === "diff" ? "diff" : mode;
  const tabs: { id: "render" | "source" | "diff"; label: string }[] = [];
  if (view && "path" in view) {
    if (kind !== "code")
      tabs.push({ id: "render", label: kind === "grid" ? "grid" : "preview" });
    // An image is only ever the picture — its bytes are not text to edit or diff.
    if (kind !== "image") {
      tabs.push({ id: "source", label: "source" });
      tabs.push({ id: "diff", label: "diff" });
    }
  }

  function pickTab(id: "render" | "source" | "diff") {
    if (!view || !("path" in view)) return;
    if (id === "diff") {
      if (dirty && !window.confirm("Discard unsaved file changes and open the diff?")) return;
      setView({ kind: "diff", path: view.path });
      return;
    }
    if (view.kind !== "file") setView({ kind: "file", path: view.path });
    setMode(id);
  }

  return (
    <div className="flex h-full flex-col bg-card">
      <div className="flex flex-none items-center gap-2 border-b px-2 py-1.5 text-xs">
        <span className={cn("truncate font-mono", dirty && "text-warn")}>
          {title}
        </span>
        <span className="flex-1" />
        {tabs.length > 0 && (
          <div className="flex overflow-hidden rounded border">
            {tabs.map((t) => (
              <button
                key={t.id}
                className={cn(
                  "px-2 py-0.5",
                  activeTab === t.id
                    ? "bg-accent text-foreground"
                    : "text-muted-foreground hover:bg-accent/50",
                )}
                onClick={() => pickTab(t.id)}
              >
                {t.label}
              </button>
            ))}
          </div>
        )}
        {isFile && !readOnly && (
          <Button size="xs" onClick={save} title="Save (Ctrl+S)">
            <Save /> save
          </Button>
        )}
        <Button size="xs" variant="ghost" onClick={onClose} title="Back to 3D">
          Back to 3D
          <X className="h-3.5 w-3.5" />
        </Button>
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-[auto_1fr]">
        <pre
          ref={gutRef}
          className="select-none overflow-hidden border-r bg-background px-2 py-2 text-right font-mono text-xs leading-[1.55] text-muted-foreground"
        >
          {sourceView ? gutter : ""}
        </pre>
        <div className="relative min-w-0 overflow-hidden">
          {view == null ? (
            <div className="flex h-full items-center justify-center p-5 text-center text-sm text-muted-foreground">
              {placeholder}
            </div>
          ) : docHtml != null ? (
            <pre
              className="code-layer doc absolute inset-0 overflow-auto p-2 font-mono text-xs leading-[1.55]"
              dangerouslySetInnerHTML={{ __html: docHtml }}
            />
          ) : rendering && kind === "grid" ? (
            <div className="absolute inset-0">
              <GridEditor
                initialText={text}
                readOnly={readOnly}
                onChange={(t) => {
                  setText(t);
                  setDirty(true);
                }}
              />
            </div>
          ) : rendering && kind === "svg" ? (
            <div className="absolute inset-0">
              <SvgPreview text={text} />
            </div>
          ) : rendering && kind === "image" ? (
            <div className="absolute inset-0">
              <ImagePreview src={workspaceFile(slug, path)} />
            </div>
          ) : (
            <>
              <pre
                ref={preRef}
                aria-hidden
                className="code-layer highlight pointer-events-none absolute inset-0 overflow-auto p-2 font-mono text-xs leading-[1.55]"
                dangerouslySetInnerHTML={{ __html: highlighted }}
              />
              <textarea
                ref={taRef}
                aria-label="File source"
                className="code-layer input absolute inset-0 resize-none overflow-auto whitespace-pre bg-transparent p-2 font-mono text-xs leading-[1.55] text-transparent caret-foreground outline-none"
                spellCheck={false}
                wrap="off"
                readOnly={readOnly}
                value={text}
                onChange={(e) => {
                  setText(e.target.value);
                  if (!dirty) setDirty(true);
                }}
                onScroll={syncScroll}
                onKeyDown={onKeyDown}
              />
            </>
          )}
        </div>
      </div>
    </div>
  );
}
