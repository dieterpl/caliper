import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { Box, Braces, Check, ChevronRight, Copy, Cuboid, Eye, FolderGit2, GitBranch, Layers, Plus, RotateCcw, Save, Scan, Trash2, Files, MessageSquare, TerminalSquare } from "lucide-react";
import { toast } from "sonner";
import { Logo } from "@/components/Logo";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import PrototypeSessions from "@/components/PrototypeSessions";
import { cn } from "@/lib/utils";

type Mode = "components" | "assemblies" | "scenes";
type Values = Record<string, number | boolean>;
type Vec = [number, number, number];
interface Part { id: string; name: string; shape: string; owner: string; params: Values; color: number }
interface Instance { id: string; ref: string; kind: "component" | "assembly"; origin: Vec; rotation: Vec }
interface Assembly { id: string; name: string; instances: Instance[] }
interface Scene { id: string; name: string; assembly: string; config: Values }
interface Draft { parts: Part[]; assemblies: Assembly[]; scenes: Scene[]; active: string; sources: Record<string, string> }
const KEY = "caliper.integrated-prototype.v2";
const seed: Draft = {
  parts: [
    { id: "motor", name: "MN5008 motor", shape: "motor", owner: "leg-kit", params: { diameter: 55.6, length: 27, shaft: 6 }, color: 0x435368 },
    { id: "hip", name: "Hip link", shape: "link", owner: "leg-kit", params: { length: 110, radius: 12 }, color: 0x94a3b8 },
    { id: "shank", name: "Shank link", shape: "link", owner: "leg-kit", params: { length: 110, radius: 9 }, color: 0x71839c },
    { id: "foot", name: "Foot pad", shape: "sphere", owner: "leg-kit", params: { radius: 15 }, color: 0x273344 },
    { id: "chassis", name: "Chassis", shape: "box", owner: "odrive-quad", params: { length: 220, width: 130, height: 36 }, color: 0x38577e },
    { id: "controller", name: "ODrive S1", shape: "board", owner: "odrive-quad", params: { length: 70, width: 70, height: 16 }, color: 0x3c9d80 },
  ],
  assemblies: [
    { id: "leg", name: "Leg", instances: [
      { id: "hip_link", ref: "hip", kind: "component", origin: [0, 0, 0], rotation: [0, 0, 0] },
      { id: "shank_link", ref: "shank", kind: "component", origin: [0, 0, -110], rotation: [0, 0, 0] },
      { id: "hip_motor", ref: "motor", kind: "component", origin: [0, 35, 0], rotation: [90, 0, 0] },
      { id: "knee_motor", ref: "motor", kind: "component", origin: [0, 35, -110], rotation: [90, 0, 0] },
      { id: "foot", ref: "foot", kind: "component", origin: [0, 0, -220], rotation: [0, 0, 0] },
    ] },
    { id: "quad", name: "Quad", instances: [
      { id: "chassis", ref: "chassis", kind: "component", origin: [0, 0, 253], rotation: [0, 0, 0] },
      { id: "front_left", ref: "leg", kind: "assembly", origin: [80, 65, 235], rotation: [0, 0, 0] },
      { id: "front_right", ref: "leg", kind: "assembly", origin: [80, -65, 235], rotation: [0, 0, 180] },
      { id: "back_left", ref: "leg", kind: "assembly", origin: [-80, 65, 235], rotation: [0, 0, 0] },
      { id: "back_right", ref: "leg", kind: "assembly", origin: [-80, -65, 235], rotation: [0, 0, 180] },
      { id: "controller", ref: "controller", kind: "component", origin: [0, 0, 279], rotation: [0, 0, 0] },
    ] },
  ],
  scenes: [
    { id: "standing", name: "Standing", assembly: "quad", config: { hipSpan: 130, legLength: 110, motors: true } },
    { id: "wide", name: "Wide stance", assembly: "quad", config: { hipSpan: 180, legLength: 110, motors: true } },
    { id: "bench", name: "Leg bench test", assembly: "leg", config: { legLength: 110, motors: true } },
  ],
  active: "standing", sources: {},
};
const labels: Record<string, string> = { diameter: "Can diameter", shaft: "Shaft diameter", hipSpan: "Hip span", legLength: "Leg length", motors: "Show motors" };
const navigatorClipboard = (value: string) => window.navigator.clipboard.writeText(value);
const field = "h-8 w-full rounded-md border bg-background px-2 text-sm focus:outline-none focus:ring-1 focus:ring-ring";
function initial(): Draft { try { return JSON.parse(localStorage.getItem(KEY) || "null") || structuredClone(seed); } catch { return structuredClone(seed); } }

function Fields({ values, onChange }: { values: Values; onChange: (values: Values) => void }) {
  return <div className="space-y-3">{Object.entries(values).map(([key, value]) => <label key={key} className="flex items-center justify-between gap-4 text-xs text-muted-foreground">
    <span>{labels[key] || key[0].toUpperCase() + key.slice(1)}</span>
    {typeof value === "boolean" ? <input aria-label={labels[key] || key[0].toUpperCase() + key.slice(1)} type="checkbox" checked={value} onChange={e => onChange({ ...values, [key]: e.target.checked })} className="accent-primary" /> : <div className="flex w-28 items-center gap-2"><Input aria-label={labels[key] || key[0].toUpperCase() + key.slice(1)} type="number" min="1" step="1" value={value} onChange={e => { if (Number(e.target.value) > 0) onChange({ ...values, [key]: Number(e.target.value) }); }} className="h-8 text-right font-mono" /><span>mm</span></div>}
  </label>)}</div>;
}

function Triple({ label, value, onChange }: { label: string; value: Vec; onChange: (v: Vec) => void }) {
  return <div className="space-y-2"><div className="text-xs text-muted-foreground">{label}</div><div className="grid grid-cols-3 gap-2">{value.map((v, index) => <label key={index} className="flex items-center gap-1 text-xs text-muted-foreground"><span>{["X", "Y", "Z"][index]}</span><Input aria-label={`${label} ${["X", "Y", "Z"][index]}`} type="number" value={v} className="h-8 px-1 text-right font-mono" onChange={e => { const next = [...value] as Vec; next[index] = Number(e.target.value); onChange(next); }} /></label>)}</div></div>;
}

function shape(part: Part, config: Values): THREE.Group {
  const group = new THREE.Group();
  const p = part.params;
  const material = new THREE.MeshStandardMaterial({ color: part.color, metalness: 0.28, roughness: 0.55 });
  const mesh = (geometry: THREE.BufferGeometry, position: Vec = [0, 0, 0], cylinder = false) => {
    const m = new THREE.Mesh(geometry, material); m.position.set(...position); if (cylinder) m.rotation.x = Math.PI / 2; group.add(m); return m;
  };
  const n = (key: string, fallback = 10) => Number(p[key] ?? fallback);
  if (part.shape === "motor") {
    mesh(new THREE.CylinderGeometry(n("diameter") / 2, n("diameter") / 2, n("length"), 48), [0, 0, 0], true);
    mesh(new THREE.CylinderGeometry(n("diameter") / 2 - 3, n("diameter") / 2 - 3, 3, 48), [0, 0, n("length") / 2], true);
    mesh(new THREE.CylinderGeometry(n("shaft") / 2, n("shaft") / 2, 10, 24), [0, 0, n("length") / 2 + 5], true);
    for (let i = 0; i < 12; i++) { const a = i * Math.PI / 6; const rib = mesh(new THREE.BoxGeometry(2, 4, n("length") - 7), [Math.cos(a) * (n("diameter") / 2), Math.sin(a) * (n("diameter") / 2), 0]); rib.rotation.z = a; }
  } else if (part.shape === "link" || part.shape === "cylinder") {
    const length = part.shape === "link" ? Number(config.legLength ?? p.length) : n("height");
    mesh(new THREE.CylinderGeometry(n("radius"), n("radius"), length, 32), [0, 0, part.shape === "link" ? -length / 2 : 0], true);
    if (part.shape === "link") mesh(new THREE.CylinderGeometry(n("radius") * 1.5, n("radius") * 1.5, 18, 32), [0, 0, 0]);
  } else if (part.shape === "sphere") mesh(new THREE.SphereGeometry(n("radius"), 32, 24));
  else {
    const width = part.id === "chassis" ? Number(config.hipSpan ?? p.width) : n("width");
    mesh(new THREE.BoxGeometry(n("length"), width, n("height")));
    if (part.shape === "board") { const top = mesh(new THREE.BoxGeometry(n("length") - 18, n("width") - 18, 4), [0, 0, n("height") / 2 + 2]); top.material = new THREE.MeshStandardMaterial({ color: 0x253841 }); }
  }
  return group;
}

function Preview({ draft, mode, selected, config, instance, onPick }: { draft: Draft; mode: Mode; selected: string; config: Values; instance: string; onPick: (id: string) => void }) {
  const host = useRef<HTMLDivElement>(null);
  const pick = useRef(onPick); pick.current = onPick;
  const [error, setError] = useState("");
  useEffect(() => {
    const el = host.current; if (!el) return;
    let renderer: THREE.WebGLRenderer;
    try { renderer = new THREE.WebGLRenderer({ antialias: true }); } catch { setError("3D preview needs WebGL. The forms and source view remain available."); return; }
    setError("");
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2)); el.appendChild(renderer.domElement);
    const stage = new THREE.Scene(); stage.background = new THREE.Color(0x0b0f17);
    const camera = new THREE.PerspectiveCamera(40, 1, 0.1, 15000); camera.up.set(0, 0, 1);
    const controls = new OrbitControls(camera, renderer.domElement); controls.enableDamping = true;
    stage.add(new THREE.HemisphereLight(0xc9dcff, 0x273347, 2));
    const light = new THREE.DirectionalLight(0xffffff, 3); light.position.set(250, -350, 550); stage.add(light);
    const grid = new THREE.GridHelper(1600, 32, 0x2a3a57, 0x172337); grid.rotation.x = Math.PI / 2; grid.position.z = -0.5; stage.add(grid);
    const root = new THREE.Group(); stage.add(root);
    function add(ref: string, kind: "component" | "assembly", parent: THREE.Group, path = "", depth = 0) {
      if (depth > 8) return;
      if (kind === "component") {
        const part = draft.parts.find(p => p.id === ref); if (!part || (config.motors === false && part.shape === "motor")) return;
        const piece = shape(part, mode === "components" ? {} : config);
        piece.traverse(o => { o.userData.instance = path.split("/")[0]; }); parent.add(piece); return;
      }
      const assembly = draft.assemblies.find(a => a.id === ref); if (!assembly) return;
      for (const node of assembly.instances) {
        const group = new THREE.Group(); const origin = [...node.origin] as Vec;
        if (ref === "quad" && mode === "scenes") { if (node.kind === "assembly") { origin[1] = Math.sign(origin[1]) * Number(config.hipSpan ?? 130) / 2; origin[2] = Number(config.legLength ?? 110) * 2 + 15; } else if (node.ref === "chassis") origin[2] = Number(config.legLength ?? 110) * 2 + 33; else if (node.ref === "controller") origin[2] = Number(config.legLength ?? 110) * 2 + 59; }
        if (ref === "leg" && origin[2] < 0) origin[2] *= Number(config.legLength ?? 110) / 110;
        group.position.set(...origin); group.rotation.set(...node.rotation.map(v => v * Math.PI / 180) as Vec);
        parent.add(group); add(node.ref, node.kind, group, path ? `${path}/${node.id}` : node.id, depth + 1);
        if (depth === 0 && node.id === instance) { const outline = new THREE.BoxHelper(group, 0x60a5fa); parent.add(outline); }
      }
    }
    const scene = draft.scenes.find(s => s.id === selected);
    add(mode === "scenes" ? scene?.assembly || "quad" : selected, mode === "components" ? "component" : "assembly", root);
    const bounds = new THREE.Box3().setFromObject(root); if (bounds.isEmpty()) bounds.setFromCenterAndSize(new THREE.Vector3(), new THREE.Vector3(80, 80, 80));
    const center = bounds.getCenter(new THREE.Vector3()); const size = bounds.getSize(new THREE.Vector3());
    grid.position.z = bounds.min.z - 2;
    const reach = Math.max(size.x, size.y, size.z) * (mode === "components" ? 1.45 : 1.8) + (mode === "components" ? 35 : 80);
    controls.target.copy(center); camera.position.set(center.x + reach * 0.9, center.y - reach, center.z + reach * 0.65); controls.update();
    const resize = () => { const width = el.clientWidth || 1, height = el.clientHeight || 1; renderer.setSize(width, height); camera.aspect = width / height; camera.updateProjectionMatrix(); };
    resize();
    const ray = new THREE.Raycaster(); let down = [0, 0];
    const pointerDown = (e: PointerEvent) => { down = [e.clientX, e.clientY]; };
    const pointerUp = (e: PointerEvent) => { if (Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 5) return; const r = el.getBoundingClientRect(); ray.setFromCamera(new THREE.Vector2((e.clientX - r.left) / r.width * 2 - 1, -(e.clientY - r.top) / r.height * 2 + 1), camera); const hit = ray.intersectObject(root, true)[0]; if (hit?.object.userData.instance) pick.current(hit.object.userData.instance); };
    el.addEventListener("pointerdown", pointerDown); el.addEventListener("pointerup", pointerUp);
    let frame = 0; let needsRender = true; const tick = () => { frame = requestAnimationFrame(tick); if (document.hidden || !el.clientWidth || !el.clientHeight) return; const moved = controls.update(); if (needsRender || moved) { renderer.render(stage, camera); needsRender = false; } }; controls.addEventListener("change", () => { needsRender = true; }); const sized = new ResizeObserver(() => { resize(); needsRender = true; }); sized.observe(el); tick();
    return () => { cancelAnimationFrame(frame); sized.disconnect(); controls.dispose(); stage.traverse(o => { if (o instanceof THREE.Mesh || o instanceof THREE.LineSegments) { o.geometry.dispose(); const materials = Array.isArray(o.material) ? o.material : [o.material]; materials.forEach(m => m.dispose()); } }); renderer.dispose(); renderer.forceContextLoss(); renderer.domElement.remove(); el.removeEventListener("pointerdown", pointerDown); el.removeEventListener("pointerup", pointerUp); };
  }, [draft.parts, draft.assemblies, draft.scenes, mode, selected, config, instance]);
  return <div className="absolute inset-0" ref={host}>{error && <div className="p-5 text-sm text-destructive">{error}</div>}</div>;
}

export default function ProjectProposal() {
  useEffect(() => { const previous = document.title; document.title = "caliper — redesign prototype"; return () => { document.title = previous; }; }, []);
  const [draft, setDraft] = useState<Draft>(initial);
  const [mode, setMode] = useState<Mode>("scenes");
  const [selection, setSelection] = useState<Record<Mode, string>>({ components: "motor", assemblies: "quad", scenes: draft.active });
  const [instanceId, setInstanceId] = useState("front_left");
  const [sourceOpen, setSourceOpen] = useState(false);
  const [navigator, setNavigator] = useState<"design" | "files" | "changes">("design");
  const [sessionsOpen, setSessionsOpen] = useState(true);
  const [notesOpen, setNotesOpen] = useState(false);
  const [notes, setNotes] = useState(() => { try { return localStorage.getItem(KEY + ".notes") || ""; } catch { return ""; } });
  const [workspaceView, setWorkspaceView] = useState(true);
  const [planOpen, setPlanOpen] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [name, setName] = useState("");
  const [recipe, setRecipe] = useState("box");
  const [addRef, setAddRef] = useState("component:motor");
  const [dirty, setDirty] = useState(false);
  const selected = selection[mode];
  const part = draft.parts.find(p => p.id === selection.components) || draft.parts[0];
  const assembly = draft.assemblies.find(a => a.id === selection.assemblies) || draft.assemblies[0];
  const scene = draft.scenes.find(s => s.id === selection.scenes) || draft.scenes[0];
  const instance = assembly.instances.find(i => i.id === instanceId);
  const title = workspaceView ? "Live design" : mode === "components" ? part.name : mode === "assemblies" ? assembly.name : scene.name;
  const owner = mode === "components" ? part.owner : mode === "assemblies" && assembly.id === "leg" ? "leg-kit" : "odrive-quad";
  const sourcePath = `cad/${mode}/${selected}.${mode === "components" ? "py" : "json"}`;
  const config = useMemo<Values>(() => mode === "scenes" ? scene.config : mode === "assemblies" ? { motors: true } : {}, [mode, scene.config]);
  const items = mode === "components" ? draft.parts : draft[mode];
  function change(update: (d: Draft) => Draft) { setDraft(update); setDirty(true); }
  function choose(id: string) { setWorkspaceView(false); setSelection(prev => ({ ...prev, [mode]: id })); setSourceOpen(false); setInstanceId(""); }
  function switchMode(next: Mode) { setWorkspaceView(false); setNavigator("design"); setMode(next); setSourceOpen(false); setInstanceId(next === "assemblies" ? "front_left" : ""); }
  function save() { try { localStorage.setItem(KEY, JSON.stringify(draft)); setDirty(false); toast("Prototype draft saved in this browser. Design files are unchanged."); } catch { toast.error("Browser storage is unavailable."); } }
  function updateInstance(patch: Partial<Instance>) { change(d => ({ ...d, assemblies: d.assemblies.map(a => a.id === assembly.id ? { ...a, instances: a.instances.map(i => i.id === instanceId ? { ...i, ...patch } : i) } : a) })); }
  function create() {
    if (!name.trim()) return; const id = name.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_") + "_" + Date.now().toString(36);
    change(d => {
      if (mode === "components") return { ...d, parts: [...d.parts, { id, name: name.trim(), shape: recipe, owner: "odrive-quad", params: recipe === "cylinder" ? { radius: 12, height: 30 } : { length: 40, width: 30, height: 20 }, color: 0x94a3b8 }] };
      if (mode === "assemblies") return { ...d, assemblies: [...d.assemblies, { id, name: name.trim(), instances: [] }] };
      return { ...d, scenes: [...d.scenes, { id, name: name.trim(), assembly: recipe, config: { hipSpan: 130, legLength: 110, motors: true } }] };
    });
    choose(id); setCreateOpen(false);
  }
  function addInstance() {
    const [kind, ref] = addRef.split(":") as ["component" | "assembly", string];
    const id = (name.trim() || ref) + "_" + Date.now().toString(36);
    const next: Instance = { id, kind, ref, origin: [0, 0, 0], rotation: [0, 0, 0] };
    change(d => ({ ...d, assemblies: d.assemblies.map(a => a.id === assembly.id ? { ...a, instances: [...a.instances, next] } : a) }));
    setInstanceId(id); setAddOpen(false);
  }
  const generatedSource = mode === "components" ? `# ${owner}/${sourcePath}\nfrom build123d import Box, Cylinder\n\ndef build(scene, config):\n    # Dimensions belong to this component definition.\n    shape = ${part.shape === "motor" ? 'motor_proxy(config["diameter"], config["length"])' : part.shape === "box" || part.shape === "board" ? 'Box(config["length"], config["width"], config["height"])' : 'link_proxy(config)'}\n    scene.body("part", shape, mass=0.1)\n` : JSON.stringify(mode === "assemblies" ? assembly : scene, null, 2);
  return <div className="flex h-full min-h-0 flex-col bg-background">
    <header className="flex flex-none flex-wrap items-center gap-2 border-b bg-card px-4 py-2.5">
      <a href="#/" className="flex items-center gap-2 font-semibold tracking-tight"><Logo />caliper</a><span className="text-muted-foreground">/</span><span className="font-medium">odrive-quad</span>
      <Badge variant="muted" className="gap-1"><GitBranch className="h-3 w-3" /> main</Badge><Badge variant="outline" className="text-warn">Interactive prototype · example data</Badge>
      <span className="flex-1" /><Button variant="ghost" size="sm" onClick={() => setNotesOpen(true)}><MessageSquare/>Review notes</Button><Button variant={sessionsOpen ? "secondary" : "ghost"} size="sm" onClick={() => setSessionsOpen(v => !v)}><TerminalSquare/>Butai</Button><Button variant="outline" size="sm" asChild><a href="#/">All designs</a></Button>
    </header>
    <div className="flex flex-none flex-wrap items-center gap-1 border-b bg-card px-4 py-2">
      <Button variant={workspaceView ? "secondary" : "ghost"} size="sm" onClick={() => { setWorkspaceView(true); setMode("scenes"); setSelection(s => ({ ...s, scenes: draft.active })); }}><Cuboid/>Workbench</Button>{(["components", "assemblies", "scenes"] as Mode[]).map((tab, index) => <Button key={tab} variant={!workspaceView && mode === tab ? "secondary" : "ghost"} size="sm" onClick={() => switchMode(tab)}>{index === 0 ? <Cuboid /> : index === 1 ? <Layers /> : <Scan />}{tab === "scenes" ? "Scene presets" : tab[0].toUpperCase() + tab.slice(1)}<span className="ml-1 rounded bg-muted px-1.5 text-muted-foreground">{(tab === "components" ? draft.parts : draft[tab]).length}</span></Button>)}
      <span className="flex-1" /><label className="hidden items-center gap-2 text-xs text-muted-foreground xl:flex" htmlFor="prototype-active-scene"><span className="h-1.5 w-1.5 rounded-full bg-good"/>Live scene<select aria-label="Live scene" id="prototype-active-scene" className="max-w-32 rounded border bg-background px-2 py-1 text-foreground" value={draft.active} onChange={e => { const active = e.target.value; change(d => ({ ...d, active })); if (workspaceView) setSelection(s => ({ ...s, scenes: active })); }}>{draft.scenes.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}</select></label><Button size="sm" variant="outline" onClick={save}><Save /> Save draft</Button>
    </div>
    <div className={cn("prototype-grid grid min-h-0 flex-1", sessionsOpen && "with-sessions")}>
      <aside className="flex min-h-0 flex-col border-r bg-card">
        <div className="flex items-center gap-1 border-b p-2">{(["design", "files", "changes"] as const).map(n => <Button key={n} size="xs" variant={navigator === n ? "secondary" : "ghost"} onClick={() => setNavigator(n)}>{n === "files" && <Files/>}{n[0].toUpperCase() + n.slice(1)}{n === "changes" && dirty && <span className="text-warn">●</span>}</Button>)}</div><div className="flex items-center gap-2 border-b px-3 py-3 text-sm font-medium"><span>{mode === "scenes" ? "Scene presets" : mode[0].toUpperCase() + mode.slice(1)}</span><span className="flex-1" /><Button size="xs" variant="ghost" title={`Create ${mode.slice(0, -1)}`} onClick={() => { setName(""); setRecipe(mode === "scenes" ? "quad" : "box"); setCreateOpen(true); }}><Plus /> New</Button></div>
        <div className="min-h-0 flex-1 overflow-y-auto py-2">
          {navigator === "design" && <><div className="flex items-center gap-2 px-3 py-2 text-xs text-muted-foreground"><FolderGit2 className="h-4 w-4" /> Project library</div>
          {items.map(item => <button key={item.id} onClick={() => choose(item.id)} className={cn("flex w-full items-center gap-2 border-l-2 px-3 py-2.5 text-left text-sm transition-colors hover:bg-accent/50", selected === item.id ? "border-primary bg-primary/10" : "border-transparent")}>
            {mode === "components" ? <Box className="h-4 w-4 shrink-0 text-muted-foreground" /> : mode === "assemblies" ? <Layers className="h-4 w-4 shrink-0 text-muted-foreground" /> : <Scan className="h-4 w-4 shrink-0 text-muted-foreground" />}<span className="min-w-0 flex-1 truncate">{item.name}</span>{mode === "scenes" && draft.active === item.id && <Check className="h-3 w-3 text-good" />}
          </button>)}
          {mode === "assemblies" && <div className="mt-4 border-t pt-2"><div className="flex items-center gap-2 px-3 py-2 text-xs text-muted-foreground">Instances <span className="ml-auto">{assembly.instances.length}</span></div>{assembly.instances.length === 0 && <p className="px-3 py-2 text-xs text-muted-foreground">Add a component or another assembly to start.</p>}{assembly.instances.map(node => <button key={node.id} onClick={() => setInstanceId(node.id)} className={cn("flex w-full items-center gap-2 px-3 py-2 text-left text-xs hover:bg-accent/50", instanceId === node.id && "bg-secondary")}><ChevronRight className="h-3 w-3 text-muted-foreground" />{node.kind === "assembly" ? <Layers className="h-3 w-3 text-muted-foreground" /> : <Cuboid className="h-3 w-3 text-muted-foreground" />}<span className="truncate">{node.id}</span></button>)}</div>}
          </>}{navigator === "files" && <div className="space-y-1 px-2"><p className="px-2 py-2 text-xs text-muted-foreground">Project files · example tree</p>{draft.parts.map(p => <button key={p.id} className="flex w-full items-center gap-2 rounded px-2 py-2 text-left font-mono text-xs hover:bg-accent" onClick={() => { setWorkspaceView(false); setMode("components"); setSelection(s => ({ ...s, components: p.id })); setSourceOpen(true); }}><Braces size={13}/>{p.owner === "leg-kit" ? "kits/leg/" : ""}{p.id}.py</button>)}<button className="flex w-full items-center gap-2 rounded px-2 py-2 text-left font-mono text-xs hover:bg-accent" onClick={() => { setWorkspaceView(false); setMode("scenes"); setSourceOpen(true); }}><Braces size={13}/>cad/project.json</button><p className="px-2 pt-4 text-xs leading-5 text-muted-foreground">Open a file here and keep the same inspector and Butai sessions.</p></div>}{navigator === "changes" && <div className="space-y-4 p-3"><div className="flex items-center gap-2 text-xs"><GitBranch size={14}/>main <span className="ml-auto text-muted-foreground">Demo repository</span></div><p className="text-xs leading-5 text-muted-foreground">{dirty ? "Your prototype draft has changes. Save it to keep them in this browser." : "Your prototype draft is saved. Try changing a dimension or a scene preset."}</p>{dirty && <div className="rounded border p-3 font-mono text-xs text-warn">M {sourcePath}</div>}<Button size="xs" variant="outline" onClick={save}><Save/>Save browser draft</Button><p className="text-xs leading-5 text-muted-foreground">In the real workspace, Files & Git stages and commits project files. Child geometry stays in its owning repository.</p></div>}
        </div>
        <div className="space-y-2 border-t p-3 text-xs text-muted-foreground"><div className="flex items-center gap-2 text-foreground"><FolderGit2 className="h-4 w-4" /> Included projects</div><div className="flex justify-between"><span>leg-kit</span><span className="font-mono">a7e34c2</span></div><p>Components and the leg assembly belong to their own repository.</p></div>
      </aside>
      <main className="flex min-h-0 min-w-0 flex-col">
        <div className="flex flex-none items-center gap-2 border-b px-4 py-3"><div className="min-w-0"><h1 className="truncate text-base font-medium">{title}</h1><p className="mt-1 text-xs text-muted-foreground">{workspaceView ? `Live scene: ${draft.scenes.find(s => s.id === draft.active)?.name} · saved assembly configuration` : mode === "components" ? "Inspect and edit one reusable component" : mode === "assemblies" ? "Compose reusable parts and subassemblies" : "Configure an assembly without changing its definition"}</p></div><span className="flex-1" /><Button size="xs" variant={!sourceOpen ? "secondary" : "ghost"} onClick={() => setSourceOpen(false)}><Eye /> 3D</Button><Button size="xs" variant={sourceOpen ? "secondary" : "ghost"} onClick={() => setSourceOpen(true)}><Braces /> Source</Button></div>
        <div className="relative min-h-[240px] flex-1">
          {sourceOpen ? <div className="flex h-full flex-col"><div className="border-b px-4 py-2 font-mono text-xs text-muted-foreground">{owner} / {sourcePath}</div><textarea aria-label="Component source draft" spellCheck={false} value={draft.sources[`${mode}:${selected}`] ?? generatedSource} onChange={e => change(d => ({ ...d, sources: { ...d.sources, [`${mode}:${selected}`]: e.target.value } }))} className="min-h-0 flex-1 resize-none bg-background p-5 font-mono text-sm leading-7 text-foreground outline-none" /><div className="border-t p-3 text-xs text-muted-foreground">Prototype source draft only. Python execution will be connected after UI review.</div></div> : <><Preview draft={draft} mode={mode} selected={selected} config={config} instance={mode === "assemblies" ? instanceId : ""} onPick={setInstanceId} /><div className="pointer-events-none absolute left-3 top-3 rounded border bg-background/80 px-2 py-1 text-xs text-muted-foreground">{mode === "components" ? "Isolated component" : mode === "assemblies" ? "Assembly preview · click an instance" : "Scene preview"} · mm</div><div className="pointer-events-none absolute bottom-4 left-4 text-xs text-muted-foreground">Drag to orbit · scroll to zoom</div>{mode === "scenes" && <div className="absolute right-3 top-3"><Badge variant={draft.active === selected ? "muted" : "outline"}>{draft.active === selected ? "Active scene in prototype" : "Scene preset"}</Badge></div>}</>}
        </div>
        <footer className="flex flex-none flex-wrap items-center gap-4 border-t bg-card px-4 py-2 text-xs text-muted-foreground"><span>view <b className="text-foreground">{mode.slice(0, -1)}</b></span><span>owner <b className="text-foreground">{owner}</b></span><span className="ml-auto">Three.js mock geometry · no design files changed</span></footer>
      </main>
      <aside className="min-h-0 overflow-y-auto border-l bg-card max-[760px]:col-span-2 max-[760px]:max-h-72 max-[760px]:border-t">
        <div className="border-b px-4 py-3 text-sm font-medium">{mode === "components" ? "Component" : mode === "assemblies" && instance ? "Instance" : mode === "assemblies" ? "Assembly" : "Scene"} inspector</div>
        <div className="space-y-6 p-4">
          {mode === "components" && <><section><h2 className="mb-3 text-xs font-medium text-muted-foreground">Dimensions</h2><Fields values={part.params} onChange={params => change(d => ({ ...d, parts: d.parts.map(p => p.id === part.id ? { ...p, params } : p) }))} /></section><div className="rounded-md border bg-background p-3 text-xs leading-5 text-muted-foreground">Changes update the preview immediately. Assembly instances reuse this definition.</div><Button variant="outline" size="sm" className="w-full" onClick={() => setSourceOpen(true)}><Braces /> Edit geometry source</Button></>}
          {mode === "assemblies" && <><Button size="sm" className="w-full" onClick={() => { setName(""); setAddRef("component:motor"); setAddOpen(true); }}><Plus /> Add instance</Button>{instance ? <><section><h2 className="mb-2 text-xs text-muted-foreground">Selected instance</h2><div className="font-mono text-sm">{instance.id}</div><div className="mt-1 text-xs text-muted-foreground">Uses {draft.parts.find(p => p.id === instance.ref)?.name || draft.assemblies.find(a => a.id === instance.ref)?.name}</div></section><Triple label="Position (mm)" value={instance.origin} onChange={origin => updateInstance({ origin })} /><Triple label="Rotation (degrees)" value={instance.rotation} onChange={rotation => updateInstance({ rotation })} /><div className="flex gap-2"><Button size="sm" variant="outline" onClick={() => { const cloned = { ...instance, id: `${instance.id}_copy_${Date.now().toString(36)}`, origin: [instance.origin[0] + 60, instance.origin[1], instance.origin[2]] as Vec }; change(d => ({ ...d, assemblies: d.assemblies.map(a => a.id === assembly.id ? { ...a, instances: [...a.instances, cloned] } : a) })); setInstanceId(cloned.id); }}><Copy /> Duplicate</Button><Button size="sm" variant="ghost" title="Remove instance" onClick={() => { change(d => ({ ...d, assemblies: d.assemblies.map(a => a.id === assembly.id ? { ...a, instances: a.instances.filter(i => i.id !== instance.id) } : a) })); setInstanceId(""); }}><Trash2 /></Button></div><Button size="sm" variant="ghost" className="w-full" onClick={() => { const target = instance.kind === "component" ? "components" : "assemblies"; setSelection(s => ({ ...s, [target]: instance.ref })); switchMode(target); }}><Eye /> Open definition</Button></> : <p className="text-xs text-muted-foreground">Select an instance in the tree or 3D view to edit its placement.</p>}</>}
          {mode === "scenes" && <><div className="rounded border bg-background p-3 text-xs leading-5 text-muted-foreground"><b className="text-foreground">What is a scene preset?</b><p className="mt-1">An assembly with saved dimensions and environment. Inspect any preset; use it to change the live workspace.</p></div><section><label className="mb-2 block text-xs text-muted-foreground" htmlFor="scene-assembly">Assembly</label><select id="scene-assembly" className={field} value={scene.assembly} onChange={e => change(d => ({ ...d, scenes: d.scenes.map(s => s.id === scene.id ? { ...s, assembly: e.target.value } : s) }))}>{draft.assemblies.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}</select></section><section><h2 className="mb-3 text-xs font-medium text-muted-foreground">Scene configuration</h2><Fields values={scene.config} onChange={config => change(d => ({ ...d, scenes: d.scenes.map(s => s.id === scene.id ? { ...s, config } : s) }))} /></section><Button className="w-full" size="sm" onClick={() => { change(d => ({ ...d, active: scene.id })); toast(`${scene.name} selected in the prototype`); }}>{draft.active === scene.id ? <Check /> : <Scan />}{draft.active === scene.id ? "Used in workspace" : "Use in workspace"}</Button><Button size="sm" variant="outline" className="w-full" onClick={() => { const id = scene.id + "_copy_" + Date.now().toString(36); change(d => ({ ...d, scenes: [...d.scenes, { ...scene, config: { ...scene.config }, id, name: scene.name + " copy" }] })); choose(id); }}><Copy /> Duplicate scene</Button><p className="text-xs leading-5 text-muted-foreground">Each scene keeps its own configuration. Switching scenes preserves the component and assembly definitions.</p></>}
          <section className="space-y-3 border-t pt-4"><h2 className="flex items-center gap-2 text-xs font-medium"><FolderGit2 className="h-4 w-4" /> Repository ownership</h2><dl className="space-y-2 text-xs"><div className="flex justify-between gap-2"><dt className="text-muted-foreground">Project</dt><dd>{owner}</dd></div><div className="flex justify-between"><dt className="text-muted-foreground">Branch</dt><dd className="font-mono">main</dd></div><div className="flex justify-between"><dt className="text-muted-foreground">Version</dt><dd className="font-mono">{owner === "leg-kit" ? "a7e34c2" : "c46fa91"}</dd></div></dl><div className="break-all rounded bg-background p-2 font-mono text-xs text-muted-foreground">{sourcePath}</div><p className="text-xs leading-5 text-muted-foreground">{owner === "leg-kit" ? "Commit changes in leg-kit, then update its pin in odrive-quad." : "Definitions and scene presets are tracked in this project's Git repository."}</p><Badge variant="outline">Example repository · browser drafts</Badge></section>
        </div>
      </aside>
      {sessionsOpen && <div className="prototype-sessions min-h-0"><PrototypeSessions context={title}/></div>}
    </div>
    <div className="flex flex-none flex-wrap items-center gap-2 border-t bg-card px-4 py-2 text-xs text-muted-foreground"><span className="h-1.5 w-1.5 rounded-full bg-warn" /> Review prototype · changes save in this browser.<span className="flex-1" /><button className="flex items-center gap-1 hover:text-foreground" onClick={() => { localStorage.removeItem(KEY); setDraft(structuredClone(seed)); setSelection({ components: "motor", assemblies: "quad", scenes: "standing" }); setInstanceId("front_left"); setDirty(false); }}><RotateCcw className="h-3 w-3" /> Reset demo</button></div>
    <Dialog open={notesOpen} onOpenChange={setNotesOpen}><DialogContent><DialogHeader><DialogTitle>Review notes</DialogTitle><DialogDescription>Try the library, scene presets, files and CLI panes. Save your feedback here, then copy it into our conversation.</DialogDescription></DialogHeader><textarea aria-label="Review feedback" value={notes} onChange={e => { setNotes(e.target.value); try { localStorage.setItem(KEY + ".notes", e.target.value); } catch { /* keep current notes */ } }} className="h-48 resize-y rounded border bg-background p-3 text-sm" placeholder="What feels better? What is confusing? What should change?"/><Button onClick={async () => { try { await navigatorClipboard(notes); toast.success("Review notes copied"); } catch { toast.error("Select the notes and copy them manually."); } }} disabled={!notes.trim()}>Copy feedback</Button><Button variant="ghost" onClick={() => { setNotesOpen(false); setPlanOpen(true); }}>Read the design rationale</Button></DialogContent></Dialog>
    <Dialog open={createOpen} onOpenChange={setCreateOpen}><DialogContent><DialogHeader><DialogTitle>New {mode.slice(0, -1)}</DialogTitle><DialogDescription>Create a definition in the prototype project library.</DialogDescription></DialogHeader><label className="space-y-2 text-sm">Name<Input autoFocus aria-label="Definition name" value={name} onChange={e => setName(e.target.value)} placeholder={mode === "components" ? "Motor mount" : mode === "assemblies" ? "Drive module" : "Low stance"} /></label>{mode !== "assemblies" && <label className="space-y-2 text-sm">{mode === "components" ? "Starting shape" : "Assembly"}<select aria-label="Starting definition" className={field} value={recipe} onChange={e => setRecipe(e.target.value)}>{mode === "components" ? <><option value="box">Box</option><option value="cylinder">Cylinder</option></> : draft.assemblies.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}</select></label>}<Button disabled={!name.trim()} onClick={create}><Plus /> Create {mode.slice(0, -1)}</Button></DialogContent></Dialog>
    <Dialog open={addOpen} onOpenChange={setAddOpen}><DialogContent><DialogHeader><DialogTitle>Add an instance</DialogTitle><DialogDescription>Reuse a component or subassembly with its own placement.</DialogDescription></DialogHeader><label className="space-y-2 text-sm">Definition<select aria-label="Instance definition" className={field} value={addRef} onChange={e => setAddRef(e.target.value)}><optgroup label="Components">{draft.parts.map(p => <option key={p.id} value={`component:${p.id}`}>{p.name}</option>)}</optgroup><optgroup label="Assemblies">{draft.assemblies.filter(a => a.id !== assembly.id && !(assembly.id === "leg" && a.id === "quad")).map(a => <option key={a.id} value={`assembly:${a.id}`}>{a.name}</option>)}</optgroup></select></label><label className="space-y-2 text-sm">Instance name<Input aria-label="Instance name" value={name} onChange={e => setName(e.target.value)} placeholder="rear_motor" /></label><Button onClick={addInstance}><Plus /> Add to {assembly.name}</Button></DialogContent></Dialog>
    <Dialog open={planOpen} onOpenChange={setPlanOpen}><DialogContent className="max-h-[85vh] max-w-2xl overflow-y-auto"><DialogHeader><DialogTitle>Integrated workspace design</DialogTitle><DialogDescription>A shared workspace connects reusable geometry, scene presets, files, Git and container-owned Butai sessions.</DialogDescription></DialogHeader><div className="space-y-5 text-sm">{[
      ["1. One workspace", "Keep the same header, file editor and Butai sessions as you move between the live design and reusable definitions."],
      ["2. Responsive previews", "Selected objects become editable immediately. The real app queues CAD builds, warms nearby parts, caches results and labels the previous preview while a build is pending."],
      ["3. Clear scene presets", "Parts make assemblies. Presets configure an assembly and its environment. Inspecting a preset is separate from using it for the live model, simulation and exports."],
      ["4. CLI choice and control", "Claude, Codex and Gemini are provisioned in Docker. Butai owns their panes inside that same container, alongside custom CLI processes and shells."],
      ["5. Keep project ownership", "Geometry remains code, definitions stay with their owning Git project, and included projects keep pinned versions. The prototype edits browser drafts; the real workspace edits project files."],
    ].map(([heading, detail]) => <section key={heading}><h3 className="mb-1 font-medium">{heading}</h3><p className="leading-6 text-muted-foreground">{detail}</p></section>)}<div className="rounded-md border bg-background p-4 text-xs leading-6 text-muted-foreground">Review target: inspect a motor → modify a hip link → assemble a leg → reuse four legs → save standing, wide and bench scenes. All persistent definitions belong to their owning Git project.</div></div></DialogContent></Dialog>
  </div>;
}
