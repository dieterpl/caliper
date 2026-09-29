---
name: cad
description: Author or modify the design in this workspace — build123d solids declared as bodies, and the joints, servos and gaits connecting them where it moves, across cad/config.py, cad/model.py and cad/parts/. Use whenever asked to model or change geometry (a plate, bracket, enclosure, mount, arm, gripper, wheel, hinge, slider, motor, belt; wall thickness, hole, fillet, dimensions, mass, colour, stance or gait).
---

# Authoring the design

A design here is a set of build123d solids declared as bodies. Joints, servos
and gaits are what you add **if it moves** — a bracket declares one body and is
finished; the app hides its simulation controls and nothing is missing.

Importing the model populates a module-global scene; `cad/export.py` turns that
into `out/model.glb` (render), `out/model.step` (interchange), `out/scene.json`
(physics) and `out/collision.json` (hull points for the headless harness).
`cad/watch.py` re-runs the export ~0.25s after any save **anywhere under `cad/`**,
and the browser reloads itself.

The model is split, so edit the file that owns the thing you are changing:

```
cad/config.py        every dimension, mass, gain and gait constant
cad/model.py         assembly order only — what the design is made of
cad/parts/hardware.py  reusable helpers: along_x()/along_y(), which mirror a
                       mount by side, and rounded_box()
cad/parts/chassis.py   the body the limbs hang from
cad/parts/leg.py       one limb: links, joints, servos
cad/parts/ground.py    the floor (the physics engine has gravity but no ground)
```

That is what a fresh workspace has — a worked four-leg example, because it
exercises every part of the DSL. It is a starting point, not the subject: for a
bracket, delete `leg.py` and `chassis.py` and declare what you were asked for.
Something that walks usually grows a `cad/gait.py` (foot paths + 2-link IK ->
sampled joint angles); see below.

A proportion change is usually a one-line edit to `cad/config.py`.

## The DSL

Import from `scene` (never edit `cad/scene.py` unless asked to extend the DSL):

```python
from build123d import Box, Cylinder, Sphere, Pos, Rot
from scene import body, decor, revolute, prismatic, fixed, motor, gait, sim
```

- `body(name, part, type=, mass=, collider=, origin=, color=, friction=, group=)`
  `type` is `dynamic` | `fixed` | `kinematic`. `origin` is where this body's
  local frame sits in the world. `friction` defaults to 0.7; feet want ~1.5.
  `group` buckets the part for the viewer's show/hide panel.
- `decor(name, part, parent=, origin=, mass=, color=, group=)` — cosmetic
  hardware bolted to a body: motors, pulleys, belts. Rendered and toggled on its
  own, but **never a rigid body**, so it costs the solver nothing. Its `mass` is
  rolled into `parent` at export, so a motor still loads the link it bolts to.
  Use this for anything that should be hideable but shouldn't collide.
- `revolute(a, b, anchor=, axis=, motor=, limits=, name=, drive=)` — hinge,
  `limits` in radians.
- `prismatic(a, b, anchor=, axis=, motor=, limits=, name=, drive=)` — slider, mm.
- `fixed(a, b, anchor=)` — weld.
- `motor(target_pos=, target_vel=, stiffness=, damping=)` — a drive on a joint.
- `gait(period, amplitude, phase=, offset=)` — a periodic target for a servo.
- `sim(timestep=, substeps=, gravity=, solver_iters=)` — world settings.

## Bought hardware

Bearings, pulleys, motors and fasteners come from the shared catalogue rather
than being redrawn and then re-counted by hand:

```python
from catalog import use, get
use("bearing/608ZZ", 2, where="hip fork plates")   # counted, not remembered
plate -= get("bearing/608ZZ").cutter(fits)          # the pocket, sized by YOUR fits
```

Declare `use()` where the model actually places the part — inside the loop, not
in a list at the bottom of a file. Then `caliper bom` counts it, and the number
cannot drift from the design. `caliper parts --fits 8` is how to find out what
already exists before modelling a new one.

## Motors: position servos vs velocity

`stiffness > 0` makes a **position servo** (a PD loop holding `target_pos`);
`stiffness == 0` leaves a plain velocity motor chasing `target_vel`. Anything
that has to hold a pose against gravity needs the servo — a velocity motor can
only brake, so a limbed model driven by `target_vel=0` will slowly fold flat.

Gains are in the `AccelerationBased` model, so they are mass-independent — but
they are **not** small numbers. On a ~20 kg robot with 200 mm links, stiffness
around `9e4` and damping `4.5e3` holds a stance; `800` folds instantly. Sweep
them with `--gain` rather than guessing.

## Walking: paths, not sine waves

For anything that has to locomote, use `trajectory(period, samples, phase)` with
angles from a `cad/gait.py` you write, not `gait()`. One sine per joint makes the
foot trace an oval, so it skids for most of the time it is on the ground — that
is a hard speed ceiling no amount of amplitude tuning gets past. Author the foot
PATH instead (planted and moving back at constant speed for `DUTY` of the stride,
then a lifted return) and solve 2-link IK for the joint angles.

Cruise speed is then a formula, not a mystery: `STEP_LEN / (PERIOD * DUTY)`.
Expect to actually achieve roughly half of it — gravity here is a gentle
-2000 mm/s², so the feet press down at a fifth of real weight and traction, not
torque, is what limits you.

Two failure modes worth knowing, both found by measuring:
- **Servo sag eats foot clearance.** If the stance servos droop, the swing foot
  scrapes and drags the robot *backwards*. Check the static hip height against
  `STANCE_DEPTH` before blaming the gait.
- **Walking off the ground slab** looks exactly like a catastrophic collapse in
  `simcheck`. Check the chassis x against the slab's half-size first.

Pass `drive=gait(...)` to make the target periodic:
`theta(t) = offset + amplitude * sin(2*pi*(t/period + phase))`, evaluated every
physics step by the simulator. Phase is in cycles, so a trot is
diagonal pairs at `0.0` and `0.5`. For a walking gait, the **sign of the
hip→knee phase lag sets the direction of travel** — negating both amplitudes
does not, since that is only a half-cycle time shift.

## The frame rule — this is what breaks models

Author each body's geometry **in its own local frame, centred on the joint it
pivots about**, then place that frame with `origin`. Joint `anchor` and `axis`
are given in **world** coordinates at the rest pose.

build123d primitives are centred on the origin by default, so a part authored
"in place" with `Pos(...)` bakes an offset into its geometry and will orbit
that offset instead of spinning cleanly. Compare:

```python
# WRONG — arm authored at its world position; it will swing about a point 200mm away
arm = Pos((200, 0, 0)) * Box(400, 20, 10)
body("arm", arm, origin=(0, 0, 100))

# RIGHT — arm centred on its own pivot, then placed
arm = Pos((200, 0, 0)) * Box(400, 20, 10)   # geometry offset so the pivot is at x=0
body("arm", arm, origin=(0, 0, 100))        # ...and THAT is the pivot in world
revolute("tower", "arm", anchor=(0, 0, 100), axis=(0, 1, 0))
```

The rule: whatever point of the part sits at its local `(0,0,0)` is the point
that lands on `origin`, and that is what the joint anchor must agree with.

## Units and conventions

- **Millimetres**, Z up. The starter model stands 258 mm at the chassis.
- Gravity defaults to `-2000` mm/s² (deliberately gentle; real gravity would be
  `-9810`). Override per-model with `sim(gravity=…)`.
- Revolute `axis` is the axis of rotation in world space — `(0,0,1)` spins about
  vertical, `(0,1,0)` is a pitch hinge.
- Rest pose convention: author limbs **straight**, with contact points exactly on
  `z=0`. Then every servo target is a plain deviation from that, instead of
  something you have to derive from the geometry.

## Colliders — know the limits

`collider="hull"` (the default) wraps the part in its **convex hull**. A concave
shape — a cross, a C-clamp, a gripper — collides as its filled-in outline, not
its true silhouette. `collider="trimesh"` is currently broken in the viewer, so
don't reach for it expecting concave collision; either keep shapes convex, or split a
concave part into several convex bodies welded with `fixed()`.

Jointed bodies have their mutual contacts disabled, so a link may overlap its
own parent freely — but a link can
still collide with anything it is *not* jointed to.

There is **no gear or coupling constraint** in the vendored Rapier (joint types
are Revolute, Fixed, Prismatic, Rope, Spring, Spherical, Generic). A belt or
gear train can therefore be modelled and positioned, but it cannot transmit
torque: drive the output joint's own servo instead.

## Placing hardware

A joint `anchor` is a point, but the axis it names is a **line**. A pulley on
that axis has to sit in its belt's plane, not at whatever point along the line
the anchor happens to be — putting one at the anchor once buried it 26 cm³ deep
in a bracket, and it looked fine until it was measured. If you write a `belt()`
helper, make it refuse non-coplanar pulleys and a centre distance shorter than
the two radii, rather than trusting yourself to notice.

Motor cans are long (a typical one is 65 mm), so which way a can points decides
the design's width. Point them away from the body, and keep any belt plane clear
of the shell: a plane inboard of the body wall drags the whole drive inside it.

## Checking your work

After editing, confirm the export succeeded rather than assuming it:

```bash
caliper export      # "export: N bodies, M joints, K decor -> …"
cat out/scene.json #  verify origins/anchors are what you intended
```

A traceback here means the watcher also failed and the browser is still showing
the last good model.

Then **check where the parts are** — `caliper fitcheck` measures the assembled
envelope and reports parts that are buried in each other, floating outside the
body, or mirrored wrong. It AABB-sweeps every pair and then runs a real boolean
on the survivors, so its millimetres and mm³ are exact, not estimates.

```bash
caliper fitcheck
```

Its ±Y symmetry line is worth trusting on anything meant to be symmetric: a
lopsided envelope means a mount that was not mirrored, which is very hard to see
and trivial to measure.
`along_x(sign)` / `along_y(sign)` in `parts/hardware.py` exist for exactly that —
a motor's shaft must point at the pulley it drives on BOTH sides.

Every finding says **where**, not just how much, and all of it lands in
`out/fitcheck.json`. Read that file rather than parsing the table: each clash
carries the centroid and box of every blob of shared solid, and each *near* pair
carries the two facing points and the gap between them. Those two points are
where a boss, a bolt or a joint anchor goes — a connection point is something to
look up, not to guess at.

## Where a joint can actually go

`caliper rom` rotates the whole subtree below each joint through the limits
`config.py` declares for it and reports the window that is collision-free, in
degrees of joint space (zero is the authored crouch, not legs-straight).

```bash
caliper rom                    # every joint, ~4 min
caliper rom --joint 'fl_*'     # one leg, ~1 min
caliper rom --joint fl_knee --pairs   # show the working
```

It exits non-zero when a declared limit reaches past a collision, which means
either the limit is wrong or the part needs clearance. Two things to know before
believing a result: a pair that already shares metal at rest only counts as
blocked once the overlap grows by 25% (a shaft in a bore does not stop a joint),
and the ground is excluded unless you pass `--ground`, because a leg swung into
the floor blocks every joint and tells you nothing.

## Looking at it

There is no browser here, so `caliper render` is how you see the model. It
writes a PNG you can **open and read as an image** — front, side, top and iso,
orthographic, with a scale bar you can measure against.

```bash
caliper render                      # out/views/model.png
caliper render --section 'y>142'    # cut through the leg plane
caliper render --only 'fl_*' --hide belts --view side
caliper render --pose fl_knee=-30 --view side
caliper render --joints --clash     # anchors, and fitcheck's blobs
```

**`--section` is the one that earns its keep.** A shaded view cannot show a
motor buried inside a beam; a cut plane through it can, and that exact fault sat
there for a while looking perfectly fine. `--pose` renders a configuration other
than the one the model was built in, which is how you confirm what `rom.py` says
is blocking a joint. `--only`/`--hide` take globs on part names or on the group
names the viewer's show/hide panel uses.

### Aiming the camera

The four fixed views are for the design as a whole. To understand one *part* —
how a bracket meets a beam, whether a boss lands on the face it should — put the
camera where you want it:

```bash
caliper render --focus hip_bracket --persp    # that part fills the frame,
                                              # the rest still drawn around it
caliper render --only hip_bracket --focus hip_bracket   # that part, alone
caliper render --eye 300,-400,250 --target 0,0,120 --persp
caliper render --azim 35 --elev 20 --zoom 2   # bearing and height, no arithmetic
caliper render --view around                  # all four iso corners at once
caliper render --view left,right,back,bottom  # the faces `all` leaves out
```

`--focus` is usually the one you want: it frames on the part but keeps its
neighbours in the picture, which is what tells you whether it *fits*. Add
`--only` with the same glob to see the part by itself.

**Orthographic measures; perspective explains.** `--persp` makes parallel edges
converge, so depth reads and you can tell which of two overlapping parts is in
front — but a distance no longer scales uniformly, and the bar is only true at
the target (it says `AT TARGET` to remind you). Judge shape in perspective,
measure in ortho, and never read a dimension off a `--persp` picture.

`--azim` runs in the XY plane from +X toward +Y, `--elev` up from it, so
`--azim 0 --elev 0` is `front` and `--azim 90 --elev 0` is `side`. `--eye` and
`--azim/--elev` each describe one camera, so they give one pane and cannot be
combined with each other. `--zoom 2` always means twice as big in frame,
whichever projection you are in.

For orthographic views as a line drawing rather than a shaded picture,
`caliper draft`. With no flag it prints the six views (front, back, left, right,
top, bottom) as **text, straight to the terminal** — the one view you can read
with no image tool at all, for a quick "are the proportions sane". `--out x.art`
writes that as a `.art` grid the app renders and you can draw on. With `--svg` it
writes `out/views/model.svg`: front/top/right as clean vector line-art,
third-angle and to one scale, with a title block and hidden edges dashed —
scalable and printable, for keeping or handing on. (You cannot *see* the SVG
here; that is what `render` is for.)

```bash
caliper draft                       # six orthographic views as ASCII, to stdout
caliper draft --out drawing.art     # that ASCII as a .art file the app opens as
                                    # an editable grid — draw on it, or hand-tweak
caliper draft --view top,front      # narrow the six down
caliper draft --svg                 # front/top/right third-angle → out/views/model.svg
caliper draft --svg --no-hidden     # visible edges only — far smaller on a
                                    # busy assembly, where dashed lines pile up
caliper draft --only 'fl_*' --pose fl_knee=-30
```

A `.art` file is just the grid of characters, so a generated one and a hand-drawn
one are the same file: the app's file viewer renders `.art` as an editable canvas
(and `.svg` as a picture) instead of raw text.

Then **actually simulate it** — `caliper sim` runs the same Rapier world
headless and reports whether the thing stands, walks and stays upright. Do not
claim a mechanism works without it; there is no usable browser on this machine.

```bash
caliper sim --static --seconds 3   # holds its pose?
caliper sim --seconds 8            # goes somewhere, stays upright?
caliper sim --gain 10 --amp 0.5 --period 2   # sweep without re-exporting
```

`--gain` scales every servo gain, `--amp` every gait amplitude, `--period`
overrides the stride — so tuning is a fast loop against the harness, and only
the settled values go back into `cad/config.py`.

Nothing anchors the model to the world by default: a body with no joint path to
a `fixed` body falls forever unless something (like `parts/ground.py`) gives it
a floor.

## Printing it

The print layer is **separate from the sim layer** and nothing in `model.py`
imports it, so a bore added for a bolt cannot perturb the physics and the watch
loop never pays for the detail. `cad/printing.py` owns every number that exists
only because a part is printed — wall thickness, hole compensation, bearing
seats, heat-set bosses, split lines — plus the catalogue of parts to make.
`caliper print` turns that into `out/print/*.stl` and a manifest.

```bash
caliper print --check    # report only, writes nothing
caliper print            # write out/print/
```

For the whole design rather than its printed catalogue — a STEP for another CAD
package, an STL or 3MF to hand someone — use `caliper bundle`, which writes
`out/export/<design>.<ext>` at the same tessellation:

```bash
caliper bundle --formats step,stl,3mf     # assembled
caliper bundle --formats stl --parts      # one file per part as well
```

It leaves out bodies that are `fixed` and jointless — the ground slab — so an
exported STL is the design, not the world it stands in. `--all` keeps them.

Never put a hole size inline in a part: take it from `printing.py`, so one
calibration coupon corrects the whole set. **Print `calibration.stl` first** —
it carries a 608 seat, an insert boss, a dowel hole and a shaft bore, and it is
20 minutes against 1.5 kg of filament.

Two failure modes it exists to catch, both found this way:

- **An enclosed void.** A blind bore that stops 0.15 mm short of the surface, or
  a hollow shell with no opening, renders perfectly and slices into a sealed
  pocket. `printparts` counts mesh bodies, so it fails the part instead.
- **A hollow that severs its own part.** One void spanning the head's neck and
  skull removed the 4 mm junction between them and left two lumps. Voids stay
  inside their own primitive and are joined by a throat.

`tessellate()` hands out per-face copies of shared vertices, so a raw mesh is
never watertight — a 20 mm cube arrives as 24 vertices and 6 "bodies". Merging
on position with an explicit tolerance is what stitches it back into a solid.
