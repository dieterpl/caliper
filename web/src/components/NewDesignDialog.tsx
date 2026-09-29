import { useEffect, useState } from "react";
import { toast } from "sonner";
import { useAgentProviders } from "@/hooks/useAgentProviders";
import { Plus } from "lucide-react";
import { app } from "@/lib/api";
import { slugify } from "@/lib/format";
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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

export default function NewDesignDialog({
  onCreated,
}: {
  onCreated: (slug: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [brief, setBrief] = useState("");
  const [agent, setAgent] = useState(true);
  const [agentType, setAgentType] = useState("codex");
  const { providers, loading, error: providersError, refresh } = useAgentProviders(open);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const slug = slugify(name);

  useEffect(() => {
    if (!loading && providers.length && !providers.some((provider) => provider.name === agentType && provider.available)) {
      const first = providers.find((provider) => provider.available);
      if (first) setAgentType(first.name);
    }
  }, [providers, loading, agentType]);

  function reset() {
    setName("");
    setBrief("");
    setAgent(true);
    setError("");
  }

  async function create() {
    if (!slug) {
      setError("Give it a name — letters, digits and dashes.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const made = await app.create({ name: slug, brief: brief.trim(), agent, agentType });
      if (made.warning) toast.warning(made.warning);
      setOpen(false);
      reset();
      onCreated(made.slug);
    } catch (e) {
      setError("could not create it: " + (e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        setOpen(v);
        if (v) reset();
      }}
    >
      <DialogTrigger asChild>
        <Button>
          <Plus /> New design
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New design</DialogTitle>
          <DialogDescription>Your CAD files, component library and Git history in one workspace.</DialogDescription>
        </DialogHeader>

        <div className="grid gap-4 py-1">
          <div className="grid gap-1.5">
            <Label htmlFor="new-name">Name</Label>
            <Input
              id="new-name"
              autoComplete="off"
              placeholder="fan-bracket"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
            <p className="font-mono text-xs text-muted-foreground">
              /workspaces/{slug || "…"}
            </p>
          </div>

          <div className="grid gap-1.5">
            <Label htmlFor="new-brief">What should it be?</Label>
            <Textarea
              id="new-brief"
              className="min-h-[84px]"
              placeholder="A wall bracket for a 60 mm fan: M4 bolts into the wall, 3 mm walls, printable without supports."
              value={brief}
              onChange={(e) => setBrief(e.target.value)}
            />
            <p className="text-xs text-muted-foreground">
              Saved in the workspace instructions for Claude, Codex and Gemini.
              After signing in, ask your agent to build the design from this brief.
            </p>
          </div>

          <label className="flex cursor-pointer items-center gap-2 text-sm">
            <Checkbox
              checked={agent}
              onCheckedChange={(v) => setAgent(v === true)}
            />
            Start an agent when the workspace opens
          </label>

          {agent && <div className="grid gap-1.5">
            <Label htmlFor="new-agent">Agent CLI</Label>
            <select id="new-agent" value={agentType} onChange={(event) => setAgentType(event.target.value)}
              className="h-9 rounded-md border bg-background px-3 text-sm" disabled={loading || busy}>
              {providers.length === 0 && <option value="codex">{loading ? "Checking providers…" : "No providers available"}</option>}
              {providers.map((provider) => <option key={provider.name} value={provider.name} disabled={!provider.available}>
                {provider.label} — {provider.status}
              </option>)}
            </select>
            <p className="text-xs text-muted-foreground">The live terminal keeps login prompts and CLI permissions under your control. You can add more agents and commands later.</p>
            {providersError && <p className="text-xs text-destructive">{providersError} <button type="button" className="underline" onClick={refresh}>Retry</button></p>}
          </div>}

          {error && <p className="text-sm text-destructive">{error}</p>}
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={() => setOpen(false)} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={create} disabled={busy || !slug || (agent && (loading || !providers.some((provider) => provider.name === agentType && provider.available)))}>
            {busy ? "Creating…" : "Create design"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
