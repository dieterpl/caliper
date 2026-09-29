import { useState } from "react";
import { Plus, TerminalSquare, X, Send, ChevronDown } from "lucide-react";
import { Button } from "./ui/button";
import { cn } from "@/lib/utils";

type Session = { id: number; name: string; lines: string[] };
export default function PrototypeSessions({ context }: { context: string }) {
  const [sessions, setSessions] = useState<Session[]>([{ id: 1, name: "Claude", lines: ["Demo session · odrive-quad", "Project context: components, assemblies and scene presets.", "Choose an object in the workbench to inspect it alongside your session."] }]);
  const [active, setActive] = useState(1);
  const [provider, setProvider] = useState("Codex");
  const [custom, setCustom] = useState("");
  const [prompt, setPrompt] = useState("");
  const [adding, setAdding] = useState(false);
  const session = sessions.find(s => s.id === active);
  function spawn() {
    const name = provider === "Custom CLI" ? custom.trim() : provider;
    if (!name) return;
    const id = Date.now();
    setSessions(s => [...s, { id, name, lines: [`${name} · prototype session`, "This demonstrates a Butai pane. Commands and agents run only in the real Docker workspace."] }]);
    setActive(id); setAdding(false);
  }
  function send() {
    if (!prompt.trim() || !session) return;
    setSessions(s => s.map(x => x.id === active ? { ...x, lines: [...x.lines, `› ${prompt.trim()}`, `Demo: request attached to ${context}. No CLI command was executed.`] } : x));
    setPrompt("");
  }
  return <aside className="flex h-full min-h-0 flex-col border-l bg-card" aria-label="Prototype Butai sessions">
    <div className="flex items-center gap-2 border-b px-3 py-3"><TerminalSquare size={16}/><span className="font-medium">Butai sessions</span><span className="flex-1"/><Button size="xs" variant="ghost" title="Add prototype session" onClick={() => setAdding(v => !v)}><Plus/></Button></div>
    <p className="border-b px-3 py-2 text-xs leading-5 text-muted-foreground">Your agents stay beside the design.<br/><span className="text-warn">Demo panes · no commands run</span></p>
    {adding && <div className="space-y-2 border-b bg-background p-3"><label className="text-xs text-muted-foreground" htmlFor="demo-provider">Agent or CLI</label><select id="demo-provider" value={provider} onChange={e => setProvider(e.target.value)} className="h-8 w-full rounded border bg-card px-2 text-xs">{["Claude", "Codex", "Gemini", "Shell", "Custom CLI"].map(p => <option key={p}>{p}</option>)}</select>{provider === "Custom CLI" && <input aria-label="Prototype custom CLI" placeholder="e.g. aider" value={custom} onChange={e => setCustom(e.target.value)} className="h-8 w-full rounded border bg-card px-2 text-xs"/>}<Button size="xs" className="w-full" disabled={provider === "Custom CLI" && !custom.trim()} onClick={spawn}>Add demo pane</Button></div>}
    <div className="flex flex-wrap gap-1 border-b p-2">{sessions.map(s => <button key={s.id} onClick={() => setActive(s.id)} className={cn("rounded px-2 py-1.5 text-xs hover:bg-accent", active === s.id && "bg-secondary text-primary")}>{s.name}</button>)}</div>
    <div className="flex items-center gap-2 border-b px-3 py-2 text-xs text-muted-foreground"><ChevronDown size={12}/>{session?.name || "No session"}<span className="flex-1"/>{session && <button title="Close prototype session" onClick={() => { const rest = sessions.filter(s => s.id !== active); setSessions(rest); setActive(rest[0]?.id || 0); }}><X size={13}/></button>}</div>
    <div className="min-h-0 flex-1 overflow-y-auto bg-background p-4 font-mono text-xs leading-6"><span className="text-primary">caliper</span><span className="text-muted-foreground"> / {context}</span>{session?.lines.map((line,i) => <p key={i} className={cn("mt-3 break-words", line.startsWith("›") ? "text-foreground" : "text-muted-foreground")}>{line}</p>)}{!session && <p className="mt-5 text-muted-foreground">Add a pane to explore agent and shell controls.</p>}</div>
    <form className="border-t p-3" onSubmit={e => { e.preventDefault(); send(); }}><label htmlFor="demo-prompt" className="mb-2 block text-xs text-muted-foreground">Try a request in the prototype</label><div className="flex gap-2"><input id="demo-prompt" value={prompt} onChange={e => setPrompt(e.target.value)} placeholder="Explain this component…" disabled={!session} className="min-w-0 flex-1 rounded border bg-background px-2 py-2 text-xs"/><Button size="xs" variant="secondary" type="submit" disabled={!session || !prompt.trim()} title="Send demo request"><Send size={13}/></Button></div></form>
  </aside>;
}
