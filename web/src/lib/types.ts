// The shapes the two backends return. Kept loose (lots of optionals) because
// both the app server and the butai daemon add fields over time and the UI only
// ever reads a subset.

export interface Workspace {
  slug: string;
  id: number | null;
  branch: string;
  dirty: number;
  thumb?: number | null;
  exported?: boolean;
  bodies?: number | null;
  decor?: number;
  joints?: number;
  commits?: number;
  agents?: number;
  working?: number;
  waiting?: number;
  processes?: number;
  last?: { when?: string } | null;
}

export interface Body {
  name: string;
  type: string;
  group?: string;
  color?: string;
}

export interface Joint {
  a: string;
  b: string;
}

export interface Decor {
  name: string;
  parent: string;
  group?: string;
  color?: string;
}

export interface Scene {
  bodies: Body[];
  joints?: Joint[];
  decor?: Decor[];
}

export interface ExportFile {
  path: string;
  bytes: number;
}

export interface ExportRow {
  id: string;
  label: string;
  what: string;
  ext?: string;
  files: ExportFile[];
  parts: ExportFile[];
  bytes: number;
  mtime: number;
  stale: boolean;
}

export interface ExportState {
  design: string;
  formats: ExportRow[];
  joints: number;
}

export interface BuildResult {
  formats?: ExportRow[];
  seconds?: number;
  log?: string;
}

export type AgentStatus =
  | "working"
  | "waiting"
  | "finished"
  | "idle"
  | "exited";

export interface AgentUsage {
  name: string;
  command: string;
  state: "metered" | "counted" | "unknown" | "no_account" | "absent";
  version?: string | null;
}

export interface DaemonAgent {
  pane: number;
  title?: string;
  state?: string;
  exited?: number | null;
}

export interface DaemonProcess {
  pane: number;
  name?: string;
  command?: string;
  status?: string;
  exited?: number | null;
}

export interface WorkspaceDetail {
  agents?: DaemonAgent[];
  processes?: DaemonProcess[];
}

export interface FileChange {
  path: string;
  code?: string;
  added?: number;
  deleted?: number;
}

export interface Commit {
  id: string;
  summary?: string;
  message?: string;
}

export interface Changes {
  staged?: (FileChange | string)[];
  unstaged?: (FileChange | string)[];
  recent_commits?: Commit[];
}

// The full commit timeline from the app server (every ref, not HEAD-relative),
// plus which commit is currently checked out.
export interface HistoryCommit {
  id: string;
  summary?: string;
  when?: string;
}

export interface History {
  commits: HistoryCommit[];
  head: string;
}

export interface TreeEntry {
  name: string;
  path: string;
  is_dir: boolean;
  changed?: boolean;
}

export interface SystemInfo {
  cpu_pct?: number;
  ram_used_gb?: number;
  ram_total_gb?: number;
  // A list of what is running on the host, not a count — `containers ${...}`
  // on the array is what put "[object Object],[object Object]" across two lines
  // of the Hub footer. Older daemons sent a plain number, so read both.
  containers?: number | { name?: string; state?: string }[];
}

// A row in either rail's unified list.
export interface PaneRow {
  pane: number;
  kind: "agent" | "proc";
  title: string;
  sub: string;
  status: AgentStatus;
  age: string;
}
