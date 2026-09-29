import { useCallback, useEffect, useRef, useState } from "react";
import { Viewer } from "@/viewer/viewer";
// physics.js is the proven vanilla module, imported unchanged (see plan).
import type { Physics } from "@/viewer/physics.js";
import { artifact, fetchScene } from "@/lib/api";
import type { Scene } from "@/lib/types";

/** The design's own parts: everything except scenery. A body that is `fixed`
 *  and that no joint touches is the floor; framing or measuring it would report
 *  the size of the world. tools/bundle.py drops the same bodies from an export. */
export function modelBodies(sc: Scene): string[] {
  const jointed = new Set<string>();
  for (const j of sc.joints || []) {
    jointed.add(j.a);
    jointed.add(j.b);
  }
  const own = sc.bodies.filter((b) => b.type !== "fixed" || jointed.has(b.name));
  return (own.length ? own : sc.bodies).map((b) => b.name);
}

export interface ViewerStats {
  parts: number;
  joints: number;
  size: string;
  builtAt: Date | null;
}

export interface UseViewer {
  containerRef: (el: HTMLDivElement | null) => void;
  status: string;
  scene: Scene | null;
  stats: ViewerStats;
  hasJoints: boolean;
  running: boolean;
  simTime: number;
  simSteps: number;
  reload: () => void;
  play: () => void;
  reset: () => void;
  setVisible: (name: string, on: boolean) => void;
  fit: () => void;
  highlight: (name: string | null) => void;
}

const EMPTY_STATS: ViewerStats = { parts: 0, joints: 0, size: "—", builtAt: null };

export function useViewer(slug: string, directory = "", focus?: string, onSelect?: (name: string | null) => void): UseViewer {
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;
  const viewerRef = useRef<Viewer | null>(null);
  const physicsRef = useRef<InstanceType<typeof Physics> | null>(null);
  const sceneRef = useRef<Scene | null>(null);
  const runningRef = useRef(false);
  const lastStamp = useRef<string | null>(null);
  const loadSequence = useRef(0);
  const rafRef = useRef(0);
  const focusRef = useRef(focus);
  focusRef.current = focus;
  const builtAtRef = useRef<Date | null>(null);
  const modelReady = useRef(false);

  const physicsConstructor = useRef<typeof Physics | null>(null);
  const preparingPhysics = useRef(false);

  const [status, setStatus] = useState("initializing…");
  const [scene, setScene] = useState<Scene | null>(null);
  const [stats, setStats] = useState<ViewerStats>(EMPTY_STATS);
  const [hasJoints, setHasJoints] = useState(false);
  const [running, setRunning] = useState(false);
  const [simTime, setSimTime] = useState(0);
  const [simSteps, setSimSteps] = useState(0);

  // ---- attach the viewer to its container div (a callback ref so we react to
  // the element mounting/unmounting) --------------------------------------
  const containerRef = useCallback((el: HTMLDivElement | null) => {
    if (el && !viewerRef.current) {
      viewerRef.current = new Viewer(el);
      viewerRef.current.onSelect = name => onSelectRef.current?.(name);
    } else if (!el && viewerRef.current) {
      viewerRef.current.dispose();
      viewerRef.current = null;
    }
  }, []);

  const applyFocus = useCallback(() => {
    const viewer = viewerRef.current;
    const sc = sceneRef.current;
    if (!viewer || !sc || !modelReady.current) return;
    const selected = focusRef.current;
    runningRef.current = false;
    setRunning(false);
    physicsRef.current = null;
    viewer.resetBodies();
    const found = viewer.isolate(selected || null);
    const own = selected ? (found ? [selected] : []) : modelBodies(sc);
    viewer.frameAll(own, !!selected);
    const joints = selected ? 0 : (sc.joints || []).length;
    const parts = selected ? Number(found) : own.length + (sc.decor || []).length;
    setStats({ parts, joints, size: viewer.sizeText(own), builtAt: builtAtRef.current });
    setHasJoints(joints > 0);
    setSimTime(0);
    setSimSteps(0);
    setStatus(selected ? (found ? "1 part" : "Part unavailable in this model") :
      joints ? `${sc.bodies.length} bodies · ${joints} joints` : `${own.length} part${own.length === 1 ? "" : "s"}`);
  }, []);

  useEffect(() => { applyFocus(); }, [focus, applyFocus]);

  const loadAll = useCallback(async () => {
    const viewer = viewerRef.current;
    if (!viewer) return;
    const token = ++loadSequence.current;
    modelReady.current = false;
    runningRef.current = false;
    setRunning(false);
    setStatus("fetching scene…");
    let sc: Scene;
    let builtAt: Date | null;
    try {
      const got = await fetchScene(slug, directory);
      sc = got.scene;
      builtAt = got.builtAt;
    } catch (e) {
      if (token === loadSequence.current) setStatus("error: " + (e as Error).message);
      return;
    }
    if (token !== loadSequence.current || viewer !== viewerRef.current) return;
    sceneRef.current = sc;
    setScene(sc);

    setStatus("loading model…");
    const bump = /^project-previews\/[0-9a-f]{20}$/.test(directory) ? "" : `?v=${builtAt?.getTime() ?? Date.now()}`;
    await viewer.loadModel(artifact(slug, `${directory ? directory + "/" : ""}model.glb${bump}`), sc);

    if (token !== loadSequence.current || viewer !== viewerRef.current) return;
    builtAtRef.current = builtAt;
    modelReady.current = true;
    applyFocus();

  }, [slug, directory, applyFocus]);

  // ---- the re-export watch + the first-load fix -------------------------
  // The vanilla app only reloaded on a *changed* stamp and swallowed the first
  // one, so a design opened before out/ was built never appeared until a manual
  // reload. Here: if nothing is loaded yet, the first stamp that exists loads.
  const checkForRebuild = useCallback(async () => {
    try {
      const r = await fetch(artifact(slug, `${directory ? directory + "/" : ""}model.glb?head=${Date.now()}`), {
        method: "HEAD",
      });
      if (!r.ok) return;
      const stamp =
        r.headers.get("last-modified") || r.headers.get("content-length");
      const haveScene = sceneRef.current != null;
      const changed = !!lastStamp.current && !!stamp && stamp !== lastStamp.current;
      if (!runningRef.current && stamp && (!haveScene || changed)) {
        await loadAll();
      }
      lastStamp.current = stamp;
    } catch {
      /* mid-write; try again next tick */
    }
  }, [slug, directory, loadAll]);

  // ---- lifecycle: load once, then poll the rebuild watch ----------------
  useEffect(() => {
    sceneRef.current = null;
    modelReady.current = false;
    setScene(null);
    lastStamp.current = null;
    loadAll().catch(e => setStatus("error: " + (e as Error).message));
    // Cached preview directories are immutable; only watch the live design.
    if (directory) return () => { ++loadSequence.current; };
    const t = window.setInterval(checkForRebuild, 2000);
    return () => { ++loadSequence.current; window.clearInterval(t); };
  }, [loadAll, checkForRebuild]);

  // ---- the physics tick (only runs while playing) -----------------------
  useEffect(() => {
    if (!running) return;
    const tick = () => {
      rafRef.current = requestAnimationFrame(tick);
      const physics = physicsRef.current;
      const viewer = viewerRef.current;
      if (!runningRef.current || !physics || !viewer) return;
      physics.step();
      for (const { name, p, q } of physics.transforms())
        viewer.setBodyTransform(name, p, q);
      setSimTime(physics.time);
      setSimSteps(physics.steps);
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafRef.current);
  }, [running]);

  const reload = useCallback(() => {
    loadAll().catch((e) => setStatus("error: " + (e as Error).message));
  }, [loadAll]);

  const play = useCallback(async () => {
    if (preparingPhysics.current || focusRef.current) return;
    if (!physicsRef.current) {
      const sc = sceneRef.current;
      const viewer = viewerRef.current;
      if (!sc || !viewer || !sc.joints?.length) return;
      preparingPhysics.current = true;
      setStatus("Preparing simulation…");
      try {
        const { Physics: Engine, initPhysics } = await import("@/viewer/physics.js");
        await initPhysics();
        // Selection might have changed while the engine downloaded.
        if (sceneRef.current !== sc || viewerRef.current !== viewer || focusRef.current) return;
        physicsConstructor.current = Engine;
        physicsRef.current = new Engine().build(sc, viewer.bodies);
        setStatus(`${sc.bodies.length} bodies · ${sc.joints.length} joints`);
      } catch (e) {
        setStatus("Simulation could not start: " + (e as Error).message);
        return;
      } finally { preparingPhysics.current = false; }
    }
    runningRef.current = !runningRef.current;
    setRunning(runningRef.current);
  }, []);

  const reset = useCallback(() => {
    runningRef.current = false;
    setRunning(false);
    const viewer = viewerRef.current;
    const sc = sceneRef.current;
    if (viewer && sc && physicsConstructor.current && physicsRef.current)
      physicsRef.current = new physicsConstructor.current().build(sc, viewer.bodies);
    viewer?.resetBodies();
    setSimTime(0);
    setSimSteps(0);
  }, []);

  const setVisible = useCallback((name: string, on: boolean) => {
    viewerRef.current?.setVisible(name, on);
  }, []);
  const fit = useCallback(() => { const sc = sceneRef.current; if (sc) viewerRef.current?.frameAll(focusRef.current ? [focusRef.current] : modelBodies(sc), !!focusRef.current); }, []);
  const highlight = useCallback((name: string | null) => { viewerRef.current?.highlight(name); }, []);

  return {
    containerRef,
    status,
    scene,
    stats,
    hasJoints,
    running,
    simTime,
    simSteps,
    reload,
    play,
    reset,
    setVisible,
    fit,
    highlight,
  };
}
