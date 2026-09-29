import { useCallback, useEffect, useState } from "react";
import { butai } from "@/lib/api";

export interface AgentProvider {
  name: string;
  label: string;
  configured: boolean;
  available: boolean;
  status: string;
}

const labels: Record<string, string> = {
  codex: "Codex", claude: "Claude Code", gemini: "Gemini CLI",
  aider: "Aider", agy: "Antigravity",
};

export function useAgentProviders(enabled = true) {
  const [providers, setProviders] = useState<AgentProvider[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    const [types, usage] = await Promise.allSettled([butai.agentTypes(), butai.agentUsage()]);
    if (types.status === "rejected" || !Array.isArray(types.value)) {
      setError("Could not reach the agent registry. Retry or open a shell.");
      setProviders([]);
    } else {
      const installed = usage.status === "fulfilled" && Array.isArray(usage.value?.clis)
        ? new Map(usage.value.clis.map((row) => [row.name, row])) : null;
      setProviders([...new Set(["codex", "claude", "gemini", ...types.value])].map((name) => {
        const configured = types.value.includes(name);
        const row = installed?.get(name);
        const available = configured && row?.state !== "absent";
        return { name, label: labels[name] || name, configured, available,
          status: !configured ? "Not configured" : row?.state === "absent" ? "Not installed"
            : row ? name === "codex" ? "ChatGPT account · sign in to Codex" : "Installed · sign in in terminal" : "Availability unchecked" };
      }));
    }
    setLoading(false);
  }, []);
  useEffect(() => { if (enabled) void refresh(); }, [enabled, refresh]);
  return { providers, loading, error, refresh };
}
