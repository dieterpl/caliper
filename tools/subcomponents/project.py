"""Git-owned projects with named scenes and composable assembly instances.

The manifest is cad/project.json. Scene builders use build(scene, config),
explicit scene declarations, and relative imports within their project package.
"""

from copy import deepcopy
from dataclasses import dataclass, replace
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
from types import ModuleType

import catalog

from . import _vector

_BUILD = threading.local()


def record_source(node):
    frame = sys._getframe(1)
    while frame:
        path = Path(frame.f_code.co_filename).resolve()
        if "cad" in path.parts and path.name != "scene.py":
            node.source = str(path)
            break
        frame = frame.f_back
    return node


class SceneBuilder:
    """An isolated scene using the host workspace's existing record schema."""

    def __init__(self, schema):
        self.schema = schema.schema if isinstance(schema, SceneBuilder) else schema
        self.SCENE = self.schema.Scene()
        self.SCENE.interfaces = {}

    def body(self, name, part, **kw):
        node = self.schema.Body(name=name, part=part, **kw)
        self.SCENE.bodies.append(node)
        return record_source(node)

    def decor(self, name, part, parent, **kw):
        node = self.schema.Decor(name=name, part=part, parent=parent, **kw)
        self.SCENE.decor.append(node)
        return record_source(node)

    def _joint(self, type, a, b, anchor, axis=(0, 0, 1), **kw):
        anchor = _vector(anchor, "joint anchor")
        axis = _vector(axis, "joint axis")
        if not sum(v*v for v in axis):
            raise ValueError("joint axis must be nonzero")
        if a == b:
            raise ValueError("a joint must connect different bodies")
        if kw.get("limits") is not None:
            limits = kw["limits"]
            if len(limits) != 2 or limits[0] > limits[1]:
                raise ValueError("joint limits need an ordered pair")
        kw.setdefault("name", f"{a}->{b}")
        joint = self.schema.Joint(type=type, a=a, b=b, anchor=tuple(anchor),
                                  axis=tuple(axis), **kw)
        self.SCENE.joints.append(joint)
        return joint

    def revolute(self, a, b, anchor, axis=(0, 0, 1), **kw):
        return self._joint("revolute", a, b, anchor, axis, **kw)

    def prismatic(self, a, b, anchor, axis=(0, 0, 1), **kw):
        return self._joint("prismatic", a, b, anchor, axis, **kw)

    def fixed(self, a, b, anchor=(0, 0, 0)):
        return self._joint("fixed", a, b, anchor)

    def sim(self, **kw):
        unknown = set(kw) - set(self.SCENE.settings)
        if unknown:
            raise ValueError(f"unknown simulation settings: {sorted(unknown)}")
        self.SCENE.settings.update(kw)
        return self.SCENE.settings

    def __getattr__(self, name):
        if name in ("motor", "gait", "trajectory"):
            return getattr(self.schema, name)
        raise AttributeError(name)


@dataclass(frozen=True)
class Assembly:
    """Instance handles used to connect a subassembly to its parent."""

    name: str
    bodies: dict
    joints: dict
    decor: dict
    config: dict
    scene: str
    project: Path
    commit: str
    interfaces: dict


class Project:
    def __init__(self, path):
        path = Path(path).resolve()
        self.cad = path if (path / "project.json").is_file() else path / "cad"
        self.root = self.cad.parent
        manifest = self.cad / "project.json"
        if not manifest.is_file():
            raise ValueError(f"no project manifest at {manifest}; sync the submodule first")
        self.manifest = json.loads(manifest.read_text())
        if self.manifest.get("version") != 1:
            raise ValueError(f"{manifest}: supported manifest version is 1")
        self.scenes = self.manifest.get("scenes", {})
        if not isinstance(self.scenes, dict) or not self.scenes:
            raise ValueError(f"{manifest}: scenes must be a nonempty object")
        self.parameters = self.manifest.get("parameters", {})
        if not isinstance(self.parameters, dict):
            raise ValueError(f"{manifest}: parameters must be an object of defaults")
        self.default_scene = self.manifest.get("default_scene", next(iter(self.scenes)))
        if self.default_scene not in self.scenes:
            raise ValueError(f"unknown default scene {self.default_scene!r}")

    def _builder(self, entry):
        module, separator, function = entry.partition(":")
        if not separator or not re.fullmatch(r"[A-Za-z_]\w*(\.[A-Za-z_]\w*)*", module):
            raise ValueError(f"invalid scene builder {entry!r}; use module.path:build")
        if not re.fullmatch(r"[A-Za-z_]\w*", function):
            raise ValueError(f"invalid builder function {function!r}")
        # Per-project package names isolate relative imports, even when every
        # subproject has its own parts/, config.py and scenes/ modules.
        package = "_caliper_project_" + hashlib.sha256(str(self.cad).encode()).hexdigest()[:16]
        if package not in sys.modules:
            namespace = ModuleType(package)
            namespace.__path__ = [str(self.cad)]
            namespace.__package__ = package
            sys.modules[package] = namespace
        builder = getattr(importlib.import_module(f"{package}.{module}"), function)
        if not callable(builder):
            raise ValueError(f"{entry!r} is not callable")
        return builder

    def assemble(self, target, name, *, scene=None, config=None, kind="scene",
                 origin=(0, 0, 0), rotation=(0, 0, 0), overrides=None):
        """Build and merge an instance; bodies, hardware and joints get a prefix.

        Body/decor geometry is rotated in its local frame, origins and joint
        anchors are rotated and translated, and joint axes are rotated only.
        An empty name builds the top-level scene and adopts its sim settings.
        """
        from build123d import Matrix, Pos, Rot, Vector

        if not isinstance(name, str) or (name and not re.fullmatch(r"[A-Za-z0-9_-]+", name)):
            raise ValueError("assembly name must contain letters, digits, _ or -")
        definitions = {"scene": self.scenes, "component": self.manifest.get("components", {}),
                       "assembly": self.manifest.get("assemblies", {})}.get(kind)
        if definitions is None:
            raise ValueError(f"unknown definition kind {kind!r}")
        selected = scene or self.default_scene
        if selected not in definitions:
            raise ValueError(f"unknown {kind} {selected!r}; choose from {', '.join(definitions)}")
        definition = definitions[selected]
        if isinstance(definition, str):
            definition = {"builder": definition}
        if not isinstance(definition, dict):
            raise ValueError(f"{kind} {selected!r} needs a definition")
        definition = deepcopy(definition)
        if overrides:
            names = {i["name"] for i in definition.get("instances", [])}
            if set(overrides) - names:
                raise ValueError("scene override references an unknown assembly instance")
            definition["instances"] = [{**i, **deepcopy(overrides.get(i["name"], {}))} for i in definition["instances"]]
        parameters = definition.get("parameters", self.parameters if kind == "scene" else {})
        configured = {**deepcopy(parameters), **deepcopy(definition.get("config", {})),
                      **deepcopy(config or {})}
        unknown = set(configured) - set(parameters)
        if unknown:
            raise ValueError(f"unknown configuration parameters: {sorted(unknown)}")
        origin = _vector(origin, "origin")
        rotation = _vector(rotation, "rotation")
        rotate = Rot(*rotation)
        place = Pos(*origin) * rotate
        prefix = f"{name}/" if name else ""
        rename = lambda value: prefix + value
        used_start, mates_start = len(catalog.USED), len(catalog.MATES)
        stack = getattr(_BUILD, "stack", [])
        key = (str(self.root), kind, selected)
        if key in stack:
            raise ValueError(f"cyclic assembly reference to {selected!r}")
        _BUILD.stack = [*stack, key]
        try:
            local = SceneBuilder(target)
            self._build(local, definition, deepcopy(configured))
            graph = local.SCENE
            body_names = {b.name for b in graph.bodies}
            node_names = [n.name for n in (*graph.bodies, *graph.decor)]
            if len(node_names) != len(set(node_names)):
                raise ValueError("scene contains duplicate body or decor names")
            joint_names = [j.name for j in graph.joints]
            if any(not n for n in joint_names) or len(joint_names) != len(set(joint_names)):
                raise ValueError("scene needs unique joint names")
            if any(d.parent not in body_names for d in graph.decor):
                raise ValueError("scene decor references an unknown parent")
            if any(j.a not in body_names or j.b not in body_names for j in graph.joints):
                raise ValueError("scene joint references an unknown body")
            existing = {n.name for n in (*target.SCENE.bodies, *target.SCENE.decor)}
            if existing.intersection(rename(n) for n in node_names):
                raise ValueError(f"assembly {name!r} would duplicate scene nodes")
            if {j.name for j in target.SCENE.joints}.intersection(rename(n) for n in joint_names):
                raise ValueError(f"assembly {name!r} would duplicate joints")
            matrix = Matrix(place.wrapped.Transformation())
            rotation_matrix = Matrix(rotate.wrapped.Transformation())
            point = lambda value: tuple(Vector(*_vector(value, "point")).transform(matrix))
            bodies = [replace(b, name=rename(b.name), part=rotate * b.part,
                              origin=point(b.origin)) for b in graph.bodies]
            decor = [replace(d, name=rename(d.name), parent=rename(d.parent),
                             part=rotate * d.part, origin=point(d.origin)) for d in graph.decor]
            joints = [replace(j, name=rename(j.name), a=rename(j.a), b=rename(j.b),
                              anchor=point(j.anchor),
                              axis=tuple(Vector(*_vector(j.axis, "axis")).transform(rotation_matrix)))
                      for j in graph.joints]
            for original, transformed in zip([*graph.bodies, *graph.decor], [*bodies, *decor]):
                if hasattr(original, "source"):
                    transformed.source = original.source
            for usage in catalog.USED[used_start:]:
                usage.where = rename(usage.where) if usage.where else name
            for i in range(mates_start, len(catalog.MATES)):
                *pair, where = catalog.MATES[i]
                catalog.MATES[i] = (*pair, rename(where) if where else name)
        except Exception:
            del catalog.USED[used_start:]
            del catalog.MATES[mates_start:]
            raise
        finally:
            _BUILD.stack = stack
        target.SCENE.bodies.extend(bodies)
        target.SCENE.decor.extend(decor)
        target.SCENE.joints.extend(joints)
        interfaces = {rename(key): {"body": rename(value["body"]),
                       "anchor": point(value["anchor"]),
                       "axis": tuple(Vector(*_vector(value["axis"], "interface axis")).transform(rotation_matrix))}
                      for key, value in graph.interfaces.items()}
        if not hasattr(target.SCENE, "interfaces"):
            target.SCENE.interfaces = {}
        target.SCENE.interfaces.update(interfaces)
        if not name:
            target.SCENE.settings.update(graph.settings)
        revision = subprocess.run(["git", "-C", str(self.root), "rev-parse", "HEAD"],
                                  capture_output=True, text=True)
        return Assembly(name, {b.name: rename(b.name) for b in graph.bodies},
                        {j.name: rename(j.name) for j in graph.joints},
                        {d.name: rename(d.name) for d in graph.decor}, configured,
                        selected, self.root, revision.stdout.strip() if revision.returncode == 0 else "", interfaces)

    def _build(self, scene, definition, config):
        from build123d import Box, Pos

        if "builder" in definition:
            self._builder(definition["builder"])(scene, config)
        elif "hardware" in definition:
            from subcomponents import get
            component = get(definition["hardware"])
            scene.body("part", component.solid(), mass=component.entry.mass, group="hardware",
                       color=definition.get("color", "#64748b"))
            catalog.use(component.entry.id, where="part")
        elif "legacy_part" in definition:
            from .editor import original_part
            original_part(scene, self.cad, definition["legacy_part"], config)
        elif "assembly" in definition:
            self.assemble(scene, "assembly", scene=definition["assembly"], kind="assembly", config=config, overrides=definition.get("overrides"))
        elif "instances" in definition:
            for instance in definition["instances"]:
                def resolve(value):
                    if isinstance(value, dict) and set(value) == {"parameter"}:
                        if value["parameter"] not in config:
                            raise ValueError("unknown assembly parameter reference")
                        return config[value["parameter"]]
                    if isinstance(value, dict):
                        return {k: resolve(v) for k,v in value.items()}
                    if isinstance(value, list):
                        return [resolve(v) for v in value]
                    return value
                instance = resolve(instance)
                options = {"origin": instance.get("origin", (0, 0, 0)),
                           "rotation": instance.get("rotation", (0, 0, 0)),
                           "config": instance.get("config", {})}
                if "project" in instance:
                    dependency = instance["project"]
                    if not re.fullmatch(r"[A-Za-z0-9_-]+", dependency):
                        raise ValueError("invalid subproject name")
                    child = Project(self.cad / "kits" / dependency)
                    child.assemble(scene, instance["name"], scene=instance.get("scene"),
                                   kind=instance.get("kind", "scene"), **options)
                else:
                    kind = "component" if "component" in instance else "assembly"
                    selected = instance.get(kind)
                    if not selected:
                        raise ValueError("each instance needs a component, assembly or project")
                    self.assemble(scene, instance["name"], kind=kind, scene=selected, **options)
            for joint in definition.get("joints", []):
                values = dict(joint)
                type = values.pop("type")
                primary_interface = str(values.get("a", "")).startswith("@")
                for side in ("a", "b"):
                    reference = values.get(side, "")
                    if reference.startswith("@"):
                        interface = scene.SCENE.interfaces.get(reference[1:])
                        if not interface:
                            raise ValueError(f"unknown connection interface {reference!r}")
                        values[side] = interface["body"]
                        if side == "a" or not primary_interface:
                            values["anchor"] = interface["anchor"]
                            values["axis"] = interface["axis"]
                if type not in ("revolute", "prismatic", "fixed"):
                    raise ValueError(f"unsupported joint type {type!r}")
                scene._joint(type, **values)
        else:
            raise ValueError("definition needs a builder, hardware, legacy part, assembly or instances")
        for name, interface in definition.get("interfaces", {}).items():
            if interface["body"] not in {b.name for b in scene.SCENE.bodies}:
                raise ValueError(f"interface {name!r} references an unknown body")
            axis = _vector(interface.get("axis", (0,0,1)), "interface axis")
            if not sum(v*v for v in axis):
                raise ValueError("interface axis must be nonzero")
            scene.SCENE.interfaces[name] = {"body": interface["body"],
                "anchor": _vector(interface.get("anchor", (0,0,0)), "interface anchor"), "axis": axis}
        scene.sim(**definition.get("settings", {}))
        environment = definition.get("environment", {})
        if environment.get("ground"):
            size = environment.get("size", 2000)
            if size <= 0:
                raise ValueError("ground size must be positive")
            scene.body("environment_floor", Pos(0, 0, -5) * Box(size, size, 10),
                       type="fixed", mass=1, group="environment", color="#1e293b")

def load_scene(scene, model_file):
    """Root cad/model.py entry point; selection comes from caliper's CLI."""
    project = Project(Path(model_file).resolve().parent)
    assembly = project.assemble(
        scene, "", scene=os.environ.get("CALIPER_SCENE") or project.manifest.get("active_scene"),
        config=json.loads(os.environ.get("CALIPER_CONFIG", "{}")))
    scene.SCENE.project = {"scene": assembly.scene, "config": assembly.config,
                           "commit": assembly.commit}
    return assembly
