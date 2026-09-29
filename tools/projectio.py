"""Project-library metadata and file updates. No CAD kernel in the web process."""

from copy import deepcopy
import configparser
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess

NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def read(path, default=None):
    return json.loads(path.read_text()) if path.is_file() else deepcopy(default)


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")
    os.replace(temporary, path)


def project_root(workspace, relative=""):
    workspace = workspace.resolve()
    if relative and not re.fullmatch(r"cad/kits/[a-z0-9][a-z0-9_-]*(?:/cad/kits/[a-z0-9][a-z0-9_-]*)*", relative):
        raise ValueError("invalid subproject path")
    root = (workspace / relative).resolve()
    if not root.is_relative_to(workspace) or not (root / "cad").is_dir():
        raise ValueError("subproject is missing; sync its Git submodule first")
    return root


def git(root, *args, check=False):
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    if check and result.returncode:
        raise ValueError(result.stderr.strip())
    return result.stdout.strip() if result.returncode == 0 else ""


def identifier(label):
    value = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")[:50]
    if not value or not NAME.fullmatch(value):
        raise ValueError("name must contain letters or numbers")
    return value


def revision(root):
    path = root / "cad/project.json"
    return hashlib.sha256(path.read_bytes() if path.is_file() else b"legacy").hexdigest()


def legacy_components(root):
    data = read(root / "out/original-index.json", None)
    if data:
        nodes = data["nodes"]
        own = [n for n in nodes if n.get("type") != "fixed" or n.get("jointed")]
        nodes = own or nodes
    else:
        scene = read(root / "out/scene.json", {"bodies": [], "joints": [], "decor": []})
        jointed = {name for j in scene.get("joints", []) for name in (j["a"], j["b"])}
        bodies = [b for b in scene["bodies"] if b.get("type") != "fixed" or b["name"] in jointed]
        nodes = [*(bodies or scene["bodies"]), *scene.get("decor", [])]
    definitions = {}
    for node in nodes:
        if node.get("group") == "environment":
            continue
        name = identifier(node["name"])
        while name in definitions:
            name += "_2"
        definitions[name] = {"label": node["name"], "legacy_part": node["name"],
                             "parameters": {"scale": 1.0}, "source": node.get("source", ""),
                             "group": node.get("group", "parts")}
    return definitions


def manifest(root):
    return read(root / "cad/project.json", {
        "version": 1, "default_scene": "original", "active_scene": "original",
        "parameters": {}, "components": legacy_components(root), "assemblies": {},
        "scenes": {"original": {"label": "Original model", "builder": "scenes.original:build"}},
    })


def dependencies(root):
    parser = configparser.ConfigParser()
    parser.read(root / ".gitmodules")
    rows = []
    for section in parser.sections():
        relative = parser.get(section, "path", fallback="")
        if not re.fullmatch(r"cad/kits/[a-z0-9][a-z0-9_-]*", relative):
            continue
        child = root / relative
        present = (child / ".git").exists()
        recorded = git(root, "ls-tree", "HEAD", "--", relative).split()
        rows.append({"name": Path(relative).name, "path": relative,
                     "url": parser.get(section, "url", fallback=""), "present": present,
                     "commit": git(child, "rev-parse", "HEAD") if present else "",
                     "pinned": recorded[2] if len(recorded) > 2 else "",
                     "dirty": bool(git(child, "status", "--porcelain")) if present else False,
                     "scenes": manifest(child).get("scenes", {}) if present else {}})
    return rows


def state(workspace, relative=""):
    root = project_root(workspace, relative)
    data = manifest(root)
    original = {n["name"]: n for n in read(root / "out/original-index.json", {"nodes": []})["nodes"]}
    for definition in data.get("components", {}).values():
        if isinstance(definition, dict) and definition.get("legacy_part") in original:
            definition["source"] = original[definition["legacy_part"]].get("source", "")
        if isinstance(definition, dict) and "builder" in definition and not definition.get("source"):
            definition["source"] = "cad/" + definition["builder"].split(":")[0].replace(".", "/") + ".py"
    sources = [str(file.relative_to(workspace)) for file in (root / "cad").rglob("*.py")
               if "__pycache__" not in file.parts and "kits" not in file.relative_to(root).parts]
    import catalog
    hardware = [{"id": p.id, "mass": p.mass, "provenance": p.provenance}
                for p in catalog.all_parts() if p.solid is not None]
    return {"project": relative, "name": root.name, "manifest": data,
            "initialized": (root / "cad/project.json").is_file(), "revision": revision(root),
            "git": {"branch": git(root, "branch", "--show-current") or "detached",
                    "commit": git(root, "rev-parse", "HEAD"),
                    "changes": git(root, "status", "--porcelain").splitlines()},
            "dependencies": dependencies(root), "sources": sorted(sources), "hardware": hardware}


def upgrade(root, app):
    cad = root / "cad"
    if (cad / "project.json").is_file():
        return manifest(root)
    if (cad / "legacy_model.py").exists():
        raise ValueError("legacy_model.py already exists; preserve it elsewhere before adoption")
    data = manifest(root)
    shutil.copyfile(cad / "model.py", cad / "legacy_model.py")
    (cad / "scenes").mkdir(exist_ok=True)
    (cad / "scenes/original.py").write_text(
        'from pathlib import Path\nfrom subcomponents.editor import build_original\n\n'
        'def build(scene, config):\n'
        '    build_original(scene, Path(__file__).resolve().parents[1], config)\n')
    write(cad / "project.json", data)
    (cad / "model.py").write_text(
        'import scene\nfrom subcomponents.project import load_scene\n\n'
        'load_scene(scene, __file__)\n')
    # Preserve the existing watcher before adopting manifest-aware rebuilds.
    if (cad / "watch.py").is_file():
        shutil.copyfile(cad / "watch.py", cad / "watch.py.bak")
    shutil.copyfile(app / "template/cad/watch.py", cad / "watch.py")
    return data


def validate(data, root):
    json.dumps(data, allow_nan=False)
    if not isinstance(data, dict):
        raise ValueError("manifest must be an object")
    components = data.get("components", {})
    assemblies = data.get("assemblies", {})
    scenes = data.get("scenes", {})
    if not all(isinstance(value, dict) for value in (components, assemblies, scenes)):
        raise ValueError("definition libraries must be objects")
    if data.get("version") != 1 or not scenes:
        raise ValueError("a project needs version 1 and at least one scene")
    active = data.get("active_scene", data.get("default_scene"))
    if active not in scenes or data.get("default_scene") not in scenes:
        raise ValueError("the default and active scenes must exist")
    graph = {}
    for kind, definitions in (("component", components), ("assembly", assemblies), ("scene", scenes)):
        for name, value in definitions.items():
            if not NAME.fullmatch(name):
                raise ValueError(f"invalid {kind} id {name!r}")
            if isinstance(value, str):
                continue
            if not isinstance(value, dict):
                raise ValueError("definitions must be objects or Python builders")
            if sum(key in value for key in ("builder", "hardware", "legacy_part", "assembly", "instances")) != 1:
                raise ValueError("a definition needs exactly one builder or composition")
            if not isinstance(value.get("parameters", {}), dict) or not isinstance(value.get("config", {}), dict):
                raise ValueError("parameters and configuration must be objects")
            if not isinstance(value.get("instances", []), list):
                raise ValueError("instances must be an array")
            refs = []
            if "assembly" in value:
                if value["assembly"] not in assemblies:
                    raise ValueError("scene references a missing assembly")
                refs.append(("assembly", value["assembly"]))
            names = set()
            for instance in value.get("instances", []):
                if not isinstance(instance, dict):
                    raise ValueError("an instance must be an object")
                instance_name = instance.get("name", "")
                if not NAME.fullmatch(instance_name) or instance_name in names:
                    raise ValueError("instance names must be valid and unique")
                names.add(instance_name)
                reference_keys = [key for key in ("component", "assembly", "project") if key in instance]
                if len(reference_keys) != 1:
                    raise ValueError("an instance must reference one subcomponent, assembly or project")
                key = reference_keys[0]
                if key == "project":
                    dependency = instance[key]
                    if not NAME.fullmatch(dependency) or not (root / "cad/kits" / dependency / "cad").is_dir():
                        raise ValueError("instance references a missing subproject")
                else:
                    if instance[key] not in (components if key == "component" else assemblies):
                        raise ValueError("instance references a missing definition")
                    refs.append((key, instance[key]))
                for key in ("origin", "rotation"):
                    vector = instance.get(key, [0, 0, 0])
                    if not isinstance(vector, (list, tuple)) or len(vector) != 3 or not all(isinstance(n, (float, int)) and math.isfinite(n) for n in vector):
                        raise ValueError("positions and rotations need three finite numbers")
            graph[(kind, name)] = refs
    def visit(key, ancestors):
        if key in ancestors:
            raise ValueError("cyclic subassembly references are not allowed")
        for ref in graph.get(key, []):
            visit(ref, ancestors | {key})
    for key in graph:
        visit(key, set())


def new_component(root, data, label, recipe, hardware=None):
    name = identifier(label)
    if name in data.setdefault("components", {}):
        raise ValueError("a subcomponent with that name already exists")
    recipes = {
        "box": ({"length": 40, "width": 30, "height": 20}, 'Box(config["length"], config["width"], config["height"])'),
        "cylinder": ({"radius": 12, "height": 30}, 'Cylinder(config["radius"], config["height"])'),
        "motor": ({"diameter": 55.6, "length": 27, "shaft_diameter": 6, "shaft_length": 8},
                  'bldc_motor(config["diameter"], config["length"], config["shaft_diameter"], config["shaft_length"])'),
    }
    if recipe == "hardware":
        import catalog
        entry = catalog.get(hardware)
        if entry.solid is None:
            raise ValueError("that catalogue item has no reusable geometry")
        parameters = {}
        source = (f'from subcomponents import get\nfrom catalog import use\n\n'
                  f'def build(scene, config):\n    component = get({hardware!r})\n'
                  '    scene.body("part", component.solid(), mass=component.entry.mass, color="#64748b")\n'
                  f'    use({hardware!r}, where="part")\n')
    elif recipe in recipes:
        parameters, expression = recipes[recipe]
        source = ('from build123d import Box, Cylinder\nfrom subcomponents import bldc_motor\n\n'
                  'def build(scene, config):\n'
                  '    if any(value <= 0 for value in config.values()):\n'
                  '        raise ValueError("dimensions must be positive")\n'
                  f'    shape = {expression}\n'
                  '    scene.body("part", shape, mass=0.1, color="#94a3b8")\n')
    else:
        raise ValueError("unknown subcomponent recipe")
    path = root / "cad/components" / f"{name}.py"
    if not path.resolve().is_relative_to(root.resolve()) or path.exists():
        raise ValueError("component source path already exists or escapes the project")
    path.parent.mkdir(exist_ok=True)
    path.write_text(source)
    data["components"][name] = {"label": label, "builder": f"components.{name}:build",
                               "parameters": parameters, "source": f"cad/components/{name}.py"}
    return name
