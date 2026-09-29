"""Where the workspace being measured lives.

The tools ship in the image (`/opt/caliper/tools`) while the model they operate
on lives in a workspace (`/workspaces/<name>/cad`), so they cannot assume the
old "my parent directory is the project" rule — that would point every tool at
the image. Resolution order:

  1. `$WORKSPACE`, if set — an explicit override for scripts and the daemon.
  2. The nearest directory at or above `cwd` that contains `cad/`. This is what
     makes `caliper fitcheck` work from anywhere inside a workspace, the same
     way git finds its repository.
  3. This file's grandparent, so the tools still run from a checkout of the app
     itself (`tools/../cad`).

(The override is `WORKSPACE`, not a branded `CALIPER_ROOT`: it names what it
points at, and a workspace is a workspace whichever tool opened it.)

`OUT` is always `ROOT/out`; nothing writes outside it.
"""

from __future__ import annotations

import os
from pathlib import Path


def find_root(start: Path | None = None) -> Path:
    """The workspace root — see the module docstring for the search order."""
    env = os.environ.get("WORKSPACE")
    if env:
        return Path(env).resolve()
    here = (start or Path.cwd()).resolve()
    for cand in (here, *here.parents):
        if (cand / "cad").is_dir():
            return cand
    return Path(__file__).resolve().parent.parent


ROOT = find_root()
CAD = ROOT / "cad"
OUT = ROOT / "out"


def require_cad() -> Path:
    """Fail loudly, and with the fix, when there is no model here to work on."""
    if not CAD.is_dir():
        raise SystemExit(
            f"no cad/ directory under {ROOT}.\n"
            "Run this from inside a workspace (a folder containing cad/), or set "
            "WORKSPACE to one."
        )
    return CAD
