import { useState } from "react";
import { Layers, Scan } from "lucide-react";
import type { UseViewer } from "@/hooks/useViewer";
import { agoFromDate } from "@/lib/format";
import PartsPanel from "@/components/PartsPanel";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";

// The render field: the WebGL canvas mounts into `containerRef`, with a small
// status line over it, the parts list as a corner overlay, and a stats strip
// beneath. It lives in its own resizable panel, so the editor never paints over
// it.
export default function Viewport({ v, hideParts = false }: { v: UseViewer; hideParts?: boolean }) {
  const [partsOpen, setPartsOpen] = useState(false);

  return (
    <div className="flex h-full flex-col bg-background">
      <div className="relative min-h-0 flex-1">
        <div ref={v.containerRef} className="absolute inset-0" />
        <div className="pointer-events-none absolute left-3 top-2 rounded bg-background/70 px-2 py-1 text-xs text-muted-foreground">
          {v.status}
        </div>

        {/* Parts live in the render frame now, not the agents rail — a corner
            overlay that toggles a scrollable list. Hiding a part is visual. */}
        {!hideParts && <div className="absolute right-2 top-2 z-10 flex max-h-[calc(100%-1rem)] flex-col items-end">
          <Button
            size="xs"
            variant={partsOpen ? "secondary" : "outline"}
            className="bg-background/80 backdrop-blur"
            onClick={() => setPartsOpen((o) => !o)}
            title="Show or hide individual parts"
          >
            <Layers /> Parts
            {v.stats.parts ? (
              <span className="ml-1 text-muted-foreground">{v.stats.parts}</span>
            ) : null}
          </Button>
          {partsOpen && (
            <div className="mt-1 flex max-h-full w-60 flex-col overflow-hidden rounded-md border bg-card/95 shadow-lg backdrop-blur">
              <ScrollArea className="min-h-0 flex-1">
                <PartsPanel scene={v.scene} setVisible={v.setVisible} />
              </ScrollArea>
            </div>
          )}
        </div>}
        <Button size="xs" variant="outline" className="absolute bottom-3 left-3 bg-background/80" onClick={v.fit} title="Fit model in the viewport"><Scan/>Fit view</Button>
      </div>

      <div className="flex flex-none flex-wrap items-center gap-x-4 gap-y-1 border-t bg-card px-3 py-1.5 text-xs text-muted-foreground">
        <span>
          parts <b className="text-foreground">{v.stats.parts || "—"}</b>
        </span>
        <span>
          size <b className="text-foreground">{v.stats.size}</b>
        </span>
        <span>
          built <b className="text-foreground">{agoFromDate(v.stats.builtAt)}</b>
        </span>
        {v.hasJoints && (
          <>
            <span className="mx-1 h-3 w-px bg-border" />
            <span className="inline-flex items-center gap-1.5">
              <span
                className="inline-block h-2 w-2 rounded-full"
                style={{
                  background: v.running
                    ? "hsl(var(--good))"
                    : "hsl(var(--muted-foreground))",
                }}
              />
              {v.running ? "running" : v.simSteps ? "paused" : "stopped"}
            </span>
            <span>
              t <b className="text-foreground">{v.simTime.toFixed(2)} s</b>
            </span>
            <span>
              step <b className="text-foreground">{v.simSteps}</b>
            </span>
            <span>
              joints <b className="text-foreground">{v.stats.joints}</b>
            </span>
          </>
        )}
      </div>
    </div>
  );
}
