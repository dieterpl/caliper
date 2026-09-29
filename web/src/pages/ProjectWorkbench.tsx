import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { useParams } from "react-router-dom";
import { createPortal } from "react-dom";
import { Box, Layers, Clapperboard, GitBranch, Plus, RefreshCw, Save, Code, Eye, Copy, Check, X, MessageSquare, ChevronDown, ChevronRight } from "lucide-react";
import { toast } from "sonner";
import { app, type ApiError } from "@/lib/api";
import type { Scene } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { Field, inputClass, ParameterFields } from "@/components/project/Fields";
import { asDefinition, keyFor, makeId, type Definition, type Kind, type ProjectState } from "@/components/project/types";
import ProjectPreview from "@/components/project/ProjectPreview";
import InstancesEditor from "@/components/project/InstancesEditor";
import { InterfacesEditor, JointsEditor } from "@/components/project/ConnectionsEditor";
import RepositoryPanel from "@/components/project/RepositoryPanel";
import CreateDefinition from "@/components/project/CreateDefinition";
import SourceEditor from "@/components/project/SourceEditor";
const tabs = [{ kind: "component" as const, label: "Components", icon: Box }, { kind: "assembly" as const, label: "Assemblies", icon: Layers }, { kind: "scene" as const, label: "Scene presets", icon: Clapperboard }];
export interface ModelSelectionRequest { body: string | null; sequence: number }
interface Props {
  mode: "model" | "library" | "files";
  navigatorTarget: HTMLElement | null;
  liveViewport: ReactNode;
  toolbar: ReactNode;
  liveScene?: Scene | null;
  selectionRequest: ModelSelectionRequest | null;
  onStateChanged: (state: ProjectState) => void;
  onSceneActivated: (name: string) => void;
  onSelectedBody: (name: string | null) => void;
  onAskAgent: (text: string) => void;
  refreshSignal: number;
  onDirtyChanged: (dirty: boolean) => void;
}
export default function ProjectWorkbench({ mode, navigatorTarget, liveViewport, toolbar, onSceneActivated, liveScene, selectionRequest, onStateChanged, onSelectedBody, onAskAgent, refreshSignal, onDirtyChanged }: Props) {
  const { slug = "" } = useParams();
  const [listKind, setListKind] = useState<Kind>("component");
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const [rawPart, setRawPart] = useState("");
  const handledSelection = useRef<number>();
  const [project, setProject] = useState(""); const [state, setState] = useState<ProjectState | null>(null); const [kind, setKind] = useState<Kind>("component"); const [selected, setSelected] = useState(""); const [draft, setDraft] = useState<Definition | null>(null); const [preview, setPreview] = useState<string | null>(null); const [previewScene, setPreviewScene] = useState<Scene | null>(null); const [busy, setBusy] = useState(false); const [error, setError] = useState(""); const [view, setView] = useState<"preview" | "source">("preview"); const [repository, setRepository] = useState(false); const [create, setCreate] = useState<Kind | null>(null);
  useEffect(() => { setInspectorOpen(false); }, [selected, rawPart, kind, project, repository]);
  const [liveFocus, setLiveFocus] = useState<string | undefined>();
  const [sourceDirty, setSourceDirty] = useState(false);
  const [previewStale, setPreviewStale] = useState(false);
  const [filter, setFilter] = useState("");
  const request = useRef(0);
  const [building, setBuilding] = useState(false);
  const [buildStatus, setBuildStatus] = useState("queued");
  const [previewLabel, setPreviewLabel] = useState("Live workspace");
  useEffect(() => () => { ++request.current; }, [slug, project]);
  const original = state && selected ? asDefinition(state.manifest[keyFor(kind)]?.[selected] || {}) : null;
  const dirty = !!draft && JSON.stringify(draft) !== JSON.stringify(original);
  const refresh = useCallback(async () => { const next = await app.project(slug, project); setState(next); return next; }, [slug, project]);
  useEffect(() => { if (refreshSignal) void refresh().catch(e => setError(e.message)); }, [refreshSignal, refresh]);
  useEffect(() => { onDirtyChanged(dirty || sourceDirty || busy); }, [dirty, sourceDirty, busy, onDirtyChanged]);
  useEffect(() => { let live = true; setState(null); setSelected(""); setDraft(null); setPreview(null); setBuilding(false); setLiveFocus(undefined); setPreviewStale(false); setSourceDirty(false); setError(""); app.project(slug, project).then(v => { if (live) { setState(v); setPreview(""); } }).catch(e => live && setError(e.message)); return () => { live = false; }; }, [slug, project]);
  const act = async (body: Record<string, unknown>): Promise<boolean> => {
    if (busy) return false; setBusy(true); setBuilding(false); setError(""); ++request.current;
    try { const next = await app.projectAction(slug, { project, ...(state ? { revision: state.revision } : {}), ...body, ...(["save_definition", "save_source"].includes(String(body.action)) ? { build: false } : {}) }); setState(next); if (next.preview) { setPreview(next.preview); setPreviewLabel(selected); } if (body.action === "activate_scene") onSceneActivated?.(String(body.name)); if (["save_definition", "save_source"].includes(String(body.action))) setPreviewStale(true); toast.success(["save_definition", "save_source"].includes(String(body.action)) ? "Changes saved. Rebuild when ready." : "Project updated"); return true; }
    catch (e) { const err = e as ApiError; const data = err.data; setError(err.message + (typeof data === "object" && data?.log ? "\n" + data.log : "")); try { await refresh(); } catch { /* keep visible state */ } return false; }
    finally { setBusy(false); }
  };
  async function lookup(nextKind: Kind, name: string, token: number, rebuild = false) {
    if (rebuild) { setBuilding(true); setBuildStatus("queued"); setError(""); }
    try {
      let next = await app.projectPreview(slug, { project, kind: nextKind, name, build: rebuild, ...(rebuild ? { force: true } : {}) });
      while (token === request.current) {
        setBuildStatus(next.status);
        if (next.status === "ready" || next.status === "stale") {
          setLiveFocus(undefined); setPreview(next.directory ?? null);
          setPreviewStale(next.status === "stale"); break;
        }
        if (next.status === "missing") { setPreview(null); setPreviewStale(false); break; }
        if (next.status === "failed") {
          setError((next.message || "CAD preview failed") + (next.log ? "\n" + next.log : ""));
          if (next.cached_directory) { setPreview(next.cached_directory); setLiveFocus(undefined); setPreviewStale(true); }
          break;
        }
        setBuilding(true);
        if (next.cached_directory) { setPreview(next.cached_directory); setLiveFocus(undefined); setPreviewStale(true); }
        await new Promise(resolve => window.setTimeout(resolve, 650));
        if (token !== request.current) return;
        next = await app.projectPreview(slug, { project, kind: nextKind, name, build: false });
      }
    } catch (e) { if (token === request.current) setError((e as Error).message); }
    finally { if (token === request.current) setBuilding(false); }
  }
  async function select(nextKind: Kind, name: string) {
    if (busy || !state) return false;
    if ((dirty || sourceDirty) && !window.confirm("Discard unsaved changes?")) return false;
    const token = ++request.current;
    const d = asDefinition(state.manifest[keyFor(nextKind)][name]);
    setRawPart(""); setKind(nextKind); setListKind(nextKind); setSelected(name); setView("preview"); setRepository(false);
    setPreviewScene(null); setError(""); setDraft(structuredClone(d)); setSourceDirty(false);
    setBuilding(false); setPreviewStale(false); setPreviewLabel(d.label || name);
    onSelectedBody(nextKind === "component" && !project ? d.legacy_part || (liveScene?.bodies.some(b => b.name === name) ? name : null) : null);
    const focus = nextKind === "component" ? d.legacy_part : undefined;
    const inLiveModel = focus && (liveScene?.bodies.some(b => b.name === focus) || liveScene?.decor?.some(b => b.name === focus));
    if (!project && liveScene && (inLiveModel || nextKind === "scene" && name === (state.manifest.active_scene || state.manifest.default_scene))) {
      setLiveFocus(focus); setPreview(""); setBuildStatus("live"); return true;
    }
    setLiveFocus(undefined); setPreview(null);
    if ((d.instances && !d.instances.length) || (!state.initialized && nextKind === "scene")) return true;
    await lookup(nextKind, name, token);
    return true;
  }
  async function rebuild() {
    if (!selected || busy || dirty || sourceDirty || building) return;
    await lookup(kind, selected, ++request.current, true);
  }

  function openProject(path: string) { if (busy || (dirty || sourceDirty) && !window.confirm("Discard unsaved definition changes?")) return; setProject(path); setRepository(true); }
  const patch = (values: Partial<Definition>) => setDraft(d => d ? { ...d, ...values } : d);
  const bodies = (previewScene || (!project && mode === "model" ? liveScene : null))?.bodies.filter(b => b.group !== "environment").map(b => b.name) || [];
  const title = draft?.label || selected || "Project library";
  useEffect(() => { if (state && !project) onStateChanged(state); }, [state, project, onStateChanged]);
  function clearSelection() {
    if (busy || (dirty || sourceDirty) && !window.confirm("Discard unsaved changes?")) return false;
    ++request.current; setSelected(""); setRawPart(""); setDraft(null); setSourceDirty(false); setView("preview"); setRepository(false); setBuilding(false); setPreviewStale(false); setError(""); onSelectedBody(null); return true;
  }
  useEffect(() => {
    if (!selectionRequest || !state || busy || handledSelection.current === selectionRequest.sequence) return;
    if (project) { setProject(""); return; }
    handledSelection.current = selectionRequest.sequence;
    if (!selectionRequest.body) { clearSelection(); return; }
    const entry = Object.entries(state.manifest.components).find(([id, value]) => id === selectionRequest.body || asDefinition(value).legacy_part === selectionRequest.body);
    if (entry) { void select("component", entry[0]); }
    else if (clearSelection()) { setRawPart(selectionRequest.body); onSelectedBody(selectionRequest.body); }
  }, [selectionRequest, state, project, busy]);
  useEffect(() => {
    if (!dirty && !sourceDirty) return;
    const guard = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", guard);
    return () => window.removeEventListener("beforeunload", guard);
  }, [dirty, sourceDirty]);
  const properties = <>{repository && state ? <RepositoryPanel state={state} busy={busy} act={act} open={openProject}/> : draft && state ? <div className="space-y-5"><div className="flex items-center justify-between"><h2 className="text-xs font-semibold">{kind === "component" ? "Part properties" : "Configuration"}</h2><Button size="xs" variant="ghost" disabled={busy} title="Duplicate definition" onClick={async () => { const label = window.prompt("Name for duplicate", `${title} copy`); if (!label) return; const id = makeId(label); if (state.manifest[keyFor(kind)][id]) { setError("That definition already exists"); return; } if (await act({ action: "save_definition", kind, name: id, definition: { ...structuredClone(draft), label } })) { setSelected(id); setDraft({ ...structuredClone(draft), label }); } }}><Copy/></Button></div><Field label="Name"><input className={inputClass} value={draft.label || selected} onChange={e => patch({ label: e.target.value })}/></Field>{kind === "scene" && <><div className="rounded border bg-background p-3 text-xs leading-5 text-muted-foreground">A scene preset saves an assembly’s dimensions, layout and environment. Inspecting it leaves the live model unchanged. Use it in the workspace to update the model, simulation and exports.</div><Button size="sm" variant="outline" className="w-full" disabled={busy || dirty || !state.initialized} onClick={() => void act({ action: "activate_scene", name: selected })}>{(state.manifest.active_scene || state.manifest.default_scene) === selected ? <Check/> : <Clapperboard/>}{(state.manifest.active_scene || state.manifest.default_scene) === selected ? "Used in live workspace" : "Use in workspace"}</Button>{draft.assembly && <Field label="Assembly"><select className={inputClass} value={draft.assembly} onChange={e => { const a = asDefinition(state.manifest.assemblies[e.target.value]); patch({ assembly: e.target.value, parameters: a.parameters || {}, config: {} }); }}>{Object.entries(state.manifest.assemblies).map(([id,d]) => <option key={id} value={id}>{asDefinition(d).label || id}</option>)}</select></Field>}</>}
    {Object.keys(draft.parameters || (kind === "scene" ? state.manifest.parameters : {}) || {}).length > 0 && <div className="space-y-3"><h3 className="text-xs font-semibold">{kind === "scene" ? "Scene parameters" : "Dimensions / parameters"}</h3><ParameterFields values={{ ...(draft.parameters || (kind === "scene" ? state.manifest.parameters : {}) || {}), ...draft.config }} onChange={values => patch(kind === "scene" ? { config: values } : { parameters: values })}/></div>}
    {kind === "scene" && draft.assembly && asDefinition(state.manifest.assemblies[draft.assembly]).instances && <InstancesEditor layoutOnly state={state} instances={(asDefinition(state.manifest.assemblies[draft.assembly]).instances || []).map(i => ({ ...i, ...draft.overrides?.[i.name] }))} onChange={instances => patch({ overrides: Object.fromEntries(instances.map(i => [i.name, { origin: i.origin, rotation: i.rotation, config: i.config }])) })}/>}{draft.instances !== undefined && <InstancesEditor state={state} instances={draft.instances} onChange={instances => patch({ instances })}/>}{draft.instances !== undefined && <JointsEditor joints={draft.joints || []} bodies={[...bodies, ...Object.keys((previewScene as Scene & { interfaces?: object })?.interfaces || {}).map(n => "@"+n)]} onChange={joints => patch({ joints })}/>}{kind !== "scene" && <details className="rounded border p-3"><summary className="cursor-pointer text-xs text-muted-foreground">Attachment interfaces</summary><div className="mt-3"><InterfacesEditor interfaces={draft.interfaces || {}} bodies={bodies} onChange={interfaces => patch({ interfaces })}/></div></details>}{kind === "scene" && <div className="space-y-3 rounded border p-3"><h3 className="text-xs font-semibold">Environment & simulation</h3><label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={draft.environment?.ground || false} onChange={e => patch({ environment: { ...draft.environment, ground: e.target.checked } })}/>Ground plane</label><ParameterFields values={{ gravity: -2000, ...draft.settings }} onChange={settings => patch({ settings })}/></div>}<details className="border-t pt-3 text-[11px] leading-5 text-muted-foreground"><summary className="cursor-pointer">Ownership & Git</summary><div className="pt-3"><p className="mb-3">Save changes writes files. Rebuild preview updates this 3D view.</p><p>Owner: <b className="text-foreground">{state.name}</b></p><code className="break-all">cad/project.json · {keyFor(kind)}.{selected}</code>{draft.source && <p className="mt-2 break-all">Geometry: {draft.source}</p>}<button className="mt-3 text-primary" onClick={() => setRepository(true)}>View project Git changes →</button></div></details></div> : <p className="text-xs leading-6 text-muted-foreground">Select a definition to edit its dimensions, placement, connections or scene configuration. Open Git to manage included projects and save revisions.</p>}</>;
  const navigation = <div className="flex h-full min-h-0 flex-col bg-card" aria-label="Project library">
    <div className="flex flex-none flex-wrap gap-1 border-b p-2">{tabs.map(({ kind: k, label }) => <Button key={k} size="xs" variant={listKind === k ? "secondary" : "ghost"} onClick={() => setListKind(k)}>{label === "Scene presets" ? "Scenes" : label}</Button>)}</div>
    <div className="flex-none px-3 pt-3"><input aria-label="Find definition" className={inputClass} placeholder="Find a definition…" value={filter} onChange={event => setFilter(event.target.value)}/></div>
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto p-2">
      <div className="flex items-center gap-2 px-2 py-3 text-xs text-muted-foreground"><span>{project ? state?.name || project : "Project definitions"}</span><span className="flex-1"/>{project && <Button size="xs" variant="ghost" disabled={busy} onClick={() => openProject(project.replace(/(?:^|\/)cad\/kits\/[^/]+$/, ""))}>Parent</Button>}<Button size="xs" variant="ghost" disabled={busy || !state} title={`Create ${listKind}`} onClick={() => setCreate(listKind)}><Plus/></Button></div>
      {Object.entries(state?.manifest[keyFor(listKind)] || {}).filter(([id, value]) => `${id} ${asDefinition(value).label || ""}`.toLowerCase().includes(filter.toLowerCase())).map(([id, value]) => { const Icon = tabs.find(tab => tab.kind === listKind)!.icon; return <button key={id} disabled={busy} aria-pressed={selected === id && kind === listKind} className={cn("mb-1 flex w-full items-center gap-2 rounded px-2 py-2 text-left text-xs hover:bg-accent disabled:opacity-60", selected === id && kind === listKind && "bg-secondary text-primary")} onClick={() => void select(listKind, id)}><Icon size={14}/><span className="min-w-0 flex-1 truncate">{asDefinition(value).label || id}</span>{listKind === "scene" && id === (state?.manifest.active_scene || state?.manifest.default_scene) && <Check size={12}/>}</button>; })}
      {state && !Object.keys(state.manifest[keyFor(listKind)]).length && <p className="p-3 text-xs text-muted-foreground">No definitions yet. Use + to create one.</p>}
      {state?.dependencies.length ? <details className="mt-4 border-t px-2 pt-3"><summary className="cursor-pointer text-xs text-muted-foreground">Included projects</summary>{state.dependencies.map(dependency => <button disabled={busy} key={dependency.name} className="mt-2 w-full rounded px-2 py-2 text-left text-xs hover:bg-accent" onClick={() => openProject([project, dependency.path].filter(Boolean).join("/"))}><GitBranch size={12} className="mr-2 inline"/>{dependency.name} ↗</button>)}</details> : null}
    </div>
    <div className="flex flex-none items-center border-t p-2 text-xs text-muted-foreground"><span className="min-w-0 flex-1 truncate px-1">{state?.name || "Loading definitions…"}</span><Button size="xs" variant="ghost" disabled={busy} title="Project repository" onClick={() => setRepository(value => !value)}><GitBranch/></Button><Button size="xs" variant="ghost" disabled={busy} title="Refresh project definitions" onClick={() => void refresh().catch(e => setError(e.message))}><RefreshCw/></Button></div>
  </div>;
  const inspecting = mode !== "files" && (repository || !!selected || !!rawPart);
  const libraryPreview = mode === "library" && !!selected;
  return <div className="flex h-full min-h-0 flex-col" data-workbench-mode={mode}>
    {navigatorTarget && createPortal(navigation, navigatorTarget)}
    <div className="flex flex-none flex-wrap items-center gap-2 border-b bg-background px-3 py-2">
      <h1 className="min-w-0 flex-1 truncate text-xs font-medium">{libraryPreview ? title : "Live model"}{dirty && <span className="ml-2 text-warn">Unsaved changes</span>}</h1>
      {building && <span role="status" className="text-xs text-muted-foreground">{buildStatus === "queued" ? "Preview queued" : "Building preview"} · {previewLabel}</span>}
      {view === "source" && draft?.source && mode !== "files" && <Button size="xs" variant="ghost" onClick={() => { if (sourceDirty && !window.confirm("Discard unsaved source changes?")) return; setSourceDirty(false); setView("preview"); }}><Eye/>Back to 3D</Button>}
      {toolbar}
    </div>
    <div className="relative min-h-0 flex-1">
      <div role="region" aria-label="Live model viewport" className={cn("absolute inset-0", (libraryPreview || view === "source" && mode !== "files") && "invisible pointer-events-none")}>{liveViewport}</div>
      {libraryPreview && view === "preview" && <div className="absolute inset-0">
        {preview !== null ? <ProjectPreview key={`${project}/${preview}`} slug={slug} directory={preview} focus={liveFocus} onScene={setPreviewScene}/> : <div className="flex h-full flex-col items-center justify-center gap-3 px-8 text-center"><Layers size={38} className="text-muted-foreground"/><h2 className="text-sm font-medium">{building ? "Building preview…" : "Preview not built yet"}</h2><p className="max-w-sm text-xs leading-6 text-muted-foreground">{building ? "You can keep browsing while CAD builds." : "Inspect the definition now, or build its 3D preview when ready."}</p></div>}
        {previewStale && !building && preview !== null && <div role="status" className="absolute right-3 top-3 rounded border bg-card/95 px-3 py-2 text-xs text-muted-foreground">Last built preview · rebuild to update</div>}
      </div>}
      {draft?.source && view === "source" && <div className={cn("absolute inset-0 z-20 bg-background", mode === "files" && "hidden")}><SourceEditor key={`${project}/${draft.source}`} slug={slug} project={project} path={draft.source} busy={busy} onDirty={setSourceDirty} onSave={text => act({ action: "save_source", kind, name: selected, path: draft.source, text })}/></div>}
      {inspecting && view !== "source" && <section aria-label="Selection inspector" className="absolute bottom-12 left-3 z-10 flex max-h-[65%] w-80 max-w-[calc(100%-1.5rem)] flex-col overflow-hidden rounded-lg border bg-card/95 shadow-lg backdrop-blur">
        <div className="flex flex-none items-center gap-2 px-3 py-2"><button aria-label={inspectorOpen ? "Collapse properties" : "Expand properties"} aria-expanded={inspectorOpen} className="flex min-w-0 flex-1 items-center gap-2 text-left text-xs font-medium" onClick={() => setInspectorOpen(open => !open)}>{inspectorOpen ? <ChevronDown size={14}/> : <ChevronRight size={14}/>}<span className="truncate">{repository ? "Project repository" : title === "Project library" ? rawPart : title}</span></button><Button size="xs" variant="ghost" disabled={busy} title="Close inspector" onClick={clearSelection}><X/></Button></div>
        <div className={inspectorOpen ? "contents" : "hidden"}>
        <div className="min-h-0 flex-1 overflow-y-auto border-t p-3">{rawPart && !draft ? <p className="text-xs leading-5 text-muted-foreground">This part is in the live model. Its dimensions are defined in the project source.</p> : properties}</div>
        {!repository && <div className="flex flex-none flex-wrap items-center gap-1 border-t p-2">
          <Button size="xs" variant="ghost" onClick={() => onAskAgent(`Inspect ${rawPart || title} in ${project || slug}. ${draft?.source ? `Its source is ${draft.source}. ` : ""}Active scene: ${state?.manifest.active_scene || state?.manifest.default_scene || "current"}. `)}><MessageSquare/>Ask agent</Button>
          {draft?.source && <Button size="xs" variant="ghost" onClick={() => setView("source")}><Code/>Source</Button>}
          {draft && <><Button size="xs" disabled={busy || !dirty} onClick={() => void act({ action: "save_definition", kind, name: selected, definition: draft })}><Save/>Save changes</Button><Button size="xs" variant="outline" disabled={busy || dirty || sourceDirty || building} onClick={() => void rebuild()}><RefreshCw className={building ? "animate-spin" : ""}/>{building ? "Building…" : preview === null ? "Build preview" : "Rebuild preview"}</Button></>}
        </div>}
        </div>
      </section>}
      {error && <div role="alert" className="absolute inset-x-3 top-3 z-30 max-h-40 overflow-auto rounded border border-destructive/40 bg-card p-3"><pre className="whitespace-pre-wrap break-words font-mono text-xs text-destructive">{error}</pre><Button size="xs" variant="ghost" onClick={() => setError("")}><X/>Dismiss</Button></div>}
      {state && !state.initialized && mode === "library" && <div className="absolute inset-x-3 top-3 flex items-center justify-between gap-3 rounded border bg-card p-3 text-xs"><span>Enable definitions to create reusable components, assemblies, and scenes.</span><Button size="xs" disabled={busy} onClick={() => void act({ action: "initialize" })}>Enable project library</Button></div>}
    </div>
    {state && <CreateDefinition kind={create} state={state} busy={busy} onClose={() => setCreate(null)} onCreate={async (body, k, id) => { if (state.manifest[keyFor(k)][id]) { setError("That definition already exists"); return false; } const ok = await act(body); if (ok) { setRawPart(""); setKind(k); setListKind(k); setSelected(id); setView("preview"); setRepository(false); setPreview(null); setLiveFocus(undefined); setPreviewStale(false); setSourceDirty(false); const next = await app.project(slug, project); setState(next); setDraft(structuredClone(asDefinition(next.manifest[keyFor(k)][id]))); } return ok; }}/>}
  </div>;
}
