// three.js viewer: loads out/model.glb, exposes each body node by name so the
// physics engine can drive its world transform. Z is up (matches the CAD).
//
// Ported from the old viewer.js with two render fixes the vanilla app lacked:
//   - a ResizeObserver on the container, so the canvas tracks panel resizes
//     (dock expanding, rails dragging) and not just window resizes; and
//   - a guard against a zero-size container, which used to leave the camera
//     with an Infinity aspect that only a window resize could recover.
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import type { Scene as SceneJson } from "@/lib/types";

export interface ViewerBody {
  node: THREE.Group;
  homePos: THREE.Vector3;
  homeQuat: THREE.Quaternion;
  localVerts: Float32Array;
}

// Retain a few parsed exports so the workspace and its isolated part viewer
// can reuse the same download and parse. Each viewer owns a geometry clone;
// releasing one canvas must never dispose another canvas's model.
const parsedModels = new Map<string, Promise<THREE.Group>>();
const MODEL_CACHE_LIMIT = 4;
function disposeParsed(root: THREE.Group) {
  root.traverse(node => {
    if (!(node instanceof THREE.Mesh)) return;
    node.geometry.dispose();
    const materials = Array.isArray(node.material) ? node.material : [node.material];
    materials.forEach(material => material.dispose());
  });
}
function parsedModel(url: string, loader: GLTFLoader): Promise<THREE.Group> {
  const cached = parsedModels.get(url);
  if (cached) {
    parsedModels.delete(url);
    parsedModels.set(url, cached);
    return cached;
  }
  const pending = loader.loadAsync(url).then(gltf => {
    gltf.scene.traverse(node => {
      if (node instanceof THREE.Mesh && !node.geometry.getAttribute("normal"))
        node.geometry.computeVertexNormals();
    });
    return gltf.scene;
  });
  parsedModels.set(url, pending);
  pending.catch(() => { if (parsedModels.get(url) === pending) parsedModels.delete(url); });
  while (parsedModels.size > MODEL_CACHE_LIMIT) {
    const first = parsedModels.entries().next().value;
    if (!first) break;
    parsedModels.delete(first[0]);
    void first[1].then(disposeParsed, () => {});
  }
  return pending;
}

export class Viewer {
  container: HTMLElement;
  bodies = new Map<string, ViewerBody>();
  decor = new Map<string, THREE.Object3D>();

  scene: THREE.Scene;
  camera: THREE.PerspectiveCamera;
  renderer: THREE.WebGLRenderer;
  controls: OrbitControls;
  root: THREE.Group;
  loader: GLTFLoader;
  onSelect?: (name: string | null) => void;
  private selected: string | null = null;
  private pointerStart: { x: number; y: number } | null = null;
  private raycaster = new THREE.Raycaster();

  private observer: ResizeObserver;
  private frame = 0;
  private disposed = false;
  private needsRender = true;
  private loadSequence = 0;

  constructor(container: HTMLElement) {
    this.container = container;
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x0b0f17);

    // A zero-size container at construction used to poison the camera aspect.
    // Fall back to 1×1 and let the observer fix it the instant layout settles.
    const w = container.clientWidth || 1;
    const h = container.clientHeight || 1;
    this.camera = new THREE.PerspectiveCamera(45, w / h, 1, 5000);
    this.camera.up.set(0, 0, 1);
    this.camera.far = 20000;
    this.camera.position.set(650, -1050, 800);

    this.renderer = new THREE.WebGLRenderer({ antialias: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.setSize(w, h);
    container.appendChild(this.renderer.domElement);
    this.renderer.domElement.addEventListener("pointerdown", this.startPick);
    this.renderer.domElement.addEventListener("pointerup", this.finishPick);

    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.addEventListener("change", () => { this.needsRender = true; });
    this.controls.target.set(0, 0, 250);

    this.scene.add(new THREE.HemisphereLight(0xbcd4ff, 0x1a2233, 1.1));
    const key = new THREE.DirectionalLight(0xffffff, 2.2);
    key.position.set(120, -160, 240);
    this.scene.add(key);

    const grid = new THREE.GridHelper(4000, 40, 0x2a3a57, 0x1a2740);
    grid.rotation.x = Math.PI / 2; // into XY plane (Z up)
    this.scene.add(grid);

    this.root = new THREE.Group();
    this.scene.add(this.root);

    this.loader = new GLTFLoader();

    // Track the container's own box, not just the window: the viewport shares a
    // resizable layout, so its size changes without any window resize firing.
    this.observer = new ResizeObserver(() => this.resize());
    this.observer.observe(container);
    window.addEventListener("resize", this.resize);

    this.animate();
  }

  private material(mesh: THREE.Mesh) {
    if (!mesh.geometry.getAttribute("normal")) mesh.geometry.computeVertexNormals();
    const hasVColor = !!mesh.geometry.getAttribute("color");
    mesh.material = new THREE.MeshStandardMaterial({
      color: hasVColor ? 0xffffff : 0x8899aa,
      vertexColors: hasVColor,
      metalness: 0.1,
      roughness: 0.55,
    });
  }

  private releaseModel() {
    this.root.traverse(node => {
      if (!(node instanceof THREE.Mesh)) return;
      node.geometry.dispose();
      const materials = Array.isArray(node.material) ? node.material : [node.material];
      materials.forEach(material => material.dispose());
    });
    this.root.clear();
    this.bodies.clear();
    this.decor.clear();
  }

  // `scene` is the parsed scene.json; it tells us which body each decor node is
  // bolted to. Without it decor still loads, just unparented.
  async loadModel(url: string, scene: SceneJson | null = null) {
    const token = ++this.loadSequence;
    const original = await parsedModel(url, this.loader);
    if (this.disposed || token !== this.loadSequence) return this.bodies;
    this.needsRender = true;
    this.releaseModel();

    const meshes: THREE.Mesh[] = [];
    const importedScene = original.clone(true);
    importedScene.traverse((o) => {
      if (!(o instanceof THREE.Mesh)) return;
      o.geometry = o.geometry.clone();
      meshes.push(o);
    });

    // GLTFLoader sanitizes punctuation in node.name. Keep the original CAD
    // names so namespaced assemblies and decor still match scene.json.
    const imported = meshes.map(mesh => {
      mesh.updateWorldMatrix(true, false);
      return { mesh, name: String(mesh.userData.name || mesh.parent?.userData.name || mesh.name),
               world: mesh.matrixWorld.clone() };
    });
    const decorMeshes: [string, THREE.Mesh, THREE.Matrix4][] = [];
    for (const { mesh, name, world } of imported) {
      if (!name) continue;
      if (name.startsWith("decor:")) {
        decorMeshes.push([name, mesh, world]);
        continue;
      }
      this.material(mesh);
      const home = new THREE.Vector3();
      const homeQuat = new THREE.Quaternion();
      const homeScale = new THREE.Vector3();
      world.decompose(home, homeQuat, homeScale);

      const posAttr = mesh.geometry.getAttribute("position");
      const localVerts = (posAttr.array as Float32Array).slice();

      const group = new THREE.Group();
      group.name = name;
      group.position.copy(home);
      group.quaternion.copy(homeQuat);
      group.scale.copy(homeScale);
      mesh.position.set(0, 0, 0);
      mesh.quaternion.identity();
      mesh.scale.set(1, 1, 1);
      group.add(mesh);
      this.root.add(group);

      this.bodies.set(name, {
        node: group,
        homePos: home.clone(),
        homeQuat: homeQuat.clone(),
        localVerts: Float32Array.from(localVerts),
      });
    }

    const parentOf = new Map(
      (scene && scene.decor ? scene.decor : []).map((d) => [
        `decor:${d.name}`,
        d.parent,
      ]),
    );
    for (const [node, mesh, world] of decorMeshes) {
      const host = this.bodies.get(parentOf.get(node) ?? "");
      if (!host) continue;
      this.material(mesh);
      host.node.updateWorldMatrix(true, false);
      const local = host.node.matrixWorld.clone().invert().multiply(world);
      local.decompose(mesh.position, mesh.quaternion, mesh.scale);
      host.node.add(mesh);
      this.decor.set(node.slice("decor:".length), mesh);
    }
    this.highlight(this.selected);
    return this.bodies;
  }

  private startPick = (event: PointerEvent) => {
    this.pointerStart = event.button === 0 ? { x: event.clientX, y: event.clientY } : null;
  };

  private finishPick = (event: PointerEvent) => {
    const start = this.pointerStart;
    this.pointerStart = null;
    if (!start || event.button !== 0 || Math.hypot(event.clientX - start.x, event.clientY - start.y) > 5) return;
    const rect = this.renderer.domElement.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    this.raycaster.setFromCamera(new THREE.Vector2((event.clientX - rect.left) / rect.width * 2 - 1, -(event.clientY - rect.top) / rect.height * 2 + 1), this.camera);
    this.root.updateWorldMatrix(true, true);
    for (const hit of this.raycaster.intersectObject(this.root, true)) {
      let node: THREE.Object3D | null = hit.object;
      let visible = true;
      while (node) { if (!node.visible) visible = false; node = node.parent; }
      if (!visible) continue;
      const decoration = [...this.decor].find(([, mesh]) => mesh === hit.object);
      if (decoration) { this.onSelect?.(decoration[0]); return; }
      node = hit.object;
      while (node && node !== this.root) {
        if (this.bodies.has(node.name)) { this.onSelect?.(node.name); return; }
        node = node.parent;
      }
    }
    this.onSelect?.(null);
  };

  highlight(name: string | null) {
    this.selected = name;
    this.root.traverse(node => {
      if (!(node instanceof THREE.Mesh)) return;
      const material = node.material as THREE.MeshStandardMaterial;
      let selected = this.decor.get(name || "") === node;
      let parent: THREE.Object3D | null = node;
      while (parent && parent !== this.root) { if (parent.name === name) selected = true; parent = parent.parent; }
      material.emissive.set(selected ? 0x245ca0 : 0x000000);
      material.emissiveIntensity = selected ? 0.6 : 0;
    });
    this.needsRender = true;
  }

  setVisible(name: string, on: boolean) {
    this.needsRender = true;
    const b = this.bodies.get(name);
    if (b) {
      b.node.visible = on;
      return;
    }
    const d = this.decor.get(name);
    if (d) d.visible = on;
  }

  /** Isolate a part using the already loaded export, with no network work. */
  isolate(name: string | null): boolean {
    this.needsRender = true;
    this.root.traverse(node => { node.visible = true; });
    if (!name) return true;
    const body = this.bodies.get(name);
    const decor = this.decor.get(name);
    for (const entry of this.bodies.values()) entry.node.visible = false;
    for (const node of this.decor.values()) node.visible = false;
    if (body) {
      body.node.visible = true;
      return true;
    }
    if (decor) {
      const host = decor.parent;
      if (host) {
        host.visible = true;
        for (const child of host.children) child.visible = child === decor;
      }
      decor.visible = true;
      return true;
    }
    return false;
  }

  bounds(names?: Iterable<string>) {
    const box = new THREE.Box3();
    for (const name of names || this.bodies.keys()) {
      const b = this.bodies.get(name);
      if (b) {
        b.node.updateWorldMatrix(true, true);
        // Hidden decorations must not inflate an isolated body's dimensions.
        for (const child of b.node.children)
          if (child.visible) box.expandByObject(child);
      } else {
        const node = this.decor.get(name);
        if (node) {
          node.updateWorldMatrix(true, true);
          box.expandByObject(node);
        }
      }
    }
    return box.isEmpty() ? null : box;
  }

  sizeText(names?: Iterable<string>) {
    const box = this.bounds(names);
    if (!box) return "—";
    const s = box.getSize(new THREE.Vector3());
    const n = (v: number) => (v >= 100 ? Math.round(v) : Math.round(v * 10) / 10);
    return `${n(s.x)} × ${n(s.y)} × ${n(s.z)} mm`;
  }

  frameAll(names?: Iterable<string>, tight = false) {
    this.needsRender = true;
    const box = this.bounds(names);
    if (!box) return;
    const size = box.getSize(new THREE.Vector3());
    const centre = box.getCenter(new THREE.Vector3());
    const span = Math.max(size.x, size.y, size.z, 1);
    const reach = tight ? span * 2 / Math.min(this.camera.aspect, 1) : span * 1.6 + 200;
    this.controls.target.copy(centre);
    this.camera.position.set(
      centre.x + reach * 0.6,
      centre.y - reach,
      centre.z + reach * 0.5,
    );
    this.camera.near = tight ? Math.min(1, reach / 100) : 1;
    this.camera.far = reach * 20;
    this.camera.updateProjectionMatrix();
    this.controls.update();
  }

  setBodyTransform(
    name: string,
    p: { x: number; y: number; z: number },
    q: { x: number; y: number; z: number; w: number },
  ) {
    const b = this.bodies.get(name);
    if (!b) return;
    this.needsRender = true;
    b.node.position.set(p.x, p.y, p.z);
    b.node.quaternion.set(q.x, q.y, q.z, q.w);
  }

  resetBodies() {
    this.needsRender = true;
    for (const [, b] of this.bodies) {
      b.node.position.copy(b.homePos);
      b.node.quaternion.copy(b.homeQuat);
    }
  }

  // Arrow so it can be added/removed as an event listener; ignores a collapsed
  // (zero-size) container rather than handing the camera an Infinity aspect.
  resize = () => {
    const w = this.container.clientWidth;
    const h = this.container.clientHeight;
    if (w === 0 || h === 0) return;
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(w, h);
    this.needsRender = true;
  };

  private animate = () => {
    if (this.disposed) return;
    this.frame = requestAnimationFrame(this.animate);
    if (document.hidden || !this.container.clientWidth || !this.container.clientHeight) return;
    const moved = this.controls.update();
    if (this.needsRender || moved) {
      this.renderer.render(this.scene, this.camera);
      this.needsRender = false;
    }
  };

  dispose() {
    this.disposed = true;
    cancelAnimationFrame(this.frame);
    this.observer.disconnect();
    window.removeEventListener("resize", this.resize);
    this.renderer.domElement.removeEventListener("pointerdown", this.startPick);
    this.renderer.domElement.removeEventListener("pointerup", this.finishPick);
    this.controls.dispose();
    this.releaseModel();
    this.renderer.dispose();
    this.renderer.forceContextLoss();
    if (this.renderer.domElement.parentElement === this.container) {
      this.container.removeChild(this.renderer.domElement);
    }
  }
}
