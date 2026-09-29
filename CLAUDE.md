# caliper — the app

This repository is the **workbench**, not a design. Designs live in workspaces:
directories under `workspaces/` (mounted at `/workspaces` in the container),
each its own git repository holding one design's `cad/`, its `out/` artifacts
and its history. A design can be a bracket, a lamp or a walking machine —
nothing here is specific to any one of them, and nothing assumes it moves.

```
docker/            the image: butai daemon + web app + toolchain + Claude CLI
bin/caliper        the one command an agent inside a workspace uses
tools/             the shared checkers: render, draft, fitcheck, rom, sim, print, bundle
template/          what a new workspace is seeded with (cad/, CLAUDE.md, skill)
web/               the app: a Vite + React + TypeScript (shadcn/ui) SPA in web/src,
                   the Python bridge (server.py), and the vendored protocol/3D helpers.
                   `npm run build` writes web/dist, which server.py serves.
scripts/           put a local butai binary in the build context; re-shoot docs/images
docs/DESIGN.md     what the app looks like and why — read it before adding UI
```

The UI says **design**; the code, the API and this document say **workspace**
wherever they mean the folder, the git repository or the butai workspace.

## Running it

```bash
docker compose up --build      # http://localhost:8017
```

That is the whole install. The build downloads the butai daemon from its public
releases (`docker/install-butai.sh`), checks the tarball against the release's
`SHA256SUMS` and refuses anything below **butai 1.0.0**, the release its wire
protocol settled at. `BUTAI_VERSION` (a build arg, and a `.env` value compose
passes through) pins a tag; `scripts/fetch-butai.sh` puts a local binary in the
build context instead, for a dev build of the daemon or a machine with no
network. A `.env` is optional — copy `.env.example` to change `BIND_ADDR`, or to
set a `WEB_TOKEN` once the port is exposed.

The container runs two processes (`docker/entrypoint.sh`): the butai daemon,
which owns every workspace and its panes, and `web/server.py`, which is the only
thing listening on a port. If either dies the container exits and Docker
restarts it — a half-running container that answers HTTP with no daemon behind
it is worse than a restart.

For quick frontend iteration, keep the backend and Butai inside Docker:

```bash
docker compose up --build -d
cd web && npm install && npm run dev  # Vite on 5173, proxying to Docker on 8017
```

Caliper connects only to `/state/butai/butai.sock` inside its own container.
There is no host daemon discovery or socket override. The frontend can run on
the host; its API, artifacts and terminal stream go to the Docker web server.
`server.py` serves `web/dist` in production. `CALIPER_SERVER` selects the Docker
web server URL for Vite; it never points directly at Butai.

## How the pieces reach each other

- The browser only ever talks to `web/server.py`.
- `/butai/api/*` is relayed verbatim to the daemon's `/v1/*`: the file tree,
  diffs, staging, commits, branches, agents and processes are all **the
  daemon's**, not ours. Before adding an endpoint here, read `crates/butai-protocol`
  in the butai repo — it is usually already there. (The protocol lives in
  rustdoc now; there is no `docs/PROTOCOL.md` any more.)
- Agent output and input use `/butai/api/workspaces/{id}/panes/{pane}/output`
  and `/input` over ordinary HTTP, relayed to the daemon’s Unix socket. The
  agent panel does not use browser WebSockets. The optional `/ws` bridge remains
  available for separate terminal clients.
- `/api/workspaces` is ours: what is on disk, creating one, removing one, typing
  into an agent's pane, checking out an old commit (the daemon's own checkout
  can only branch from HEAD), and export — `GET .../export` says what has been
  built and whether `cad/` has moved since, `POST` runs `caliper bundle` (or
  `render`/`print`) and waits, `GET .../download?path=…` streams one file or
  zips several.
- `/w/<slug>/out/...` serves a workspace's artifacts, which is why the viewport
  always shows the design named in the header.
- A workspace's `.butai.toml` starts its export watcher. The daemon reads it when
  the workspace opens — that is why there is no setup script any more.

## The boundary that keeps breaking

`tools/` is shared by every workspace, so **nothing in it may depend on one
model's names or constants**. Three examples that had to be fixed:

- `simcheck.mjs` decided what a foot was with `name.endsWith('_lower')`. It now
  reads the joint graph — a body nothing hangs from is the end of its chain.
- `fitcheck.py` imported `MOTOR_D`/`MOTOR_L` from the workspace's config and
  crashed on a model without them. It now skips that section instead.
- `bundle.py` has to leave the floor out of an exported STL, and cannot do it by
  looking for a body called `ground`. It drops bodies that are `fixed` and that
  no joint touches — and keeps everything when that would leave nothing, because
  a design made of one fixed solid is still a design. `web/src/hooks/useViewer.ts`
  filters the camera and the size readout by the same rule; if you change one,
  change both.

The app itself follows the same rule: physics is a capability, not the point.
The Play button, the clock and the step counter appear when `scene.json` has
joints and stay away when it does not.

When you add a check, ask what it does on a design with two parts and no motors.

## The parts catalogue

`tools/catalog/` is the shared catalogue of real, buyable things — bearings,
pulleys, motors, fasteners — and it is the fourth thing a design borrows, after
the tools, the template and (one day) a subdesign. A catalogue entry is not a
solid: it carries the spec, the mass, the fits it offers and needs, where its
numbers came from, and optionally the geometry — `solid()`, the `cutter()` for
the pocket it sits in, and an `envelope()`. One entry emits all of them, so a
pocket that does not match its bearing is not a mistake you can make.

A design says where it puts hardware and the counting is ours:

```python
from catalog import use
use("bearing/608ZZ", 2, where="hip fork plates")
```

`caliper bom` imports the model, so the quantity is however many times that line
actually ran — place a fifth leg and the bearing count follows in the same
second the render does. `caliper parts --fits 8` searches by what will mate,
which is the question a name search cannot answer.

Two rules, both the same rule as everywhere else here:

- **It is `catalog`, not `parts`.** Every workspace has a `cad/parts/` package
  and `cad/` sits ahead of the image on `PYTHONPATH`, so a shared module called
  `parts` would be shadowed in exactly the workspaces that wanted it.
- **Nothing in `tools/catalog/` may know one model's names.** A 608ZZ is a fact
  about the world; `MOTOR_D` is a fact about one robot. An entry takes its
  dimensions as arguments and its fits from the calling workspace, which is why
  changing `FIT_PRESS` after a calibration coupon moves every seat everywhere.

A guessed dimension may not carry a press fit — `caliper bom --check` fails on
it by name. That is the one gate worth having: a part that will not go in is
worse than a part nobody modelled.

## Verifying without a browser

Run the type check, production build, Python tests and API checks:

```bash
# the whole SPA: types and a production build. This is the gate the old
# `node --check` loop used to be — it now covers every .tsx as well.
cd web && npm run build          # tsc --noEmit && vite build → web/dist

curl -s localhost:8017/api/workspaces          # with the token cookie
curl -s localhost:8017/butai/api/workspaces/1   # the proxy reaches the daemon
curl -s localhost:8017/api/workspaces/<slug>/export   # what has been built
```

For the export loop: `touch workspaces/<name>/cad/model.py`, wait ~4 s, then
`stat -c '%n %.19y' workspaces/<name>/out/*` — the timestamps must move
(`ls -la` hides this at minute granularity).

For the download route, prove the traversal guard as well as the happy path:
`?path=../cad/model.py` must 404, not hand over a source file.

For browser checks, install Playwright and its matching Chromium build.
An alternate browser can be selected with `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH`
in the review scripts. Use a disposable stack with example designs for screenshots.

Spawning an agent starts a real Claude session and costs tokens. Do it
deliberately, not as a smoke test.

## Notes

- `docker/butai` is an optional local binary, gitignored: 15 MB, and the image
  downloads a release when it is absent. Whichever it uses, the build stage runs
  `butai --version` and stops below 1.0.0 — a daemon old enough to answer
  `/v1/*` differently should fail the build, not the first agent.
- Docker publishes only to `127.0.0.1` by default. LAN access requires both
  `BIND_ADDR=0.0.0.0` and `WEB_TOKEN`; use HTTPS or an SSH tunnel remotely.
  Access grants command execution and access to mounted credentials.
- **Known bug: the viewport desyncs during a long simulation.** Press Play on a
  design that travels and after ~2 s of sim time part of the assembly walks and
  part stays at the origin — you end up looking at two half-robots. It is not
  the model: `caliper sim` on the same workspace reports `walking: PASS` and
  every `decor` parent in `scene.json` resolves to a dynamic body. The suspect
  is `loadModel()` in `web/src/viewer/viewer.ts`, which reparents body meshes
  into fresh groups (zeroing `mesh.position`/`quaternion`) and only afterwards
  computes each decor mesh's world position — by which time an ancestor it
  depended on has been moved. Screenshots of a running sim are taken inside the
  first second for this reason.
- Either way, every route goes through the same check. If you add one, keep it
  there.
