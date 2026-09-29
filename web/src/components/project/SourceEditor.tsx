import { useEffect, useState } from "react";
import { workspaceFile } from "@/lib/api";
import { Button } from "@/components/ui/button";
export default function SourceEditor({ slug, project, path, busy, onSave, onDirty }: { slug: string; project: string; path: string; busy: boolean; onSave: (text: string) => Promise<boolean>; onDirty?: (dirty: boolean) => void }) {
  const [text, setText] = useState("");
  const [saved, setSaved] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    let live = true;
    fetch(workspaceFile(slug, [project, path].filter(Boolean).join("/"))).then(async r => { if (!r.ok) throw new Error("could not read source"); return r.text(); }).then(t => { if (live) { setText(t); setSaved(t); setError(""); } }).catch(e => live && setError(e.message));
    return () => { live = false; };
  }, [slug, project, path]);
  useEffect(() => { const guard = (e: BeforeUnloadEvent) => { if (text !== saved) { e.preventDefault(); e.returnValue = ""; } }; window.addEventListener("beforeunload", guard); return () => window.removeEventListener("beforeunload", guard); }, [text, saved]);
  useEffect(() => { onDirty?.(text !== saved); }, [text, saved, onDirty]);
  return <div className="flex h-full flex-col"><div className="flex items-center justify-between border-b bg-card px-3 py-2"><code className="text-xs">{[project, path].filter(Boolean).join("/")}{text !== saved ? " •" : ""}</code><Button size="xs" disabled={busy || text === saved || !!error} onClick={async () => { if (await onSave(text)) setSaved(text); }}>Save source</Button></div>{error ? <p className="p-4 text-destructive">{error}</p> : <textarea spellCheck={false} aria-label="Component source" className="min-h-0 flex-1 resize-none bg-background p-4 font-mono text-xs leading-6 outline-none" value={text} onChange={e => setText(e.target.value)} />}</div>;
}
