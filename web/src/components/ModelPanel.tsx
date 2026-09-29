import { useEffect, useMemo, useState } from "react";
import { Box, ChevronRight, Eye, EyeOff } from "lucide-react";
import type { Scene } from "@/lib/types";
import { cn } from "@/lib/utils";

export default function ModelPanel({ scene, name, selected, onSelect, setVisible }: {
  scene: Scene | null; name: string; selected: string | null;
  onSelect: (name: string | null) => void; setVisible: (name: string, visible: boolean) => void;
}) {
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const groups = useMemo(() => {
    const result = new Map<string, { name: string; color?: string }[]>();
    for (const part of [...scene?.bodies || [], ...scene?.decor || []]) {
      const group = part.group || "Parts";
      if (!result.has(group)) result.set(group, []);
      result.get(group)!.push(part);
    }
    return result;
  }, [scene]);
  useEffect(() => { setHidden(new Set()); }, [scene]);
  useEffect(() => {
    if (!selected) return;
    const group = [...groups].find(([, parts]) => parts.some(part => part.name === selected))?.[0];
    if (group) setOpen(current => new Set([...current, group]));
  }, [selected, groups]);
  return <div className="flex h-full min-h-0 flex-col bg-card" aria-label="Model structure">
    <div className="flex-none px-4 pb-2 pt-4 text-xs text-muted-foreground">Structure</div>
    <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
      <button className="mb-2 flex w-full items-center gap-2 rounded px-2 py-2 text-left text-xs hover:bg-accent" onClick={() => onSelect(null)} title="Clear part selection"><Box size={14}/><span className="truncate font-medium">{name}</span></button>
      {!scene && <p className="px-2 py-3 text-xs text-muted-foreground">Loading model structure…</p>}
      {[...groups].map(([group, parts]) => <section key={group} className="mb-1">
        <button aria-expanded={open.has(group)} className="flex w-full items-center gap-2 rounded px-2 py-2 text-left text-xs hover:bg-accent" onClick={() => setOpen(current => { const next = new Set(current); if (next.has(group)) next.delete(group); else next.add(group); return next; })}><ChevronRight size={12} className={cn("flex-none", open.has(group) && "rotate-90")}/><span className="min-w-0 flex-1 truncate">{group}</span><span className="text-[10px] text-muted-foreground">{parts.length}</span></button>
        {open.has(group) && parts.map(part => <div key={part.name} className={cn("group flex items-center rounded pl-6 pr-1 hover:bg-accent", selected === part.name && "bg-secondary text-primary")}>
          <button className="flex min-w-0 flex-1 items-center gap-2 py-2 text-left text-xs" title={`Inspect ${part.name}`} aria-pressed={selected === part.name} onClick={() => onSelect(part.name)}><span className="h-2 w-2 flex-none rounded-full bg-muted-foreground" style={part.color ? { background: part.color } : undefined}/><span className="truncate">{part.name}</span></button>
          <button className="rounded p-1 text-muted-foreground hover:bg-secondary" title={`${hidden.has(part.name) ? "Show" : "Hide"} ${part.name}`} aria-pressed={!hidden.has(part.name)} onClick={() => { const visible = hidden.has(part.name); setVisible(part.name, visible); setHidden(current => { const next = new Set(current); if (visible) next.delete(part.name); else next.add(part.name); return next; }); }}>{hidden.has(part.name) ? <EyeOff size={12}/> : <Eye size={12}/>}</button>
        </div>)}
      </section>)}
    </div>
  </div>;
}
