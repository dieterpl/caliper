import type { ProjectState } from "@/components/project/types";
// The two APIs this app talks to, in one place — a typed port of the old api.js.
//
// `butai` is the daemon's REST surface, relayed by server.py: the file tree,
// diffs, staging, commits, branches, agents and processes all live there.
// `app` is this server's own: workspaces on disk, and typing into a pane.
//
// Everything goes through one `call()` so a 401 (the token cookie expired or
// was never set) always lands the same way — at the login page.

import type {
  AgentUsage,
  BuildResult,
  Changes,
  ExportState,
  History,
  Scene,
  SystemInfo,
  TreeEntry,
  Workspace,
  WorkspaceDetail,
} from "./types";

export interface ApiError extends Error {
  data?: { error?: string; log?: string } | string | null;
  status?: number;
}

export interface ProjectPreviewJob {
  status: "queued" | "building" | "ready" | "failed" | "stale" | "missing";
  directory?: string;
  cached_directory?: string;
  message?: string;
  log?: string;
}

async function call<T = unknown>(url: string, opts?: RequestInit): Promise<T> {
  const r = await fetch(url, opts);
  if (r.status === 401) {
    location.href = "/login";
    throw new Error("not signed in");
  }
  const text = await r.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  const asObj = data as { error?: string } | null;
  if (!r.ok || (asObj && asObj.error)) {
    const err = new Error(
      (asObj && asObj.error) || `${r.status} on ${url}`,
    ) as ApiError;
    // Keep the whole body on the error: a failed build carries the tool's own
    // output in `log`, and that is the only explanation anyone gets.
    err.data = data as ApiError["data"];
    err.status = r.status;
    throw err;
  }
  return data as T;
}

const json = (body: unknown): RequestInit => ({
  headers: { "content-type": "application/json" },
  body: JSON.stringify(body),
});

// ------------------------------------------------------------- the daemon
export const butai = {
  get: <T = unknown>(path: string) => call<T>("/butai/api" + path),
  post: <T = unknown>(path: string, body?: unknown) =>
    call<T>("/butai/api" + path, { method: "POST", ...json(body || {}) }),
  del: <T = unknown>(path: string) =>
    call<T>("/butai/api" + path, { method: "DELETE" }),

  system: () => butai.get<SystemInfo>("/system"),
  workspace: (id: number) => butai.get<WorkspaceDetail>(`/workspaces/${id}`),
  tree: (id: number, path = "") =>
    butai.get<{ entries?: TreeEntry[] }>(
      `/workspaces/${id}/tree?path=${encodeURIComponent(path)}`,
    ),
  file: (id: number, path: string) =>
    butai.get<{ text?: string; truncated?: boolean }>(
      `/workspaces/${id}/file?path=${encodeURIComponent(path)}`,
    ),
  diff: (id: number, path: string, kind = "unstaged") =>
    butai.get<{ patch?: string }>(
      `/workspaces/${id}/diff?path=${encodeURIComponent(path)}&kind=${kind}`,
    ),
  show: (id: number, rev: string) =>
    butai.get<{ patch?: string }>(
      `/workspaces/${id}/show?id=${encodeURIComponent(rev)}`,
    ),
  changes: (id: number) => butai.get<Changes>(`/workspaces/${id}/changes`),
  stage: (id: number, path: string) =>
    butai.post(`/workspaces/${id}/changes/stage`, { path }),
  unstage: (id: number, path: string) =>
    butai.post(`/workspaces/${id}/changes/unstage`, { path }),
  commit: (id: number, message: string) =>
    butai.post(`/workspaces/${id}/changes/commit`, { message }),
  checkout: (id: number, branch: string, create = false) =>
    butai.post(`/workspaces/${id}/checkout`, { branch, create }),
  // The agent types this daemon is configured with, e.g. claude/codex/gemini.
  paneOutput: (id: number, pane: number, signal?: AbortSignal) =>
    call<{ pane: number; lines: string[]; exited: number | null }>(
      `/butai/api/workspaces/${id}/panes/${pane}/output?source=scrollback&format=text&lines=200`,
      { signal },
    ),
  paneScreen: (id: number, pane: number, signal?: AbortSignal) =>
    call<{ pane: number; cols: number; rows: number; lines: string[]; cursor: [number, number] | null }>(
      `/butai/api/workspaces/${id}/panes/${pane}/output?source=screen&format=ansi&lines=500`, { signal },
    ),
  paneHistory: (id: number, pane: number, lines: number, signal?: AbortSignal) =>
    call<{ lines: string[] }>(
      `/butai/api/workspaces/${id}/panes/${pane}/output?source=scrollback&format=ansi&lines=${lines}`, { signal },
    ),
  paneInput: (id: number, pane: number, input: unknown) =>
    call(`/butai/api/workspaces/${id}/panes/${pane}/input`, {
      method: "POST", ...json(input), signal: AbortSignal.timeout(8000),
    }),
  paneKey: (id: number, pane: number, code: "enter" | "esc") =>
    butai.post(`/workspaces/${id}/panes/${pane}/input`, { key: { code } }),
  agentTypes: () => butai.get<string[]>("/agents"),
  agentUsage: () => butai.get<{ clis: AgentUsage[] }>("/usage"),
  spawnAgent: (id: number, type = "claude") =>
    butai.post(`/workspaces/${id}/agents`, { type }),
  // A plain shell is a process pane (a PTY), not an agent type — how you get a
  // terminal to run `claude login` and paste a token.
  startProcess: (id: number, name: string, command: string) =>
    butai.post(`/workspaces/${id}/processes`, { name, command }),
  killPane: (id: number, pane: number) =>
    butai.del(`/workspaces/${id}/processes/${pane}`),
  // Saving a file is an upload of the raw text to a path in the workspace.
  save: (id: number, path: string, text: string) =>
    call(`/butai/api/workspaces/${id}/upload?path=${encodeURIComponent(path)}`, {
      method: "POST",
      headers: { "content-type": "text/plain" },
      body: text,
    }),
};

// --------------------------------------------------------------- this app
export const app = {
  projectPreview: (slug: string, body: { project?: string; kind: "component" | "assembly" | "scene"; name: string; config?: Record<string, unknown>; background?: boolean; retry?: boolean; build?: boolean; force?: boolean }) =>
    call<ProjectPreviewJob>(`/api/workspaces/${encodeURIComponent(slug)}/project-preview`, { method: "POST", ...json(body) }),
  project: (slug: string, project = "") => call<ProjectState>(`/api/workspaces/${encodeURIComponent(slug)}/project?project=${encodeURIComponent(project)}`),
  projectAction: (slug: string, body: Record<string, unknown>) => call<ProjectState>(`/api/workspaces/${encodeURIComponent(slug)}/project`, { method: "POST", ...json(body) }),
  workspaces: () => call<{ workspaces: Workspace[] }>("/api/workspaces"),
  create: (body: { name: string; brief: string; agent: boolean; agentType?: string }) =>
    call<{ slug: string; agent?: boolean; warning?: string }>("/api/workspaces", { method: "POST", ...json(body) }),
  remove: (slug: string) =>
    call(`/api/workspaces/${encodeURIComponent(slug)}`, { method: "DELETE" }),
  prompt: (slug: string, text: string, pane?: number) =>
    call(`/api/workspaces/${encodeURIComponent(slug)}/prompt`, {
      method: "POST",
      ...json(pane == null ? { text } : { text, pane }),
    }),
  // Going back to a commit is ours, not the daemon's: its checkout can only
  // branch from HEAD, which would silently leave you on the current version.
  openVersion: (slug: string, rev: string) =>
    call<{ branch: string }>(
      `/api/workspaces/${encodeURIComponent(slug)}/version`,
      { method: "POST", ...json({ rev }) },
    ),
  // The whole commit timeline (every ref, not just ancestors of HEAD) plus the
  // current HEAD, so the newest version is always there to go forward to.
  history: (slug: string) =>
    call<History>(`/api/workspaces/${encodeURIComponent(slug)}/history`),

  // Export: what this design has been written out as, and building more of it.
  exports: (slug: string) =>
    call<ExportState>(`/api/workspaces/${encodeURIComponent(slug)}/export`),
  build: (slug: string, body: { formats: string[]; parts?: boolean; all?: boolean }) =>
    call<BuildResult>(`/api/workspaces/${encodeURIComponent(slug)}/export`, {
      method: "POST",
      ...json(body),
    }),
  // A URL rather than a fetch: the browser downloads it, so it must be
  // navigable. One path comes down as itself, several as one zip.
  downloadUrl: (slug: string, paths: string[]) =>
    `/api/workspaces/${encodeURIComponent(slug)}/download?` +
    paths.map((p) => `path=${encodeURIComponent(p)}`).join("&"),
};

/** Artifacts belong to a workspace, never to the app. */
export const artifact = (slug: string, name: string) =>
  `/w/${encodeURIComponent(slug)}/out/${name}`;

/** A picture in the working tree, served as bytes — for an <img>, since the
 *  daemon's file endpoint only hands back text. */
export const workspaceFile = (slug: string, path: string) =>
  `/api/workspaces/${encodeURIComponent(slug)}/file?path=${encodeURIComponent(path)}`;

/** Live scenes bypass cache; fingerprinted project previews are immutable. */
export async function fetchScene(slug: string, directory = ""): Promise<{
  scene: Scene;
  builtAt: Date | null;
}> {
  const bump = /^project-previews\/[a-f0-9]{20}$/.test(directory) ? "" : `?t=${Date.now()}`;
  const r = await fetch(artifact(slug, `${directory ? directory + "/" : ""}scene.json${bump}`));
  if (!r.ok) throw new Error("no scene.json yet — has it exported?");
  const stamp = r.headers.get("last-modified");
  return { scene: (await r.json()) as Scene, builtAt: stamp ? new Date(stamp) : null };
}
