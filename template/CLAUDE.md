# This design

You are inside one design. This folder is a git repository holding a single
thing — a bracket, an enclosure, a lamp, a machine that walks: its CAD model,
its built artifacts, and its history. Everything you change here affects only
this design; other workspaces are other folders.

It is seeded with a worked example — a four-legged stander, jointed and
servo-driven, because that exercises every part of the DSL. **It is a starting
point, not the subject.** If you were asked for a fan bracket, delete the legs.

```
cad/config.py      every dimension, mass, gain — a proportion change is one line here
cad/model.py       assembly order only: what the design is made of
cad/parts/*.py     the geometry, one module per sub-assembly
cad/scene.py       the CAD -> physics DSL (only edit to extend the DSL itself)
cad/printing.py    everything that exists because a part gets printed
out/               built artifacts — never edit, never commit (gitignored)
```

Joints, motors and gaits are **optional**. A design that does not move declares
bodies and stops there; the app notices and puts its simulation controls away.

The tools are **not** in this folder. They live in the image and are reached
through one command, `caliper`, which works from anywhere inside the workspace.

## The loop

Reusable hardware lives in `subcomponents`, backed by `catalog`:
`get("motor/MN5008").attach(scene, "motor", "parent_body")` declares hardware,
mass and one BOM unit. `caliper parts --geometry` lists shared solids.

For a reusable project, commit `cad/project.json` with named scene builders
(`build(scene, config)`) and configuration defaults. Builders use the provided
scene and relative project imports. `subcomponents.project.Project` assembles
configured, namespaced instances from Git submodules under `cad/kits/`.
The root `model.py` calls `load_scene(scene, __file__)`. Use `caliper scenes`
and `caliper export --scene NAME --set KEY=JSON` to select a scene. Track stable
configurations in the manifest and child versions through parent submodule pins.
Existing models without a manifest keep their usual assembly code.

A watcher process is already running. When you save anything under `cad/`, it
re-exports `out/` about a quarter second later, and the browser viewport reloads
itself. You do not need to tell anyone to refresh.

That means: **edit, then check.** Do not batch ten changes and hope.

```bash
caliper export      # rebuild out/ now, and see the error if there is one
caliper render      # look at it — PNGs in out/views/, which you can open and read
caliper render --focus jaw --persp   # aim the camera at one part, up close
caliper draft       # three-view line drawing — ASCII to read here, --svg to keep
caliper fitcheck    # measure it — clashes, gaps, ±Y symmetry, in mm
caliper rom         # how far each joint really moves before it hits something
caliper sim         # run the physics: does it stand, does it walk, does it stay up
caliper bundle      # write STEP/STL/3MF into out/export/ for a slicer or a CAD app
caliper help        # all of them, with what each is for
```

`rom` and `sim` only mean anything once the design has joints. On something that
does not move, `render` and `fitcheck` are the whole toolkit.

## Before you say it works

There is **no browser on this machine** and no way for you to screenshot the
viewport. But you are not blind: `caliper render` writes PNGs, and you can open
them and see the design. Do that — a picture catches the whole class of mistakes
that no number reports, like a part facing the wrong way.

What you cannot do is *guess*. A claim about the design is worth making if you
looked at it or if a command printed it, and not otherwise:

- Changed geometry? `caliper export` must succeed — a traceback means the
  watcher also failed and the browser is still showing the last good model.
- Moved something? `caliper fitcheck` — it finds parts buried inside each other,
  floating outside the body, or mirrored wrong, and says *where* in millimetres.
- Changed a limit, a link length, or anything a joint swings through? `caliper rom`.
- Changed mass, gains, or a gait? `caliper sim --seconds 8`. "It should stand"
  is not a result; `standing: PASS` is.
- Handing it to a slicer or another CAD app?
  `caliper bundle --formats step,stl` — it refuses nothing, but it does report
  a part that is not watertight, and that part will not slice.
- Looked at it? `caliper render --section 'y>0'`. A shaded view cannot show a motor
  buried in a beam. A cut plane through it can.
- Wondering what one part actually looks like?
  `caliper render --focus <part> --persp` puts the camera on it, close up, with
  the rest of the design still around it. Then **open the PNG and look at it**.

If a check fails, fix it or say plainly that it fails. Do not describe the
intent of a change as though it were the outcome.

## Committing

Commit when a change verifies — that is what makes a version you can come back
to. Stage and commit from this workspace as normal (`git add`, `git commit`);
the app shows the same history and can check any commit back out.

Write the message about the design, not the code: *"widen the hip cradle so the
knee clears full travel"*, not *"update config.py"*.

## The rule that breaks models

Author each body's geometry **in its own local frame, centred on the joint it
pivots about**, then place that frame with `origin`. Joint `anchor` and `axis`
are world coordinates at the rest pose. A part authored at its world position
orbits that offset instead of spinning cleanly.

That rule only bites on things that rotate. A part that never moves can be
authored wherever it belongs.

The full set — servo gains, collider limits, gaits, printing — is in the `cad`
skill. Read it before changing anything that moves; it is short and every
paragraph in it exists because something went wrong once.

## Units and conventions

Millimetres, Z up. The seeded example is authored **standing**, feet exactly on
`z=0`, so every joint's zero is "stand" and a servo target is a plain deviation
from it. Gravity defaults to a deliberately gentle -2000 mm/s².

Keep whatever you build sitting on `z=0` too: it is what makes a render legible,
and what stops an exported STL arriving 200 mm above the print bed.
