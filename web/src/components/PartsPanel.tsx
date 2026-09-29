import { useEffect, useMemo, useState } from "react";
import { ChevronRight } from "lucide-react";
import type { Scene } from "@/lib/types";
import { Checkbox } from "@/components/ui/checkbox";
import { cn } from "@/lib/utils";

interface Part {
  name: string;
  color?: string;
  group: string;
}

// The parts list, shown as a corner overlay inside the render frame. Hiding a
// part is visual only — it toggles the body's visibility in the scene.
export default function PartsPanel({
  scene,
  setVisible,
}: {
  scene: Scene | null;
  setVisible: (name: string, on: boolean) => void;
}) {
  const groups = useMemo(() => {
    const m = new Map<string, Part[]>();
    if (scene) {
      const add = (p: { name: string; color?: string; group?: string }) => {
        const g = p.group || "other";
        if (!m.has(g)) m.set(g, []);
        m.get(g)!.push({ name: p.name, color: p.color, group: g });
      };
      for (const b of scene.bodies) add(b);
      for (const d of scene.decor || []) add(d);
    }
    return m;
  }, [scene]);

  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [open, setOpen] = useState<Set<string>>(new Set());

  // A freshly loaded scene starts fully visible.
  useEffect(() => {
    setHidden(new Set());
  }, [scene]);

  function toggle(name: string, on: boolean) {
    setVisible(name, on);
    setHidden((prev) => {
      const next = new Set(prev);
      if (on) next.delete(name);
      else next.add(name);
      return next;
    });
  }

  function toggleGroup(parts: Part[], on: boolean) {
    for (const p of parts) setVisible(p.name, on);
    setHidden((prev) => {
      const next = new Set(prev);
      for (const p of parts) (on ? next.delete(p.name) : next.add(p.name));
      return next;
    });
  }

  if (!scene || groups.size === 0) {
    return (
      <div className="px-3 py-2 text-xs text-muted-foreground">
        No parts loaded yet.
      </div>
    );
  }

  return (
    <div className="text-sm">
      {[...groups].map(([group, parts]) => {
        const isOpen = open.has(group);
        const allOn = parts.every((p) => !hidden.has(p.name));
        return (
          <div key={group} className="border-b border-border/60 last:border-0">
            <div className="flex items-center gap-2 px-3 py-1.5">
              <button
                className="text-muted-foreground transition-transform"
                onClick={() =>
                  setOpen((prev) => {
                    const next = new Set(prev);
                    isOpen ? next.delete(group) : next.add(group);
                    return next;
                  })
                }
                title={isOpen ? "Collapse" : "Expand"}
              >
                <ChevronRight
                  className={cn("h-4 w-4 transition-transform", isOpen && "rotate-90")}
                />
              </button>
              <Checkbox
                checked={allOn}
                onCheckedChange={(v) => toggleGroup(parts, v === true)}
              />
              <span className="flex-1 truncate">{group}</span>
              <span className="text-xs text-muted-foreground">{parts.length}</span>
            </div>
            {isOpen && (
              <div className="pb-1">
                {parts.map((p) => (
                  <label
                    key={p.name}
                    className="flex cursor-pointer items-center gap-2 py-1 pl-9 pr-3 hover:bg-accent/50"
                  >
                    <Checkbox
                      checked={!hidden.has(p.name)}
                      onCheckedChange={(v) => toggle(p.name, v === true)}
                    />
                    <span
                      className="inline-block h-2.5 w-2.5 shrink-0 rounded-full"
                      style={{ background: p.color || "#8b9bb4" }}
                    />
                    <span className="truncate text-xs">{p.name}</span>
                  </label>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
