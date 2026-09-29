# Reusable projects, components and scenes

A reusable subproject is an ordinary Git repository. It owns its components,
subassembly builders, named scenes and configuration presets. A parent includes
it at `cad/kits/<name>` as a Git submodule; the parent's commit records the exact
child commit. The library does not copy a child's geometry into the parent.

The implementation has three layers:

1. `catalog` owns hardware dimensions, provenance, mass and buying information.
2. `subcomponents` provides shared hardware geometry and explicit scene attachment.
3. `subcomponents.project` builds a project's named scenes and merges configured
   assembly instances into a parent scene, with independent names and placements.

The first implementation includes motor, controller and pulley proxies, existing
bearing geometry, isolated project imports, nested subassemblies, scene selection,
configuration overrides and Git-pinned example projects. Existing single-model
workspaces still work without a manifest.

## What a subproject owns

```text
leg/                         independent Git repository
  cad/
    project.json             named scenes and committed configuration presets
    model.py                 standalone scene entry point
    scene.py                 workspace physics record schema
    export.py, watch.py       ordinary caliper exporter and watcher
    parts/links.py           reusable link subassembly builder
    scenes/leg.py            assembled and links-only scene builders
    kits/                    optional dependencies, themselves Git submodules
```

For example, `cad/project.json`:

```json
{
  "version": 1,
  "default_scene": "assembled",
  "parameters": {"length": 110, "radius": 10, "side": 1},
  "scenes": {
    "assembled": "scenes.leg:assembled",
    "links_only": "scenes.leg:links_only",
    "long": {"builder": "scenes.leg:assembled", "config": {"length": 150}}
  }
}
```

Every entry points to a function `build(scene, config)` (the function may have
another name). Builders declare geometry into the **provided** scene, and use
relative imports for their own modules: `from ..parts.links import links`.
Projects get separate Python package namespaces, so two projects can each own
`parts/`, `config.py` and `scenes/` without shadowing one another. Import modules
without assembling anything; perform all scene and BOM declarations inside
builder functions. Builders validate their own parameter values. Unknown
configuration keys are rejected by the library.

The root `cad/model.py` selects and builds one scene:

```python
import scene
from subcomponents.project import load_scene

load_scene(scene, __file__)
```

Use the current template exporter and watcher when adopting named scenes. The
exporter records the chosen scene, configuration and project commit in
`out/scene.json`; the watcher rebuilds on `project.json` changes as well as Python
changes. Exported artifacts remain generated files, outside Git.

## Compose several instances

Inside the parent's scene builder:

```python
from pathlib import Path
from subcomponents.project import Project

def build(scene, config):
    # Declare the chassis first; omitted here for brevity.
    leg = Project(Path(__file__).resolve().parents[1] / "kits/leg")
    left = leg.assemble(scene, "left", scene="assembled",
                        config={"length": 125, "side": 1},
                        origin=(80, 65, 265))
    right = leg.assemble(scene, "right", scene="long",
                         config={"side": -1}, origin=(80, -65, 315),
                         rotation=(0, 0, 180))
    scene.fixed("chassis", left.bodies["mount"], anchor=(80, 65, 265))
    scene.fixed("chassis", right.bodies["mount"], anchor=(80, -65, 315))
```

The resulting names include `left/thigh`, `right/thigh`, `left/hip` and
`right/hip`. The returned `Assembly` maps local body, decor and joint names to
their parent-scene names; it also records the resolved configuration and child
commit. Parents use those handles to connect subassemblies together.

Rotation uses build123d Euler angles in **degrees**. Body and decor shapes rotate
around their own local origins; their origins and joint anchors rotate and
translate into the assembly's placement. Joint axes rotate without translating.
Joint limits, servos and drives are preserved. Subassemblies can recursively
include other projects. The root scene owns simulation settings; nested scene
settings do not replace the parent's settings.

Building occurs in a temporary scene. Missing references, duplicate instance
names and failed child builders leave the target scene and BOM unchanged.
Hardware usage locations receive the same instance prefix as the scene nodes.

## Shared hardware

```python
from subcomponents import along_y, get

motor = get("motor/MN5008")
shape = motor.solid(rotation=along_y(-1))  # local geometry, no BOM side effects
pocket = motor.cutter({"HARDWARE_CLEARANCE": 0.3})
occupied = motor.envelope()
motor.attach(scene, "hip_motor", "mount", origin=(0, 35, 0),
             rotation=along_y(-1), group="motors")
```

`attach` declares decor with catalogue mass and records one BOM unit. The parent
body must already exist. Do not also call `catalog.use` for the same placement.
If a motor should itself be a rigid body, use `scene.body` with `motor.solid()`
and explicitly call `catalog.use` instead.

Geometry is centered at the origin, with motor output and pulley axes along +Z.
`along_x` and `along_y` return rotation tuples for the component API. Shapes are
cached: use build123d location multiplication to produce placed copies; do not
mutate a returned shape. The public `bldc_motor`, `driver_board` and
`timing_pulley` builders also accept explicit dimensions for custom geometry.

Motor and board cutters reserve their whole envelopes with a caller-supplied
gap, defaulting to 0.2 mm. They are clearance pockets, not bolt-hole patterns.
Pulley envelopes reserve shaft space as well as the flanges. Bearing cutters
retain their existing printer-fit behavior. Catalogue lookup remains available
without loading build123d:

```bash
caliper parts --geometry
caliper parts --show motor/MN5008
```

These shapes are assembly proxies. They omit motor mounting patterns and real
pulley tooth profiles; they are not manufacturing drawings. Catalogue dimension
provenance remains unchanged, including the estimated GB36-1 dimensions.

## Try the Git-owned quad and leg examples

From the caliper checkout, create **new** sibling design repositories:

```bash
CALIPER_APP="$PWD"
CALIPER_DEMO="$(mktemp -d)"
mkdir "$CALIPER_DEMO/leg" "$CALIPER_DEMO/quad"
cp -a "$CALIPER_APP/template/." "$CALIPER_DEMO/leg/"
cp -a "$CALIPER_APP/template/." "$CALIPER_DEMO/quad/"
cp -a "$CALIPER_APP/examples/leg-project/cad/." "$CALIPER_DEMO/leg/cad/"
cp -a "$CALIPER_APP/examples/quad-project/cad/." "$CALIPER_DEMO/quad/cad/"
git -C "$CALIPER_DEMO/leg" init
git -C "$CALIPER_DEMO/leg" add .
git -C "$CALIPER_DEMO/leg" commit -m 'reusable leg with three scenes'
git -C "$CALIPER_DEMO/quad" init
git -C "$CALIPER_DEMO/quad" add .
git -C "$CALIPER_DEMO/quad" commit -m 'quad assembly scenes'
cd "$CALIPER_DEMO/quad"
"$CALIPER_APP/bin/caliper" sub add leg
git commit -m 'pin reusable leg project'
"$CALIPER_APP/bin/caliper" scenes
"$CALIPER_APP/bin/caliper" export --scene wide --set length=125
"$CALIPER_APP/bin/caliper" bom --scene wide --set length=125
"$CALIPER_APP/bin/caliper" export --scene links_only
```

The quad owns `assembled`, `wide` and `links_only` scenes. Each composes four
instances of the leg project. The leg owns `assembled`, `links_only` and `long`
scenes. The example exercises reuse and scene composition; its simple links and
motor proxies are not a finished robot design.

Scene flags work with export, watch, render, measurement, BOM and bundle commands
because they select what `model.py` builds. For a watcher, pass the selection
when starting `caliper watch`. Outputs use the existing `out/` directory, so
exporting a different scene replaces the displayed artifacts. Bundles rebuild
from the requested scene; bundling a GLB requires a matching prior export.
Commands that only consume exported artifacts, such as headless simulation,
require exporting the desired scene first.

Use CLI overrides for experiments. To **track** a configuration, commit its
defaults or preset in `project.json`, or the parent's assembly builder. The
parent's Git submodule pin and committed configuration together reproduce the
assembly. After cloning, run `caliper sub sync`; inspect `caliper sub status`
before updating a child pin. Commit component and scene changes in the child
repository, then stage `cad/kits/leg` and commit the new pin in the parent.

The web workbench continues to display the exported scene through the existing
viewer. Scene selection in this implementation is through the CLI and committed
manifest, rather than a new browser control.

## Verification

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Tests exercise shared geometry, mirrored placement, clearance containment,
independent imports and scenes, configuration overrides, nested joint graphs,
atomic failures, Git submodule pinning and cloning, and actual STEP/GLB exports
and BOM output for the selected scene.

## Project library in the browser

Open **Project library** from a workspace, or navigate to
`/#/ws/<project>/project`. The left rail lists reusable subcomponents, assemblies,
scenes and included Git projects. Selecting a definition builds a real isolated
CAD preview; it does not replace the workbench's active scene.

Use **Enable project library** to adopt an older design. Its `model.py` is
preserved as `legacy_model.py`, and its complete original model remains a named
scene. Existing bodies and fittings become selectable component definitions with
source locations and a uniform scale parameter. Generated geometry is a preview;
the editable geometry stays in Python.

Create parts from a box, cylinder, parameterized motor or geometry-backed hardware
catalogue entry. Edit dimensions in the inspector or open **Source** to modify the
owning Python builder. **Save & build** persists a definition and rebuilds its
preview. CAD errors appear below the preview, and the previous successful
artifacts remain available. A failed source build leaves the source on disk so it
can be corrected; a failed definition build restores the previous manifest.

Assemblies contain named instances of components, other assemblies or a pinned
child project's scene. Each instance has a position, Euler rotation in degrees
and independent configuration. Add internal joints after building the instances.
Named connection interfaces expose a body, anchor and axis; a parent joint can
reference `@instance/interface` in place of a body. The parent uses that interface's
transformed anchor and axis.

Scenes can reference an assembly and store `overrides` keyed by instance name.
The UI edits placement and component configuration without changing the shared
assembly. Scene environment and simulation settings are persisted too.
**Activate scene** rebuilds the normal workspace model and selects that scene for
CLI export, BOM and simulation. The original scene is always available after
adoption.

**Git** shows the current owning repository's branch, revision and actual changes.
Commit a child's definitions in that child's view, stage its updated pin in the
parent, then commit the parent. To include a sibling project, enable its library
and commit its definitions first. Included projects open their own library and
source inspector. Preview directories live under ignored `out/`.

The React implementation uses shared field, instance, connection, source, preview,
creation and repository components in `web/src/components/project/`.
