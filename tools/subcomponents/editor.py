"""Real CAD discovery, legacy project adoption, and isolated preview exports."""

from copy import copy, deepcopy
import importlib.util
import fcntl
import json
import os
from pathlib import Path
import pkgutil
import runpy
import shutil
import sys
import tempfile
from types import ModuleType

import catalog
from .project import Project, SceneBuilder

_ORIGINAL = {}


def build_original(target, cad, config=None):
    """Reuse the original model without leaking its config/parts/scene modules."""
    cad = Path(cad).resolve()
    key = str(cad)
    if key not in _ORIGINAL:
        local = SceneBuilder(target)
        bases = {module.name for module in pkgutil.iter_modules([str(cad)])} | {"scene"}
        owned = lambda name: name.split(".")[0] in bases
        previous = {name: module for name, module in sys.modules.items() if owned(name)}
        for name in previous:
            sys.modules.pop(name, None)
        proxy = ModuleType("scene")
        proxy.__dict__.update(vars(local.schema))
        for name in ("body", "decor", "revolute", "prismatic", "fixed", "sim", "motor", "gait", "trajectory"):
            setattr(proxy, name, getattr(local, name))
        proxy.SCENE = local.SCENE
        sys.modules["scene"] = proxy
        sys.path.insert(0, str(cad))
        start, mates = len(catalog.USED), len(catalog.MATES)
        original_use = catalog.use
        def traced_use(*args, **kwargs):
            entry = original_use(*args, **kwargs)
            owners = set()
            frame = sys._getframe(1)
            while frame:
                source = Path(frame.f_code.co_filename).resolve()
                if source.is_relative_to(cad):
                    candidate = frame.f_locals.get("name")
                    if isinstance(candidate, str):
                        owners.add(candidate)
                    owners.add(frame.f_code.co_name)
                frame = frame.f_back
            catalog.USED[-1].owners = owners
            return entry
        catalog.use = traced_use
        try:
            source = cad / "legacy_model.py"
            runpy.run_path(str(source if source.is_file() else cad / "model.py"))
            _ORIGINAL[key] = (local.SCENE, [copy(u) for u in catalog.USED[start:]],
                              list(catalog.MATES[mates:]))
        finally:
            catalog.use = original_use
            del catalog.USED[start:]
            del catalog.MATES[mates:]
            sys.path.remove(str(cad))
            for name in list(sys.modules):
                if owned(name):
                    sys.modules.pop(name, None)
            sys.modules.update(previous)
    graph, usage, mates = _ORIGINAL[key]
    target.SCENE.bodies.extend(copy(n) for n in graph.bodies)
    target.SCENE.decor.extend(copy(n) for n in graph.decor)
    target.SCENE.joints.extend(deepcopy(n) for n in graph.joints)
    target.SCENE.settings.update(graph.settings)
    catalog.USED.extend(copy(u) for u in usage)
    catalog.MATES.extend(mates)
    out = cad.parent / "out"
    out.mkdir(exist_ok=True)
    (out / "original-index.json").write_text(json.dumps(index(graph, cad.parent), indent=2))


def original_part(target, cad, name, config=None):
    local = SceneBuilder(target)
    start, mates = len(catalog.USED), len(catalog.MATES)
    try:
        build_original(local, cad)
    finally:
        del catalog.USED[start:]
        del catalog.MATES[mates:]
    original = next((n for n in [*local.SCENE.bodies, *local.SCENE.decor] if n.name == name), None)
    if original is None:
        raise ValueError(f"original model has no part {name!r}")
    scale = (config or {}).get("scale", 1)
    if scale <= 0:
        raise ValueError("scale must be positive")
    part = original.part if scale == 1 else original.part.scale(scale)
    node = target.body("part", part, mass=max(original.mass, 0.001) * scale ** 3,
                       color=original.color, group=original.group)
    node.source = getattr(original, "source", "")


def index(graph, root):
    root = Path(root)
    nodes = []
    jointed = {name for joint in graph.joints for name in (joint.a, joint.b)}
    for node in [*graph.bodies, *graph.decor]:
        source = getattr(node, "source", "")
        try:
            source = str(Path(source).relative_to(root)) if source else ""
        except ValueError:
            source = ""
        size = node.part.bounding_box().size
        nodes.append({"name": node.name, "source": source, "group": node.group,
                      "origin": list(node.origin), "size": [size.X, size.Y, size.Z],
                      "kind": "decor" if hasattr(node, "parent") else "body",
                      "type": getattr(node, "type", None), "jointed": node.name in jointed,
                      "mass": node.mass, "parent": getattr(node, "parent", None)})
    return {"nodes": nodes}


def export_graph(schema, graph, cad, destination, metadata=None):
    """Export to a staging directory; failed CAD builds preserve prior artifacts."""
    cad, destination = Path(cad), Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".project-build-", dir=destination.parent))
    spec = importlib.util.spec_from_file_location("_caliper_project_export", cad / "export.py")
    exporter = importlib.util.module_from_spec(spec)
    previous, model = schema.SCENE, sys.modules.get("model")
    try:
        spec.loader.exec_module(exporter)
        exporter.OUT = stage
        schema.SCENE = graph
        sys.modules["model"] = ModuleType("model")
        if exporter.main():
            raise ValueError("CAD export failed")
        scene_path = stage / "scene.json"
        data = json.loads(scene_path.read_text())
        if hasattr(graph, "project"):
            data["project"] = graph.project
        data["interfaces"] = getattr(graph, "interfaces", {})
        if metadata:
            data["definition"] = metadata
        node_index = index(graph, cad.parent)
        sources = {n["name"]: n["source"] for n in node_index["nodes"]}
        for node in [*data["bodies"], *data.get("decor", [])]:
            node["source"] = sources.get(node["name"], "")
        scene_path.write_text(json.dumps(data, indent=2))
        (stage / "project-index.json").write_text(json.dumps(node_index, indent=2))
        destination.mkdir(parents=True, exist_ok=True)
        # scene.json is published last, after the geometry it describes.
        for file in [p for p in stage.iterdir() if p.name != "scene.json"]:
            os.replace(file, destination / file.name)
        os.replace(scene_path, destination / "scene.json")
    finally:
        schema.SCENE = previous
        if model is None:
            sys.modules.pop("model", None)
        else:
            sys.modules["model"] = model
        shutil.rmtree(stage, ignore_errors=True)


def _run(cad, action, kind="scene", name=None, destination=None, configuration=None):
    cad = Path(cad).resolve()
    sys.path.insert(0, str(cad))
    import scene
    local = SceneBuilder(scene)
    if action == "discover":
        build_original(local, cad)
        out = cad.parent / "out"
        out.mkdir(exist_ok=True)
        (out / "original-index.json").write_text(json.dumps(index(local.SCENE, cad.parent), indent=2))
        return
    if (cad / "project.json").is_file():
        project = Project(cad)
        selected = name or os.environ.get("CALIPER_SCENE") or project.manifest.get("active_scene") or project.default_scene
        assembly = project.assemble(local, "", kind=kind, scene=selected,
                                    config=configuration or json.loads(os.environ.get("CALIPER_CONFIG", "{}")))
        local.SCENE.project = {"scene": assembly.scene, "config": assembly.config, "commit": assembly.commit}
    else:
        if action == "export":
            build_original(local, cad)
        else:
            original_part(local, cad, name)
    if not local.SCENE.bodies:
        raise ValueError("add a subcomponent instance before building this assembly")
    export_graph(scene, local.SCENE, cad, destination or cad.parent / "out",
                 {"kind": kind, "name": name})


def run(cad, action, **kwargs):
    cad = Path(cad).resolve()
    out = cad.parent / "out"
    out.mkdir(exist_ok=True)
    # Serializes watcher and HTTP exports without locking isolated previews.
    if action == "export":
        with (out / ".project-export.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            return _run(cad, action, **kwargs)
    return _run(cad, action, **kwargs)


def original_assembly(target, cad, bodies, origin=(0, 0, 0), prefix=""):
    """Extract a reusable subassembly with its fittings, internal joints and BOM."""
    local = SceneBuilder(target)
    start, mates = len(catalog.USED), len(catalog.MATES)
    build_original(local, cad)
    selected = set(bodies)
    if selected - {b.name for b in local.SCENE.bodies}:
        del catalog.USED[start:]; del catalog.MATES[mates:]
        raise ValueError("subassembly references a missing original body")
    rename = lambda name: name.removeprefix(prefix) if prefix else name
    shift = lambda vector: tuple(a-b for a,b in zip(vector, origin))
    for original in local.SCENE.bodies:
        if original.name in selected:
            node = copy(original); node.name = rename(node.name); node.origin = shift(node.origin)
            target.SCENE.bodies.append(node)
    fittings = set()
    for original in local.SCENE.decor:
        if original.parent in selected:
            node = copy(original); fittings.add(node.name); node.name = rename(node.name)
            node.parent = rename(node.parent); node.origin = shift(node.origin)
            target.SCENE.decor.append(node)
    for original in local.SCENE.joints:
        if original.a in selected and original.b in selected:
            node = deepcopy(original); node.name = rename(node.name)
            node.a = rename(node.a); node.b = rename(node.b); node.anchor = shift(node.anchor)
            target.SCENE.joints.append(node)
    def belongs(usage):
        return usage.where in selected | fittings or any(
            node == owner or node.startswith(owner + "_") or node.startswith(owner + "/")
            for owner in getattr(usage, "owners", ()) for node in selected)
    usage = [u for u in catalog.USED[start:] if belongs(u)]
    del catalog.USED[start:]; del catalog.MATES[mates:]
    for item in usage:
        item.where = rename(item.where)
    catalog.USED.extend(usage)
