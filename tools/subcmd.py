"""`caliper sub` -- include another design in this one, as a git submodule.

A design is a git repository, so the thing that includes one is a submodule.
That is not a workaround for the lack of a package manager: it is the mechanism
git already has for "this repository, at exactly this commit", which is the
whole of what a subdesign needs. The pin is a commit id in the parent's tree, so
checking out a six-month-old version of the parent brings back the version of
the subdesign it was drawn against.

    caliper sub add odrive-leg            include a sibling design
    caliper sub add <url> --as leg        ...or one from anywhere
    caliper sub list                      what is included, and at which commit
    caliper sub status                    dirty? behind? the bit butai omits
    caliper sub update leg                move the pin to the sub's latest commit
    caliper sub sync                      check out the pins (after a fresh clone)

Two things this handles that plain `git submodule` does not:

  * **The URL of a sibling design is relative.** `../odrive-leg` resolves to the
    same repository on the host and at `/workspaces/odrive-leg` in the
    container, where an absolute host path would not exist at all.

  * **A dirty submodule is invisible in the app.** butai's `/changes` reports a
    workspace with edited submodule content as `state: clean` with nothing
    unstaged -- git itself says ` m cad/kits/leg`. Somebody editing subdesign
    geometry through the app would be told there was nothing to commit. That is
    what `caliper sub status` exists to say out loud, and what the app's own
    workspace endpoint now reports alongside it.
"""

from __future__ import annotations

import argparse
import configparser
import subprocess
import sys
from pathlib import Path

from paths import ROOT

# Where an included design lands. One directory, so the files rail has one place
# to show them and `.gitignore` has one path to reason about.
SUBDIR = "cad/kits"

# Local-path submodules need this since git 2.38 closed the file-transport hole.
# Every design here is a directory on the same machine, so every add is local.
GIT_LOCAL = ["-c", "protocol.file.allow=always"]


def git(*args: str, cwd: Path | None = None, check: bool = True) -> str:
    r = subprocess.run(["git", "-C", str(cwd or ROOT), *args],
                       capture_output=True, text=True)
    if check and r.returncode != 0:
        raise SystemExit(f"caliper sub: git {' '.join(args)}\n{r.stderr.strip()}")
    return r.stdout.strip()


def modules() -> list[dict]:
    """Every submodule of this design, with the state git knows and butai does not."""
    f = ROOT / ".gitmodules"
    if not f.is_file():
        return []
    cp = configparser.ConfigParser()
    cp.read_string(f.read_text())

    out = []
    for section in cp.sections():
        path = cp.get(section, "path", fallback=None)
        if not path:
            continue
        here = ROOT / path
        entry = {
            "name": Path(path).name,
            "path": path,
            "url": cp.get(section, "url", fallback=""),
            "present": (here / ".git").exists(),
            "pinned": "", "head": "", "dirty": False, "behind": 0, "subject": "",
        }
        # The pin is what the PARENT records; head is what is checked out. They
        # differ after someone commits inside the submodule without updating the
        # parent, which is the state that silently un-pins a design.
        rec = git("ls-tree", "HEAD", path, check=False)
        if rec:
            entry["pinned"] = rec.split()[2][:9] if len(rec.split()) > 2 else ""
        if entry["present"]:
            entry["head"] = git("rev-parse", "--short=9", "HEAD", cwd=here, check=False)
            entry["subject"] = git("log", "-1", "--format=%s", cwd=here, check=False)
            entry["dirty"] = bool(git("status", "--porcelain", cwd=here, check=False))
            count = git("rev-list", "--count", f"{entry['head']}..HEAD@{{u}}",
                        cwd=here, check=False)
            entry["behind"] = int(count) if count.isdigit() else 0
        out.append(entry)
    return out


def resolve_url(target: str) -> tuple[str, str]:
    """(url, default name). A sibling design becomes a RELATIVE url on purpose."""
    if "://" in target or target.startswith("git@"):
        return target, Path(target.rstrip("/")).name.removesuffix(".git")
    p = Path(target)
    if p.is_absolute() and p.is_dir():
        # An absolute host path does not exist inside the container. If it is a
        # sibling of this workspace, say so relatively and it resolves in both.
        if p.parent == ROOT.parent:
            return f"../{p.name}", p.name
        return str(p), p.name
    sibling = ROOT.parent / target
    if (sibling / ".git").exists():
        return f"../{target}", target
    raise SystemExit(
        f"caliper sub: no design {target!r} beside this one, and it is not a url.\n"
        f"  designs here: "
        + ", ".join(sorted(d.name for d in ROOT.parent.iterdir()
                           if (d / '.git').exists() and d != ROOT)))


def cmd_add(args) -> int:
    url, default = resolve_url(args.target)
    name = args.as_ or default
    path = f"{SUBDIR}/{name}"
    if (ROOT / path).exists():
        raise SystemExit(f"caliper sub: {path} already exists")
    if url == f"../{ROOT.name}":
        raise SystemExit("caliper sub: a design cannot include itself")

    git(*GIT_LOCAL, "submodule", "add", "-q", url, path)
    git("add", ".gitmodules", path)
    sub = ROOT / path
    sha = git("rev-parse", "--short=9", "HEAD", cwd=sub, check=False)
    print(f"  added {name} at {path}")
    print(f"  url   {url}")
    print(f"  pin   {sha}  {git('log', '-1', '--format=%s', cwd=sub, check=False)}")
    print(f"\n  staged, not committed. Commit the pin to record which version "
          f"this design\n  was drawn against:  git commit -m 'include {name}'")
    return 0


def cmd_list(args) -> int:
    subs = modules()
    if not subs:
        print(f"  {ROOT.name} includes no other design.\n"
              f"  caliper sub add <design>   include one")
        return 0
    print(f"\n  {ROOT.name} includes:\n")
    for s in subs:
        state = ("missing — run `caliper sub sync`" if not s["present"]
                 else "dirty" if s["dirty"] else "clean")
        print(f"  {s['name']:<16} {s['pinned'] or '—':<10} {state}")
        print(f"  {'':<16} {s['url']}")
        if s["subject"]:
            print(f"  {'':<16} {s['subject'][:58]}")
        if s["present"] and s["head"] and s["pinned"] and not s["head"].startswith(s["pinned"][:7]):
            print(f"  {'':<16} checked out at {s['head']}, but the pin says "
                  f"{s['pinned']} — commit the pin or `caliper sub sync`")
        print()
    return 0


def cmd_status(args) -> int:
    """The thing the app cannot tell you, said out loud.

    butai reports a workspace whose submodule content is edited as clean, with
    nothing unstaged. Everything below is invisible in the Changes tab.
    """
    subs = modules()
    problems = 0
    if not subs:
        print("  no submodules.")
        return 0
    for s in subs:
        if not s["present"]:
            print(f"  MISSING  {s['name']}  not checked out — `caliper sub sync`")
            problems += 1
            continue
        if s["dirty"]:
            print(f"  DIRTY    {s['name']}  edited content that this design's "
                  f"Changes tab does not show")
            for ln in git("status", "--porcelain", cwd=ROOT / s["path"],
                          check=False).splitlines()[:6]:
                print(f"           {ln}")
            print(f"           commit inside {s['path']}, then `caliper sub "
                  f"update {s['name']}` to move the pin")
            problems += 1
        if s["head"] and s["pinned"] and not s["head"].startswith(s["pinned"][:7]):
            print(f"  UNPINNED {s['name']}  checked out {s['head']}, pin says "
                  f"{s['pinned']}")
            problems += 1
        if s["behind"]:
            print(f"  BEHIND   {s['name']}  {s['behind']} commit(s) behind its "
                  f"upstream")
    if not problems:
        print(f"  {len(subs)} submodule(s), all clean and on their pin.")
    return 1 if problems else 0


def cmd_update(args) -> int:
    subs = {s["name"]: s for s in modules()}
    names = [args.name] if args.name else list(subs)
    if args.name and args.name not in subs:
        raise SystemExit(f"caliper sub: {args.name!r} is not included here. "
                         f"Included: {', '.join(subs) or 'nothing'}")
    for n in names:
        s = subs[n]
        sub = ROOT / s["path"]
        if not s["present"]:
            print(f"  {n}: not checked out — `caliper sub sync` first")
            continue
        if s["dirty"]:
            print(f"  {n}: has uncommitted changes; commit them inside "
                  f"{s['path']} before moving the pin")
            continue
        before = s["head"]
        git("fetch", "-q", check=False, cwd=sub)
        branch = git("rev-parse", "--abbrev-ref", "HEAD", cwd=sub, check=False)
        git("merge", "--ff-only", "-q", f"origin/{branch}", cwd=sub, check=False)
        after = git("rev-parse", "--short=9", "HEAD", cwd=sub, check=False)
        if after == before:
            print(f"  {n}: already at {after}")
            continue
        git("add", s["path"])
        print(f"  {n}: {before} -> {after}  "
              f"{git('log', '-1', '--format=%s', cwd=sub, check=False)}")
        print(f"      staged. `caliper export` before committing the pin: a "
              f"subdesign that moved is geometry that moved.")
    return 0


def cmd_sync(args) -> int:
    git(*GIT_LOCAL, "submodule", "update", "--init", "--recursive")
    for s in modules():
        print(f"  {s['name']:<16} {s['head'] or '—'}  {s['subject'][:48]}")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="caliper sub",
                                 description=__doc__.split("\n")[0])
    sp = ap.add_subparsers(dest="cmd")

    a = sp.add_parser("add", help="include another design")
    a.add_argument("target", help="a sibling design's name, a path, or a url")
    a.add_argument("--as", dest="as_", help="name it differently here")
    a.set_defaults(fn=cmd_add)

    for name, fn, help_ in (("list", cmd_list, "what is included"),
                            ("status", cmd_status, "dirty? behind? unpinned?"),
                            ("sync", cmd_sync, "check out the pins")):
        p = sp.add_parser(name, help=help_)
        p.set_defaults(fn=fn)

    u = sp.add_parser("update", help="move a pin to the sub's latest commit")
    u.add_argument("name", nargs="?", help="which one; omit for all")
    u.set_defaults(fn=cmd_update)

    args = ap.parse_args(argv)
    if not getattr(args, "fn", None):
        return cmd_list(args)
    if not (ROOT / ".git").exists():
        raise SystemExit(f"caliper sub: {ROOT} is not a git repository")
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
