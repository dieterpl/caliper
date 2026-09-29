import { useState } from "react";
import { Download } from "lucide-react";
import { app } from "@/lib/api";
import type { ApiError } from "@/lib/api";
import type { ExportRow } from "@/lib/types";
import { agoFromSeconds, humanSize } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

export default function ExportDialog({ slug }: { slug: string }) {
  const [open, setOpen] = useState(false);
  const [rows, setRows] = useState<ExportRow[]>([]);
  const [picked, setPicked] = useState<Set<string>>(new Set(["step", "stl"]));
  const [oneFilePerPart, setOneFilePerPart] = useState(false);
  const [includeScenery, setIncludeScenery] = useState(false);
  const [note, setNote] = useState("");
  const [bad, setBad] = useState(false);
  const [log, setLog] = useState("");
  const [building, setBuilding] = useState(false);

  async function onOpenChange(next: boolean) {
    setOpen(next);
    if (!next) return;
    setNote("");
    setBad(false);
    setLog("");
    setRows([]);
    try {
      const s = await app.exports(slug);
      setRows(s.formats || []);
    } catch (e) {
      setBad(true);
      setNote("could not read it: " + (e as Error).message);
    }
  }

  function toggle(id: string, on: boolean) {
    setPicked((prev) => {
      const next = new Set(prev);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });
  }

  async function build() {
    const formats = [...picked];
    if (!formats.length) return;
    setBuilding(true);
    setBad(false);
    setLog("");
    setNote(
      "running caliper bundle — a first build tessellates every part, so give it a moment.",
    );
    try {
      const r = await app.build(slug, {
        formats,
        parts: oneFilePerPart,
        all: includeScenery,
      });
      const fresh = r.formats || rows;
      setRows(fresh);
      const paths = fresh
        .filter((row) => picked.has(row.id))
        .flatMap((row) => [
          ...row.files,
          ...(oneFilePerPart ? row.parts || [] : []),
        ])
        .map((f) => f.path);
      if (!paths.length) {
        setBad(true);
        setNote("the build reported success but wrote nothing");
        setLog(r.log || "");
        return;
      }
      setNote(
        `built in ${r.seconds}s — downloading ${paths.length} file${paths.length > 1 ? "s" : ""}`,
      );
      location.href = app.downloadUrl(slug, paths);
    } catch (err) {
      const e = err as ApiError;
      setBad(true);
      setNote(e.message);
      const data = e.data;
      setLog((typeof data === "object" && data?.log) || "");
    } finally {
      setBuilding(false);
    }
  }

  const n = picked.size;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm" title="STEP, STL, 3MF, OBJ, GLB">
          <Download /> Export
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>
            Export{" "}
            <span className="font-normal text-muted-foreground">{slug}</span>
          </DialogTitle>
          <DialogDescription>
            Built on demand into <code>out/export/</code>. Anything already newer
            than <code>cad/</code> is reused, so a second export is instant.
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-3">
          <div className="rounded-md border">
            {rows.length === 0 && (
              <div className="px-3 py-2 text-sm text-muted-foreground">
                reading out/…
              </div>
            )}
            {rows.map((row) => {
              let status = (
                <span className="text-muted-foreground">not built</span>
              );
              if (row.files.length && row.stale)
                status = (
                  <span className="text-warn">
                    stale · {humanSize(row.bytes)}
                  </span>
                );
              else if (row.files.length)
                status = (
                  <span className="text-good">
                    {humanSize(row.bytes)} · {agoFromSeconds(row.mtime)}
                  </span>
                );
              return (
                <label
                  key={row.id}
                  className="flex cursor-pointer items-center gap-3 border-b px-3 py-2 last:border-0 hover:bg-accent/40"
                >
                  <Checkbox
                    checked={picked.has(row.id)}
                    onCheckedChange={(v) => toggle(row.id, v === true)}
                  />
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-medium">
                      {row.label}
                      {row.files.length > 1 && (
                        <span className="ml-1.5 text-xs text-muted-foreground">
                          {row.files.length} files
                        </span>
                      )}
                    </div>
                    <div className="truncate text-xs text-muted-foreground">
                      {row.what}
                    </div>
                  </div>
                  <div className="text-xs">{status}</div>
                </label>
              );
            })}
          </div>

          <div className="flex flex-wrap gap-4 text-sm">
            <label className="flex cursor-pointer items-center gap-2">
              <Checkbox
                checked={oneFilePerPart}
                onCheckedChange={(v) => setOneFilePerPart(v === true)}
              />
              One file per part
            </label>
            <label className="flex cursor-pointer items-center gap-2">
              <Checkbox
                checked={includeScenery}
                onCheckedChange={(v) => setIncludeScenery(v === true)}
              />
              Include the ground and other scenery
            </label>
          </div>

          {note && (
            <p className={cn("text-sm", bad ? "text-destructive" : "text-muted-foreground")}>
              {note}
            </p>
          )}
          {log && (
            <pre className="max-h-40 overflow-auto rounded-md border bg-background p-2 font-mono text-xs">
              {log}
            </pre>
          )}
        </div>

        <DialogFooter className="items-center">
          <span className="mr-auto text-xs text-muted-foreground">
            out/ is never committed
          </span>
          <Button variant="ghost" onClick={() => setOpen(false)} disabled={building}>
            Close
          </Button>
          <Button onClick={build} disabled={building || n === 0}>
            {building
              ? "building…"
              : n > 1
                ? `Build & download ${n} as a zip`
                : "Build & download"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
