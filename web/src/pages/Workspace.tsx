import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import type { PanelImperativeHandle } from "react-resizable-panels";
import { GitBranch, Pause, Play, RotateCcw, RefreshCw, PanelLeft, TerminalSquare } from "lucide-react";
import { toast } from "sonner";
import { app } from "@/lib/api";
import type { Workspace as Ws } from "@/lib/types";
import { useViewer } from "@/hooks/useViewer";
import { Button } from "@/components/ui/button";
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "@/components/ui/resizable";
import { Logo } from "@/components/Logo";
import Viewport from "@/components/Viewport";
import ModelPanel from "@/components/ModelPanel";
import FilesRail, { type DocTarget } from "@/components/FilesRail";
import Dock from "@/components/Dock";
import AgentsRail from "@/components/AgentsRail";
import ExportDialog from "@/components/ExportDialog";
import ProjectWorkbench, { type ModelSelectionRequest } from "./ProjectWorkbench";
import { asDefinition, type ProjectState } from "@/components/project/types";
import { cn, HUB_TITLE } from "@/lib/utils";

type Mode = "model" | "library" | "files";
function useCompact(query: string) {
  const [compact, setCompact] = useState(() => window.matchMedia(query).matches);
  useEffect(() => { const media = window.matchMedia(query); const change = () => setCompact(media.matches); change(); media.addEventListener("change", change); return () => media.removeEventListener("change", change); }, [query]);
  return compact;
}
export default function Workspace() {
  const { slug = "" } = useParams();
  const navigate = useNavigate(); const location = useLocation();
  const mode: Mode = location.pathname.endsWith("/project") ? "library" : location.pathname.endsWith("/files") ? "files" : "model";
  const [rows, setRows] = useState<Ws[]>([]); const [error, setError] = useState("");
  const row = rows.find(workspace => workspace.slug === slug);
  const [branch, setBranch] = useState("—"); const [project, setProject] = useState<ProjectState | null>(null);
  const [pendingScene, setPendingScene] = useState(""); const [refreshSignal, setRefreshSignal] = useState(0);
  const [definitionDirty, setDefinitionDirty] = useState(false); const [docDirty, setDocDirty] = useState(false);
  const [docTarget, setDocTarget] = useState<DocTarget | null>(null); const [docOpen, setDocOpen] = useState(false);
  const [leftOpen, setLeftOpen] = useState(true); const [rightOpen, setRightOpen] = useState(true);
  const [leftMobile, setLeftMobile] = useState(false); const [rightMobile, setRightMobile] = useState(false);
  const [navigatorTarget, setNavigatorTarget] = useState<HTMLDivElement | null>(null);
  const [selectionRequest, setSelectionRequest] = useState<ModelSelectionRequest | null>(null);
  const [selectedBody, setSelectedBody] = useState<string | null>(null);
  const [promptRequest, setPromptRequest] = useState<{ text: string; sequence: number } | null>(null);
  const sequence = useRef(0); const leftRef = useRef<PanelImperativeHandle>(null); const rightRef = useRef<PanelImperativeHandle>(null);
  const smallProject = useCompact("(max-width: 600px)"); const smallAgents = useCompact("(max-width: 850px)");
  const chooseBody = useCallback((body: string | null) => { setSelectionRequest({ body, sequence: ++sequence.current }); setLeftMobile(false); }, []);
  const v = useViewer(slug, "", undefined, chooseBody);
  const onSelectedBody = useCallback((body: string | null) => { setSelectedBody(body); v.highlight(body); }, [v.highlight]);
  const onProjectChanged = useCallback((next: ProjectState) => { setProject(next); }, []);
  const activeScene = project?.manifest.active_scene || project?.manifest.default_scene || "";
  const sceneLabel = activeScene && project ? asDefinition(project.manifest.scenes[activeScene]).label || activeScene : slug;

  useEffect(() => {
    let live = true;
    app.workspaces().then(({ workspaces }) => { if (!live) return; setRows(workspaces); const found = workspaces.find(workspace => workspace.slug === slug); if (found) { setBranch(found.branch || "—"); setError(""); } else setError(`No design called "${slug}"`); }).catch(e => live && setError("Could not read designs: " + e.message));
    return () => { live = false; };
  }, [slug, refreshSignal]);
  useEffect(() => { document.title = `caliper — ${slug}`; return () => { document.title = HUB_TITLE; }; }, [slug]);
  useEffect(() => { if (smallProject) leftRef.current?.collapse(); else leftRef.current?.expand(); }, [smallProject]);
  useEffect(() => { if (smallAgents) rightRef.current?.collapse(); else rightRef.current?.expand(); }, [smallAgents]);
  useEffect(() => { setLeftMobile(false); setRightMobile(false); if (mode !== "model" && v.running) v.play(); }, [mode]);

  function toggleLeft() { if (smallProject) { setLeftMobile(value => !value); setRightMobile(false); } else if (leftOpen) leftRef.current?.collapse(); else leftRef.current?.expand(); }
  function toggleRight() { if (smallAgents) { setRightMobile(value => !value); setLeftMobile(false); } else if (rightOpen) rightRef.current?.collapse(); else rightRef.current?.expand(); }
  function chooseMode(next: Mode) { navigate(`/ws/${encodeURIComponent(slug)}${next === "library" ? "/project" : next === "files" ? "/files" : ""}`); }
  function openDoc(target: DocTarget) { if (docDirty && JSON.stringify(target) !== JSON.stringify(docTarget) && !window.confirm("Discard unsaved file changes?")) return; setDocTarget(target); setDocOpen(true); setLeftMobile(false); }
  const onSceneActivated = useCallback(() => { v.reload(); setRefreshSignal(value => value + 1); }, [v.reload]);
  async function useScene(name: string) {
    if (!project || pendingScene || activeScene === name) return;
    setPendingScene(name);
    try { const next = await app.projectAction(slug, { action: "activate_scene", name, revision: project.revision }); setProject(next); v.reload(); setSelectionRequest({ body: null, sequence: ++sequence.current }); setRefreshSignal(value => value + 1); }
    catch (e) { toast.error("Scene could not be built: " + (e as Error).message); }
    finally { setPendingScene(""); }
  }
  const toolbar = <>
    {project?.initialized && activeScene && <label className="flex items-center gap-1.5 text-xs text-muted-foreground" htmlFor="live-scene">Scene<select id="live-scene" aria-label="Live scene" className="max-w-36 rounded border bg-card px-2 py-1 text-foreground" value={activeScene} disabled={!!pendingScene || definitionDirty} title={definitionDirty ? "Save your changes before switching scenes" : "Scene used by the live model, simulation, and exports"} onChange={event => void useScene(event.target.value)}>{Object.entries(project.manifest.scenes).map(([id, definition]) => <option key={id} value={id}>{asDefinition(definition).label || id}</option>)}</select>{pendingScene && <RefreshCw size={12} className="animate-spin"/>}</label>}
    {mode === "model" && v.hasJoints && <><Button size="xs" variant="ghost" onClick={v.play}>{v.running ? <Pause/> : <Play/>}{v.running ? "Pause" : "Simulate"}</Button><Button size="xs" variant="ghost" onClick={v.reset} title="Reset simulation"><RotateCcw/></Button></>}
  </>;
  return <div className="flex h-full min-h-0 flex-col" data-workspace-layout="simple">
    <header className="flex min-h-14 flex-none items-center gap-2 border-b bg-card px-3 py-2">
      <button onClick={() => { if ((definitionDirty || docDirty) && !window.confirm("Discard unsaved changes and leave this project?")) return; navigate("/"); }} title="All designs" className="flex items-center gap-2 rounded px-1.5 py-1 hover:bg-accent"><Logo/><span className="hidden font-semibold tracking-tight sm:inline">caliper</span></button>
      <span className="hidden text-muted-foreground sm:inline">/</span>
      <select aria-label="Project" className="min-w-0 max-w-44 truncate rounded bg-transparent px-1 py-1 text-xs font-medium sm:max-w-64" value={slug} onChange={event => { if ((definitionDirty || docDirty) && !window.confirm("Discard unsaved changes and switch projects?")) return; navigate(`/ws/${encodeURIComponent(event.target.value)}`); }}>{!row && <option value={slug}>{slug}</option>}{rows.map(workspace => <option key={workspace.slug} value={workspace.slug}>{workspace.slug}</option>)}</select>
      <span className="hidden items-center gap-1 text-xs text-muted-foreground md:flex"><GitBranch size={12}/>{branch}</span><span className="flex-1"/>
      <Button size="xs" variant={(smallProject ? leftMobile : leftOpen) ? "secondary" : "ghost"} aria-expanded={smallProject ? leftMobile : leftOpen} onClick={toggleLeft} title="Toggle project panel"><PanelLeft/><span className="hidden sm:inline">Project panel</span></Button>
      <Button size="xs" variant={(smallAgents ? rightMobile : rightOpen) ? "secondary" : "ghost"} aria-expanded={smallAgents ? rightMobile : rightOpen} onClick={toggleRight}><TerminalSquare/>Agents</Button><ExportDialog slug={slug}/>
    </header>
    {error && <p role="alert" className="border-b p-2 text-xs text-destructive">{error}</p>}
    <div className={cn("relative min-h-0 flex-1", smallProject && "compact-project", smallAgents && "compact-agents", leftMobile && "project-overlay-open", rightMobile && "agents-overlay-open")}>
      {(leftMobile && smallProject || rightMobile && smallAgents) && <button className="absolute inset-0 z-30 bg-background/60" aria-label="Close open panel" onClick={() => { setLeftMobile(false); setRightMobile(false); }}/>}
      <ResizablePanelGroup orientation="horizontal">
        <ResizablePanel id="project-panel" panelRef={leftRef} collapsible collapsedSize={0} defaultSize="18%" minSize="15%" maxSize="32%" onResize={size => setLeftOpen(size.asPercentage > 0)} className="workspace-project-panel min-w-0">
          <aside className="flex h-full min-h-0 flex-col border-r bg-card" aria-label="Project panel">
            <nav aria-label="Project tools" className="flex flex-none gap-1 border-b px-2 py-2">{([["model", "Model"], ["library", "Library"], ["files", "Files & Git"]] as const).map(([key, label]) => <Button key={key} size="xs" variant={mode === key ? "secondary" : "ghost"} aria-current={mode === key ? "page" : undefined} onClick={() => chooseMode(key)}>{label}</Button>)}</nav>
            <div className={cn("min-h-0 flex-1", mode !== "model" && "hidden")}><ModelPanel scene={v.scene} name={sceneLabel} selected={selectedBody} onSelect={chooseBody} setVisible={v.setVisible}/></div>
            <div ref={setNavigatorTarget} className={cn("min-h-0 flex-1", mode !== "library" && "hidden")}/>
            <div className={cn("min-h-0 flex-1", mode !== "files" && "hidden")}>{row?.id != null ? <FilesRail wsId={row.id} slug={slug} sel={docTarget && "path" in docTarget ? docTarget.path : null} refreshSignal={refreshSignal} onOpen={openDoc} onCheckout={next => { setBranch(next); setRefreshSignal(value => value + 1); v.reload(); }}/> : <RailPending text="Connecting files and Git…"/>}</div>
          </aside>
        </ResizablePanel>
        <ResizableHandle className="workspace-project-handle"/>
        <ResizablePanel id="design-view" defaultSize="56%" minSize="30%" className="min-w-0">
          <div className="relative h-full min-h-0">
            <ProjectWorkbench refreshSignal={refreshSignal} onDirtyChanged={setDefinitionDirty} mode={mode} navigatorTarget={navigatorTarget} selectionRequest={selectionRequest} liveScene={v.scene} onStateChanged={onProjectChanged} onSceneActivated={onSceneActivated} onSelectedBody={onSelectedBody} onAskAgent={text => { setPromptRequest({ text, sequence: ++sequence.current }); if (smallAgents) setRightMobile(true); else rightRef.current?.expand(); }} toolbar={toolbar} liveViewport={<Viewport v={v} hideParts/>}/>
            {row?.id != null && <div className={cn("absolute inset-0 z-20 bg-background", !(mode === "files" && docOpen) && "hidden")}><Dock wsId={row.id} slug={slug} target={docTarget} onDirty={setDocDirty} active={mode === "files" && docOpen} onClose={() => setDocOpen(false)} onSaved={path => { setRefreshSignal(value => value + 1); if (path.startsWith("cad/")) toast("Saved — rebuilding CAD in the background"); }}/></div>}
          </div>
        </ResizablePanel>
        <ResizableHandle className="workspace-agent-handle"/>
        <ResizablePanel id="agent-panel" panelRef={rightRef} collapsible collapsedSize={0} defaultSize="26%" minSize="20%" maxSize="45%" onResize={size => setRightOpen(size.asPercentage > 0)} className="workspace-agent-panel min-w-0">
          {row?.id != null ? <AgentsRail wsId={row.id} slug={slug} promptRequest={promptRequest}/> : <RailPending text="Agent sessions are unavailable. Check the container service."/>}
        </ResizablePanel>
      </ResizablePanelGroup>
    </div>
  </div>;
}
function RailPending({ text }: { text: string }) { return <div className="flex h-full flex-col items-center justify-center gap-3 bg-card p-5 text-center"><Logo size={28} mono className="opacity-20"/><p className="text-xs leading-5 text-muted-foreground">{text}</p></div>; }
