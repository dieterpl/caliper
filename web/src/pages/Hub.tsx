import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { app, artifact, butai } from "@/lib/api";
import type { SystemInfo, Workspace } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import NewDesignDialog from "@/components/NewDesignDialog";
import { Logo, Wordmark } from "@/components/Logo";

function Dot({ color }: { color: string }) {
  return (
    <span
      className="inline-block h-2 w-2 rounded-full"
      style={{ background: color }}
    />
  );
}

function Thumb({
  w,
  onOpen,
  onRendered,
}: {
  w: Workspace;
  onOpen: () => void;
  onRendered: () => void;
}) {
  const [broken, setBroken] = useState(false);
  const [rendering, setRendering] = useState(false);

  async function render(e: React.MouseEvent) {
    e.stopPropagation();
    setRendering(true);
    try {
      await app.build(w.slug, { formats: ["views"] });
      onRendered();
    } catch {
      setRendering(false);
    }
  }

  const showImg = w.thumb && !broken;
  return (
    <div
      className="flex aspect-video items-center justify-center overflow-hidden bg-background"
      onClick={onOpen}
    >
      {showImg ? (
        <img
          className="h-full w-full object-contain"
          src={artifact(w.slug, "views/model.png") + `?v=${w.thumb}`}
          alt=""
          onError={() => setBroken(true)}
        />
      ) : w.exported ? (
        <Button variant="ghost" size="sm" onClick={render} disabled={rendering}>
          {rendering ? "rendering…" : "Render a preview"}
        </Button>
      ) : (
        <span className="text-xs text-muted-foreground">not exported yet</span>
      )}
    </div>
  );
}

export default function Hub() {
  const navigate = useNavigate();
  const [list, setList] = useState<Workspace[]>([]);
  const [sub, setSub] = useState("…");
  const [sys, setSys] = useState<SystemInfo | null>(null);
  const [up, setUp] = useState<boolean | null>(null);
  // The empty state and the grid look the same before the first fetch lands,
  // so nothing decides between them until one has.
  const [loaded, setLoaded] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const { workspaces } = await app.workspaces();
      setList(workspaces);
      setLoaded(true);
      setSub(`${workspaces.length} on disk · /workspaces`);
    } catch (e) {
      setSub("could not read /workspaces: " + (e as Error).message);
    }
    try {
      setSys(await butai.system());
      setUp(true);
    } catch {
      setSys(null);
      setUp(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const t = window.setInterval(refresh, 4000);
    return () => window.clearInterval(t);
  }, [refresh]);

  async function remove(slug: string) {
    if (
      !confirm(
        `Remove "${slug}"?\n\nIt is closed and the folder moves to ` +
          `/workspaces/.trash — nothing is deleted.`,
      )
    )
      return;
    try {
      await app.remove(slug);
      refresh();
    } catch (e) {
      alert("could not remove it: " + (e as Error).message);
    }
  }

  const agents = list.reduce((n, w) => n + (w.agents || 0), 0);
  const panes = list.reduce((n, w) => n + (w.processes || 0), 0);
  const vitals: string[] = [
    `butai daemon ${up ? "up" : "down"}`,
    `agents ${agents}`,
    `panes ${panes}`,
  ];
  if (sys) {
    if (sys.cpu_pct != null) vitals.push(`cpu ${Math.round(sys.cpu_pct)}%`);
    if (sys.ram_used_gb != null)
      vitals.push(
        `ram ${sys.ram_used_gb.toFixed(1)} / ${(sys.ram_total_gb || 0).toFixed(0)} GB`,
      );
    const c = sys.containers;
    if (typeof c === "number") vitals.push(`containers ${c}`);
    else if (Array.isArray(c) && c.length) {
      const running = c.filter((x) => x.state === "running").length;
      vitals.push(`containers ${running} / ${c.length}`);
    }
  }

  return (
    <div className="flex h-full flex-col">
      <header className="flex flex-none items-center gap-3 border-b bg-card px-4 py-2.5">
        <Wordmark tagline />
        <Badge variant="muted" className="gap-1.5">
          <Dot
            color={
              up == null
                ? "hsl(var(--muted-foreground))"
                : up
                  ? "hsl(var(--good))"
                  : "hsl(var(--destructive))"
            }
          />
          {up == null ? "connecting…" : up ? "container healthy" : "daemon unreachable"}
        </Badge>
        <span className="flex-1" />
        <NewDesignDialog onCreated={(slug) => navigate(`/ws/${slug}`)} />
      </header>

      <div className="flex-1 overflow-auto p-5">
        <div className="mb-4 flex items-baseline gap-3">
          <h2 className="text-lg font-semibold">Designs</h2>
          <span className="text-sm text-muted-foreground">{sub}</span>
        </div>

        {loaded && list.length === 0 ? (
          <div className="flex flex-col items-center gap-4 py-20 text-center">
            <Logo size={56} mono className="opacity-20" />
            <div className="max-w-sm">
              <div className="font-medium">Nothing designed yet</div>
              <p className="mt-1 text-sm text-muted-foreground">
                A design is its own git repository with a <code>cad/</code>
                folder. Name one, say what it should be, and an agent starts
                from the template.
              </p>
            </div>
            <NewDesignDialog onCreated={(slug) => navigate(`/ws/${slug}`)} />
          </div>
        ) : (
          <div className="grid grid-cols-[repeat(auto-fill,minmax(260px,1fr))] gap-4">
            {list.map((w) => (
              <Card
                key={w.slug}
                className="cursor-pointer overflow-hidden transition-colors hover:border-primary/60"
                onContextMenu={(e) => {
                  e.preventDefault();
                  remove(w.slug);
                }}
              >
                <Thumb
                  w={w}
                  onOpen={() => navigate(`/ws/${w.slug}`)}
                  onRendered={() => refresh()}
                />
                <div className="p-3" onClick={() => navigate(`/ws/${w.slug}`)}>
                  <div className="flex items-center gap-2">
                    <span className="truncate font-medium">{w.slug}</span>
                    <span className="flex-1" />
                    {w.agents ? (
                      <Badge variant="muted" className="gap-1.5">
                        <Dot
                          color={
                            w.working
                              ? "hsl(var(--good))"
                              : w.waiting
                                ? "hsl(var(--warn))"
                                : "hsl(var(--muted-foreground))"
                          }
                        />
                        {w.agents} agent{w.agents > 1 ? "s" : ""}
                      </Badge>
                    ) : (
                      <Badge variant="muted">idle</Badge>
                    )}
                  </div>
                  <div className="mt-1 truncate text-xs text-muted-foreground">
                    {w.branch} · {w.dirty ? `${w.dirty} uncommitted` : "clean"}
                    {w.last?.when ? ` · ${w.last.when}` : ""}
                  </div>
                  <div className="mt-2 flex gap-4 text-xs text-muted-foreground">
                    <span>
                      parts{" "}
                      <b className="text-foreground">
                        {w.bodies == null ? "—" : w.bodies + (w.decor || 0)}
                      </b>
                    </span>
                    {w.joints ? (
                      <span>
                        joints <b className="text-foreground">{w.joints}</b>
                      </span>
                    ) : null}
                    <span>
                      commits <b className="text-foreground">{w.commits ?? 0}</b>
                    </span>
                  </div>
                </div>
              </Card>
            ))}

            <NewDesignCard onCreated={(slug) => navigate(`/ws/${slug}`)} />
          </div>
        )}
      </div>

      <div data-private="host-status" className="flex flex-none flex-wrap gap-x-4 gap-y-1 border-t bg-card px-4 py-2 font-mono text-xs text-muted-foreground">
        {vitals.map((v) => (
          <span key={v}>{v}</span>
        ))}
      </div>
    </div>
  );
}

// A card-shaped "new design" affordance that opens the same dialog.
function NewDesignCard({ onCreated }: { onCreated: (slug: string) => void }) {
  return (
    <Card className="flex min-h-[180px] items-center justify-center border-dashed p-4">
      <div className="flex flex-col items-center gap-2 text-center text-muted-foreground">
        <span className="text-2xl">+</span>
        <NewDesignDialog onCreated={onCreated} />
        <span className="text-xs">name it, say what it should be</span>
      </div>
    </Card>
  );
}
