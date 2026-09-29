import { useCallback, useEffect, useRef, useState } from "react";
import { ChevronRight, Plus, Terminal, X } from "lucide-react";
import { toast } from "sonner";
import { butai } from "@/lib/api";
import type { AgentStatus, PaneRow } from "@/lib/types";
import { Button } from "@/components/ui/button";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";
import { useAgentProviders } from "@/hooks/useAgentProviders";
import AgentTerminal from "@/components/AgentTerminal";
import { Input } from "@/components/ui/input";

const SAYS: Record<AgentStatus, string> = {
  working: "working",
  waiting: "waiting — it asked you something",
  finished: "finished its turn — your move",
  idle: "idle",
  exited: "exited",
};

const DOT: Record<AgentStatus, string> = {
  working: "hsl(var(--good))",
  waiting: "hsl(var(--warn))",
  finished: "hsl(var(--primary))",
  idle: "hsl(var(--muted-foreground))",
  exited: "hsl(var(--destructive))",
};

interface Props {
  wsId: number;
  slug: string;
  promptRequest?: { text: string; sequence: number } | null;
}

export default function AgentsRail({ wsId, promptRequest }: Props) {
  const [agents, setAgents] = useState<PaneRow[]>([]);
  const [procs, setProcs] = useState<PaneRow[]>([]);
  const [sel, setSel] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const { providers, loading: providersLoading, error: providersError, refresh: refreshProviders } = useAgentProviders();
  const [customOpen, setCustomOpen] = useState(false);
  const [command, setCommand] = useState("");
  const [connectionError, setConnectionError] = useState("");
  const [pasteRequest, setPasteRequest] = useState<{ pane: number; text: string; sequence: number } | null>(null);
  const handledPrompt = useRef<number>();

  useEffect(() => {
    if (!menuOpen) return;
    const dismiss = (event: KeyboardEvent) => { if (event.key === "Escape") setMenuOpen(false); };
    window.addEventListener("keydown", dismiss);
    return () => window.removeEventListener("keydown", dismiss);
  }, [menuOpen]);

  const since = useRef(new Map<number, { status: string; at: number }>());
  const selRef = useRef<number | null>(null);
  selRef.current = sel;

  const age = useCallback((pane: number, status: string) => {
    const prev = since.current.get(pane);
    if (!prev || prev.status !== status) {
      since.current.set(pane, { status, at: Date.now() });
      return "";
    }
    const s = Math.round((Date.now() - prev.at) / 1000);
    if (s < 45) return "";
    if (s < 5400) return `${Math.round(s / 60)}m`;
    return `${Math.round(s / 3600)}h`;
  }, []);

  const poll = useCallback(async (followNew?: "agent" | "proc") => {
    let detail;
    try {
      detail = await butai.workspace(wsId);
    } catch {
      setConnectionError("Connection interrupted. Retrying…");
      return;
    }
    setConnectionError("");
    const ag: PaneRow[] = (detail.agents || []).map((a) => {
      const reported = a.state as AgentStatus;
      const status: AgentStatus = a.exited != null ? "exited" : reported in SAYS ? reported : "idle";
      return {
        pane: a.pane,
        kind: "agent",
        title: a.title || `agent ${a.pane}`,
        sub: a.exited != null ? `exited (${a.exited})` : SAYS[status] || status,
        status,
        age: age(a.pane, status),
      };
    });
    const pr: PaneRow[] = (detail.processes || []).map((p) => {
      const status: AgentStatus =
        p.exited != null ? "exited" : p.status === "ok" ? "working" : "idle";
      return {
        pane: p.pane,
        kind: "proc",
        title: p.name || `pane ${p.pane}`,
        sub: p.command || "",
        status,
        age: p.status || "",
      };
    });
    setAgents(ag);
    setProcs(pr);

    // Follow the first agent on first sight; keep the user's choice otherwise.
    const all = [...ag, ...pr];
    if (followNew) {
      const rows = followNew === "agent" ? ag : pr;
      if (rows.length) select(rows[rows.length - 1].pane);
    } else if (selRef.current == null || !all.some((r) => r.pane === selRef.current)) {
      select(ag[0]?.pane ?? pr[0]?.pane ?? null);
    }
  }, [wsId, age]);

  useEffect(() => {
    setSel(null);
    poll();
    const t = window.setInterval(() => { void poll(); }, 2000);
    return () => window.clearInterval(t);
  }, [poll]);

  function select(pane: number | null) {
    selRef.current = pane;
    setSel(pane);
  }

  useEffect(() => {
    if (!promptRequest || handledPrompt.current === promptRequest.sequence) return;
    const target = agents.find(row => row.pane === sel) || agents[0];
    if (!target) return;
    handledPrompt.current = promptRequest.sequence;
    if (sel !== target.pane) select(target.pane);
    setPasteRequest({ ...promptRequest, pane: target.pane });
  }, [promptRequest, sel, agents]);

  async function spawn(type: string) {
    setMenuOpen(false);
    setBusy(true);
    try {
      await butai.spawnAgent(wsId, type);
      toast(`${type} starting…`);
      await poll("agent");
    } catch (e) {
      toast.error(`could not start ${type}: ` + (e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  // Closing a pane is the daemon's kill: the agent's session ends with it, so
  // ask first — unless it has already exited, where the row is just litter.
  async function close(r: PaneRow) {
    if (
      r.status !== "exited" &&
      !confirm(
        r.kind === "agent"
          ? `Close "${r.title}"?\n\nIts session ends. Anything it has already ` +
              `written stays in the design; anything it was mid-thought about ` +
              `is lost.`
          : `Stop "${r.title}"?`,
      )
    )
      return;
    try {
      await butai.killPane(wsId, r.pane);
      if (selRef.current === r.pane) select(null);
      poll();
    } catch (e) {
      toast.error(`could not close ${r.title}: ` + (e as Error).message);
    }
  }

  async function signInCodex() {
    setMenuOpen(false);
    setBusy(true);
    try {
      await butai.startProcess(wsId, "Codex sign-in", "codex login --device-auth");
      await poll("proc");
      toast("Open the link in the terminal and sign in with your ChatGPT account. Then add Codex.");
    } catch (error) {
      toast.error("Could not start Codex sign-in: " + (error as Error).message);
    } finally { setBusy(false); }
  }

  async function startShell() {
    setMenuOpen(false);
    setBusy(true);
    try {
      await butai.startProcess(wsId, "shell", "bash");
      toast("shell starting…");
      await poll("proc");
    } catch (e) {
      toast.error("could not start a shell: " + (e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function startCommand() {
    if (!command.trim() || busy) return;
    setBusy(true);
    try {
      await butai.startProcess(wsId, command.trim().split(/\s+/)[0], command.trim());
      setCustomOpen(false);
      setCommand("");
      await poll("proc");
    } catch (error) {
      toast.error("Could not start command: " + (error as Error).message);
    } finally { setBusy(false); }
  }

  return (
    <div className="flex h-full flex-col bg-card">
      <div className="flex flex-none items-center gap-2 border-b px-3 py-2">
        <Terminal className="h-4 w-4 text-muted-foreground" />
        <span className="font-medium">Agents</span>
        <span className="rounded bg-muted px-1.5 text-xs text-muted-foreground">
          {agents.length}
        </span>
        <span className="flex-1" />
        <div className="relative">
          <Button
            size="xs"
            variant="outline"
            onClick={() => { if (!menuOpen) void refreshProviders(); setMenuOpen((o) => !o); }}
            disabled={busy}
            aria-expanded={menuOpen}
            title="Start an agent — or a shell to sign in / run commands"
          >
            <Plus /> Add
          </Button>
          {menuOpen && (
            <>
              {/* click-away backdrop */}
              <div className="fixed inset-0 z-40" onClick={() => setMenuOpen(false)} />
              <div className="absolute right-0 z-50 mt-1 w-72 rounded-md border bg-popover p-1 text-popover-foreground shadow-md">
                <p className="px-2 py-1 text-xs text-muted-foreground">Agent CLIs in this container</p>
                {providersLoading && <p role="status" className="px-2 py-2 text-xs text-muted-foreground">Checking installed providers…</p>}
                {providersError && <p className="px-2 py-2 text-xs text-destructive">{providersError}</p>}
                {providers.map((provider) => (
                  <button
                    key={provider.name}
                    disabled={!provider.available || providersLoading}
                    className="flex w-full flex-col items-start rounded px-2 py-1.5 text-sm hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50"
                    onClick={() => spawn(provider.name)}
                  >
                    {provider.label}
                    <span className="text-xs text-muted-foreground">{provider.status}</span>
                  </button>
                ))}
                <div className="my-1 h-px bg-border" />
                {providers.some(provider => provider.name === "codex" && provider.available) && <button
                  className="flex w-full flex-col items-start rounded px-2 py-1.5 text-sm hover:bg-accent"
                  onClick={() => void signInCodex()}>
                  Sign in to Codex
                  <span className="text-xs text-muted-foreground">Use your ChatGPT account · no API key</span>
                </button>}
                <button
                  className="flex w-full items-center rounded px-2 py-1.5 text-sm hover:bg-accent"
                  onClick={startShell}
                >
                  Shell
                  <span className="ml-auto font-mono text-xs text-muted-foreground">
                    bash
                  </span>
                </button>
                <button className="flex w-full items-center rounded px-2 py-1.5 text-sm hover:bg-accent"
                  onClick={() => { setMenuOpen(false); setCustomOpen(true); }}>Run any CLI / command…</button>
                <p className="px-2 py-1.5 text-xs text-muted-foreground">Missing a CLI? Install it or sign in from a shell, then reopen this menu.</p>
              </div>
            </>
          )}
        </div>
      </div>

      {connectionError && <p role="status" className="border-b px-3 py-2 text-xs text-warn">{connectionError}</p>}
      {customOpen && <form className="grid gap-2 border-b p-3" onSubmit={(event) => { event.preventDefault(); void startCommand(); }}>
        <label htmlFor={`cli-command-${wsId}`} className="text-xs font-medium">Command in this workspace</label>
        <Input id={`cli-command-${wsId}`} autoFocus placeholder="aider, npm run dev, python…" value={command} onChange={(event) => setCommand(event.target.value)} disabled={busy} />
        <p className="text-xs text-muted-foreground">Runs inside this Docker container in a live Butai terminal. For agent status tracking, configure a launcher in ~/.butai/config.toml.</p>
        <div className="flex gap-2"><Button type="submit" size="xs" disabled={busy || !command.trim()}>Run command</Button><Button type="button" size="xs" variant="ghost" onClick={() => setCustomOpen(false)}>Cancel</Button></div>
      </form>}

      <div className="max-h-48 flex-none overflow-y-auto border-b" role="group" aria-label="Project agents">
            <div>
              {agents.length === 0 ? (
                <div className="px-3 py-2 text-xs text-muted-foreground">
                  Start Codex, Claude or Gemini with “Add”, or open a shell to run any command. Each terminal runs in this design’s workspace.
                </div>
              ) : (
                agents.map((r) => (
                  <Row
                    key={r.pane}
                    r={r}
                    on={r.pane === sel}
                    onClick={() => select(r.pane)}
                    onClose={() => close(r)}
                  />
                ))
              )}
            </div>

            {procs.length > 0 && (
              <Section label={`Terminals & processes (${procs.length})`} defaultOpen={false}>
                {procs.map((r) => (
                  <Row
                    key={r.pane}
                    r={r}
                    on={r.pane === sel}
                    onClick={() => select(r.pane)}
                    onClose={() => close(r)}
                  />
                ))}
              </Section>
            )}
      </div>
          <div className="flex min-h-0 flex-1 flex-col">
            <div className="flex-none border-b px-3 py-2 text-xs text-muted-foreground">{[...agents, ...procs].find((row) => row.pane === sel)?.title || "Select a session"} · Live Butai session</div>
            <div className="min-h-0 flex-1"><AgentTerminal wsId={wsId} pane={sel} pasteRequest={pasteRequest}/></div>
          </div>
    </div>
  );
}

function Row({
  r,
  on,
  onClick,
  onClose,
}: {
  r: PaneRow;
  on: boolean;
  onClick: () => void;
  onClose: () => void;
}) {
  return (
    <div
      className={cn(
        "group flex w-full items-center border-l-2 border-transparent pr-1 hover:bg-accent/50",
        on && "border-primary bg-accent",
      )}
    >
      <button
        className="flex min-w-0 flex-1 items-center gap-2 px-2 py-1 text-left"
        title={`${r.kind} · pane ${r.pane} · ${r.status}`}
        onClick={onClick}
        aria-pressed={on}
      >
        <span
          className="inline-block h-1.5 w-1.5 shrink-0 rounded-full"
          style={{ background: DOT[r.status] }}
        />
        <span className="min-w-0 flex-1 truncate text-xs">{r.title}</span>
        {r.sub && (
          <span className="max-w-[45%] shrink-0 truncate text-[10px] text-muted-foreground">
            {r.sub}
          </span>
        )}
        {r.age && (
          <span className="shrink-0 font-mono text-[10px] text-muted-foreground">
            {r.age}
          </span>
        )}
      </button>
      {/* Space is tight, so this one is icon-only and carries its own title. */}
      <button
        type="button"
        title={
          r.status === "exited"
            ? `Remove ${r.title}`
            : r.kind === "agent"
              ? `Close ${r.title} — ends its session`
              : `Stop ${r.title}`
        }
        onClick={onClose}
        className="shrink-0 rounded p-0.5 text-muted-foreground opacity-0 transition-opacity hover:bg-destructive/15 hover:text-destructive focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring group-hover:opacity-100"
      >
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}

function Section({
  label,
  defaultOpen,
  children,
}: {
  label: string;
  defaultOpen: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger className="flex w-full items-center gap-1.5 border-t px-3 py-1 text-xs font-medium text-muted-foreground hover:bg-accent/50">
        <ChevronRight
          className={cn("h-3.5 w-3.5 transition-transform", open && "rotate-90")}
        />
        {label}
      </CollapsibleTrigger>
      <CollapsibleContent>{children}</CollapsibleContent>
    </Collapsible>
  );
}
