import { useCallback, useEffect, useMemo, useState } from "react";
import { ChevronRight, FilePlus } from "lucide-react";
import { toast } from "sonner";
import { app, butai } from "@/lib/api";
import { kindOf } from "@/lib/filekind";
import type { Changes, FileChange, History, TreeEntry } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";

export type DocTarget =
  | { kind: "file" | "diff"; path: string }
  | { kind: "commit"; rev: string; subject: string };

interface Props {
  wsId: number;
  slug: string;
  sel: string | null;
  refreshSignal: number;
  onOpen: (t: DocTarget) => void;
  onCheckout: (branch: string) => void;
}

const changePath = (f: FileChange | string) =>
  typeof f === "string" ? f : f.path;

// One directory level: fetches its own entries and recurses into open subdirs.
function Dir({
  wsId,
  path,
  depth,
  openDirs,
  changed,
  sel,
  reload,
  onPick,
}: {
  wsId: number;
  path: string;
  depth: number;
  openDirs: Set<string>;
  changed: Set<string>;
  sel: string | null;
  reload: number;
  onPick: (e: TreeEntry) => void;
}) {
  const [entries, setEntries] = useState<TreeEntry[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let live = true;
    butai
      .tree(wsId, path)
      .then((d) => live && setEntries(d.entries || []))
      .catch((e) => live && setError((e as Error).message));
    return () => {
      live = false;
    };
  }, [wsId, path, reload]);

  if (error)
    return (
      <div className="px-3 py-1 text-xs text-destructive">⚠ {error}</div>
    );
  if (!entries) return null;

  return (
    <>
      {entries.map((ent) => {
        const isOpen = openDirs.has(ent.path);
        const isChanged = ent.changed || changed.has(ent.path);
        return (
          <div key={ent.path}>
            <div
              className={cn(
                "flex cursor-pointer items-center gap-1 py-1 pr-2 text-sm hover:bg-accent/50",
                sel === ent.path && "bg-accent",
              )}
              style={{ paddingLeft: 8 + depth * 13 }}
              title={ent.path}
              onClick={() => onPick(ent)}
            >
              <span className="flex w-4 justify-center text-muted-foreground">
                {ent.is_dir ? (
                  <ChevronRight
                    className={cn("h-3.5 w-3.5 transition-transform", isOpen && "rotate-90")}
                  />
                ) : null}
              </span>
              <span
                className={cn(
                  "truncate",
                  ent.is_dir ? "font-medium" : "",
                  isChanged ? "text-warn" : "",
                )}
              >
                {ent.name}
              </span>
              {isChanged && <span className="ml-auto text-warn">●</span>}
            </div>
            {ent.is_dir && isOpen && (
              <Dir
                wsId={wsId}
                path={ent.path}
                depth={depth + 1}
                openDirs={openDirs}
                changed={changed}
                sel={sel}
                reload={reload}
                onPick={onPick}
              />
            )}
          </div>
        );
      })}
    </>
  );
}

export default function FilesRail({
  wsId,
  slug,
  sel,
  refreshSignal,
  onOpen,
  onCheckout,
}: Props) {
  const [mode, setMode] = useState<"files" | "changes">("files");
  const [openDirs, setOpenDirs] = useState<Set<string>>(new Set(["cad"]));
  const [changes, setChanges] = useState<Changes | null>(null);
  const [history, setHistory] = useState<History | null>(null);
  const [commitMsg, setCommitMsg] = useState("");
  const [committing, setCommitting] = useState(false);
  // Bumped after creating a file, so every open Dir refetches and shows it.
  const [treeKey, setTreeKey] = useState(0);

  const refresh = useCallback(async () => {
    try {
      setChanges(await butai.changes(wsId));
    } catch {
      /* daemon blip */
    }
    try {
      setHistory(await app.history(slug));
    } catch {
      /* mid-checkout — the list is rebuilt on the next tick */
    }
  }, [wsId, slug]);

  useEffect(() => {
    refresh();
    const t = window.setInterval(refresh, 2000);
    return () => window.clearInterval(t);
  }, [refresh, refreshSignal]);

  const staged = changes?.staged || [];
  const unstaged = changes?.unstaged || [];
  const commits = history?.commits || [];
  const head = history?.head || "";

  const changed = useMemo(() => {
    const s = new Set<string>();
    for (const f of staged) s.add(changePath(f));
    for (const f of unstaged) s.add(changePath(f));
    return s;
  }, [staged, unstaged]);

  function pick(ent: TreeEntry) {
    if (ent.is_dir) {
      setOpenDirs((prev) => {
        const next = new Set(prev);
        next.has(ent.path) ? next.delete(ent.path) : next.add(ent.path);
        return next;
      });
      return;
    }
    onOpen({ kind: "file", path: ent.path });
  }

  async function newFile() {
    const raw = window.prompt(
      "New file — a path in the workspace.\n" +
        "End it .art for a drawing grid, .svg for a picture.",
      "drawing.art",
    );
    if (raw == null) return;
    const path = raw.trim().replace(/^\/+/, "");
    if (!path) return;
    // Seed a .art with real spaces (50×50) so it opens as a sized canvas — a
    // trimmed blank would collapse to one column wide on reload.
    const seed =
      kindOf(path) === "grid" ? (" ".repeat(50) + "\n").repeat(50) : "";
    try {
      await butai.save(wsId, path, seed);
      setTreeKey((k) => k + 1);
      onOpen({ kind: "file", path });
      await refresh();
    } catch (e) {
      toast.error("could not create " + path + ": " + (e as Error).message);
    }
  }

  async function setStage(path: string, on: boolean) {
    try {
      if (on) await butai.stage(wsId, path);
      else await butai.unstage(wsId, path);
      await refresh();
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  async function commit() {
    const msg = commitMsg.trim();
    if (!msg || changed.size === 0) return;
    setCommitting(true);
    try {
      // Stage every change, then commit — one gesture, so the box never asks
      // the user to tick files first. The daemon has no bulk-stage, so walk the
      // unstaged files (already-staged ones need nothing).
      for (const f of unstaged) await butai.stage(wsId, changePath(f));
      await butai.commit(wsId, msg);
      setCommitMsg("");
      await refresh();
    } catch (e) {
      toast.error("commit failed: " + (e as Error).message);
    } finally {
      setCommitting(false);
    }
  }

  async function openVersion(rev: string) {
    const short = rev.slice(0, 7);
    if (
      !confirm(
        `Open version ${short}?\n\nIt is checked out on a branch of its own; ` +
          `the watcher re-exports and the viewport catches up.`,
      )
    )
      return;
    try {
      const r = await app.openVersion(slug, rev);
      await refresh();
      onCheckout(r.branch);
    } catch (e) {
      toast.error("could not open that version: " + (e as Error).message);
    }
  }

  return (
    <div className="flex h-full flex-col bg-card">
      <div className="flex flex-none items-center gap-2 border-b p-2">
        <Tabs value={mode} onValueChange={(v) => setMode(v as "files" | "changes")}>
          <TabsList>
            <TabsTrigger value="files">Files</TabsTrigger>
            <TabsTrigger value="changes" className="gap-1.5">
              Changes
              {changed.size > 0 && (
                <span className="rounded bg-primary/20 px-1 text-[10px] text-primary">
                  {changed.size}
                </span>
              )}
            </TabsTrigger>
          </TabsList>
        </Tabs>
        <span className="flex-1" />
        {mode === "files" && (
          <Button size="xs" variant="ghost" onClick={newFile} title="New file">
            <FilePlus /> New
          </Button>
        )}
      </div>

      <ScrollArea className="min-h-0 flex-1">
        {mode === "files" ? (
          <div className="py-1">
            <Dir
              wsId={wsId}
              path=""
              depth={0}
              openDirs={openDirs}
              changed={changed}
              sel={sel}
              reload={treeKey}
              onPick={pick}
            />
          </div>
        ) : (
          <ChangesView
            staged={staged}
            unstaged={unstaged}
            sel={sel}
            onStage={setStage}
            onOpenDiff={(p) => onOpen({ kind: "diff", path: p })}
          />
        )}

        {commits.length > 0 && (
          <div className="border-t">
            <div className="flex items-center gap-2 px-3 py-1.5 text-xs font-medium text-muted-foreground">
              <span>History</span>
              <span className="ml-auto">{commits.length}</span>
            </div>
            {commits.map((c, i) => {
              const isHead = c.id === head;
              return (
                <div
                  key={c.id}
                  className={cn(
                    "flex cursor-pointer items-center gap-2 px-3 py-1 text-xs hover:bg-accent/50",
                    isHead ? "text-foreground" : "text-muted-foreground",
                  )}
                  title="Click to show; double-click to open this version"
                  onClick={() => onOpen({ kind: "commit", rev: c.id, subject: c.summary || "" })}
                  onDoubleClick={() => openVersion(c.id)}
                >
                  <span
                    className={cn(
                      "inline-block h-1.5 w-1.5 shrink-0 rounded-full",
                      isHead ? "bg-primary" : "bg-transparent",
                    )}
                  />
                  <span className="font-mono text-muted-foreground">
                    {String(c.id).slice(0, 7)}
                  </span>
                  <span className="min-w-0 flex-1 truncate">{c.summary || ""}</span>
                  {i === 0 && (
                    <span className="shrink-0 rounded bg-muted px-1 text-[10px]">latest</span>
                  )}
                  {isHead && (
                    <span className="shrink-0 rounded bg-primary/20 px-1 text-[10px] text-primary">
                      here
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </ScrollArea>

      {/* Always here, on both tabs: type a line and commit — it stages every
          change for you, so there is nothing to tick first. */}
      <div className="flex flex-none flex-col gap-2 border-t p-2">
        <Textarea
          className="min-h-[52px] text-sm"
          placeholder="What changed about the design?"
          value={commitMsg}
          onChange={(e) => setCommitMsg(e.target.value)}
        />
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">
            {changed.size
              ? `stages & commits all ${changed.size} change${changed.size === 1 ? "" : "s"}`
              : "nothing to commit"}
          </span>
          <span className="flex-1" />
          <Button
            size="sm"
            onClick={commit}
            disabled={committing || changed.size === 0 || !commitMsg.trim()}
          >
            {committing ? "Committing…" : "Commit"}
          </Button>
        </div>
      </div>
    </div>
  );
}

function ChangesView({
  staged,
  unstaged,
  sel,
  onStage,
  onOpenDiff,
}: {
  staged: (FileChange | string)[];
  unstaged: (FileChange | string)[];
  sel: string | null;
  onStage: (path: string, on: boolean) => void;
  onOpenDiff: (path: string) => void;
}) {
  if (!staged.length && !unstaged.length)
    return (
      <div className="px-3 py-3 text-xs text-muted-foreground">
        Nothing has changed since the last commit.
      </div>
    );
  return (
    <div className="py-1">
      {staged.length > 0 && (
        <Group label="Staged" count={staged.length}>
          {staged.map((f) => (
            <FileRow
              key={changePath(f)}
              f={f}
              staged
              sel={sel}
              onStage={onStage}
              onOpenDiff={onOpenDiff}
            />
          ))}
        </Group>
      )}
      {unstaged.length > 0 && (
        <Group label="Unstaged" count={unstaged.length}>
          {unstaged.map((f) => (
            <FileRow
              key={changePath(f)}
              f={f}
              staged={false}
              sel={sel}
              onStage={onStage}
              onOpenDiff={onOpenDiff}
            />
          ))}
        </Group>
      )}
    </div>
  );
}

function Group({
  label,
  count,
  children,
}: {
  label: string;
  count: number;
  children: React.ReactNode;
}) {
  return (
    <div>
      <div className="flex items-center gap-2 px-3 py-1 text-xs font-medium text-muted-foreground">
        <span>{label}</span>
        <span className="ml-auto">{count}</span>
      </div>
      {children}
    </div>
  );
}

function FileRow({
  f,
  staged,
  sel,
  onStage,
  onOpenDiff,
}: {
  f: FileChange | string;
  staged: boolean;
  sel: string | null;
  onStage: (path: string, on: boolean) => void;
  onOpenDiff: (path: string) => void;
}) {
  const path = changePath(f);
  const fc = typeof f === "string" ? ({ path } as FileChange) : f;
  return (
    <div
      className={cn(
        "flex cursor-pointer items-center gap-2 px-3 py-1 text-xs hover:bg-accent/50",
        sel === path && "bg-accent",
      )}
      title={path}
      onClick={() => onOpenDiff(path)}
    >
      <button
        className={cn(
          "flex h-4 w-4 items-center justify-center rounded border text-[10px]",
          staged
            ? "border-primary bg-primary/20 text-primary"
            : "border-border text-transparent",
        )}
        title={staged ? "Unstage" : "Stage"}
        onClick={(e) => {
          e.stopPropagation();
          onStage(path, !staged);
        }}
      >
        ✓
      </button>
      <span className="flex-1 truncate">{path}</span>
      {fc.added || fc.deleted ? (
        <span className="font-mono">
          <span className="text-good">+{fc.added || 0}</span>{" "}
          <span className="text-destructive">−{fc.deleted || 0}</span>
        </span>
      ) : (
        <span className="text-muted-foreground">{fc.code || ""}</span>
      )}
    </div>
  );
}
