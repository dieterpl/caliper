#!/usr/bin/env python3
"""The web app: workspaces, their artifacts, and a bridge to the butai daemon.

One process, standard library only. It does five things:

  * **Workspaces** (`/api/workspaces`) — a workspace is a directory under
    `$WORKSPACES_DIR` that holds one design: `cad/` (the model), `out/` (built
    artifacts) and its own git history. Creating one copies the template, makes
    the first commit, and hands the path to the daemon, which opens it and
    starts the export watcher from the workspace's `.butai.toml`.
  * **Artifacts** (`/w/<slug>/out/...`) — the viewer fetches the model and scene
    of whichever workspace is open, so the design on screen always belongs to
    the workspace named in the header.
  * **Export** (`/api/workspaces/<slug>/export|download`) — what a design can be
    handed to another program as. The building is `caliper bundle`'s; this
    decides what is stale, runs the command, and streams the result back as a
    file or a zip.
  * **The daemon's REST API** (`/butai/api/<rest>` -> `/v1/<rest>`) — the file
    tree, diffs, staging, commits, branches, agents and processes all come from
    butai; this only relays.
  * **Optional streaming bridge** (`/ws`) — the daemon's framed protocol over a
    WebSocket for compatible clients. The current terminal uses REST endpoints;
    this bridge only translates framing.

Both daemon paths ride its single AF_UNIX socket (framed + HTTP on the same
socket, routed by a first-byte sniff), so the daemon never opens a TCP port and
the butai project itself is never modified. Browsers can't open a Unix socket.

Because that relay can start processes in the container, `WEB_TOKEN` guards
every route: without the cookie you get a login page, not an API.

    python web/server.py [port]
"""
from __future__ import annotations   # so `list[Path]` parses on an older python

import base64
import hashlib
import hmac
import io
import json
import mimetypes
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
import zipfile
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

APP = Path(os.environ.get("APP_DIR") or Path(__file__).resolve().parent.parent)
sys.path.insert(0, str(APP / "tools"))
import projectio
WORKSPACES = Path(os.environ.get("WORKSPACES_DIR") or APP / "workspaces")
TEMPLATE = Path(os.environ.get("TEMPLATE_DIR") or APP / "template")
TOKEN = (os.environ.get("WEB_TOKEN") or "").strip()
PORT = int(sys.argv[1] if len(sys.argv) > 1 else os.environ.get("PORT") or 8017)

# The web app is now a Vite build: `npm run build` in web/ writes web/dist, and
# this server hands it out as the SPA. A missing build must never expose APP
# (which can contain credentials, Git internals and private workspaces).
DIST = Path(__file__).resolve().parent / "dist"
SERVE_DIR = DIST
SERVER_BIND = os.environ.get("SERVER_BIND", "127.0.0.1")

API_PREFIX = "/butai/api/"
WS_API = "/api/workspaces"
OUT_RE = re.compile(r"^/w/([^/]+)/out/(.*)$")
# Workspace names become a directory, a git repo, a butai workspace and a URL, so
# anything outside this character set is rejected outright rather than
# sanitised — "../.." can then never become an arbitrary file write.
SAFE_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
COOKIE = "caliper_token"
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"  # RFC 6455 handshake magic

# What the export dialog offers. The first five are `caliper bundle`'s formats,
# written as out/export/<slug>.<ext>; the last two are commands that already
# existed, listed here so one dialog covers everything a design can produce.
EXPORTS = [
    {"id": "step", "label": "STEP", "ext": "step",
     "what": "solid CAD — FreeCAD, Fusion, SolidWorks"},
    {"id": "stl", "label": "STL", "ext": "stl",
     "what": "one watertight mesh; what every slicer eats"},
    {"id": "3mf", "label": "3MF", "ext": "3mf",
     "what": "parts and colours kept apart, for modern slicers"},
    {"id": "obj", "label": "OBJ", "ext": "obj",
     "what": "mesh interchange"},
    {"id": "glb", "label": "GLB", "ext": "glb",
     "what": "exactly what the viewport draws"},
    {"id": "views", "label": "PNG views", "dir": "views", "glob": "*.png",
     "what": "orthographic renders — also the picture on the hub card"},
    {"id": "print", "label": "Print pack", "dir": "print", "glob": "*",
     "what": "one STL per printed part, plus the manifest"},
]
BUNDLE_IDS = [e["id"] for e in EXPORTS if "ext" in e]
EXPORT_IDS = {e["id"] for e in EXPORTS}
BUILD_TIMEOUT_S = 900


class ProjectBuildError(Exception):
    pass

# One build at a time per workspace: two concurrent OCCT tessellations of the
# same model would race on the same output files and cost twice the CPU.
_build_locks: dict[str, threading.Lock] = {}
_mutation_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def build_lock(slug: str) -> threading.Lock:
    with _locks_guard:
        return _build_locks.setdefault(slug, threading.Lock())


def mutation_lock(slug: str) -> threading.Lock:
    with _locks_guard:
        return _mutation_locks.setdefault(slug, threading.Lock())


def preview_fingerprint(root: Path) -> str:
    """Include every CAD input, even when it is older than the newest file.

    Content hashes for code/definitions also catch edits with preserved mtimes;
    names catch deletions. Imported CAD assets use size and nanosecond mtime.
    Generated output, Git internals and bytecode never invalidate a preview.
    """
    digest = hashlib.sha256()
    excluded = {".git", "__pycache__", "out"}
    for base, prefix in ((root / "cad", "cad"), (APP / "tools", "tools")):
        for directory, child_dirs, filenames in os.walk(base):
            # Prune generated trees before descending: included projects can
            # have thousands of old previews in their own out/ directories.
            child_dirs[:] = sorted(name for name in child_dirs if name not in excluded)
            for filename in sorted(filenames):
                path = Path(directory) / filename
                if filename in excluded or not path.is_file() or (prefix == "tools" and path.suffix != ".py"):
                    continue
                relative = path.relative_to(base)
                digest.update(f"{prefix}/{relative}\0".encode())
                if path.suffix in (".py", ".json", ".toml"):
                    digest.update(path.read_bytes())
                else:
                    stat = path.stat()
                    digest.update(f"{stat.st_size}:{stat.st_mtime_ns}".encode())
                digest.update(b"\0")
    return digest.hexdigest()


def project_preview_spec(ws: Path, root: Path, relative: str, kind: str, name: str, configuration=None):
    if kind not in ("component", "assembly", "scene"):
        raise ValueError("invalid preview kind")
    configuration = {} if configuration is None else configuration
    if not isinstance(configuration, dict):
        raise ValueError("preview configuration must be an object")
    data = projectio.manifest(root)
    key = {"component": "components", "assembly": "assemblies", "scene": "scenes"}[kind]
    if name not in data.get(key, {}):
        raise ValueError("unknown definition")
    actual = name
    if not (root / "cad/project.json").is_file():
        if kind != "component":
            raise ValueError("enable project definitions before previewing an assembly or scene")
        actual = data["components"][name]["legacy_part"]
    token = hashlib.sha256(json.dumps([relative, kind, name, configuration, data,
                                     preview_fingerprint(root)], sort_keys=True).encode()).hexdigest()[:20]
    destination = ws / "out/project-previews" / token
    return destination, ["project", "preview", "--kind", kind, "--name", actual,
                         "--out", str(destination), "--config", json.dumps(configuration)]


def preview_ready(destination: Path) -> bool:
    return all((destination / name).is_file() for name in ("scene.json", "model.glb"))


def response_cache_policy(path: str, status: int) -> str:
    """Only content-addressed files can outlive a request in the browser."""
    path = urlparse(path).path
    immutable_preview = re.fullmatch(r"/w/[^/]+/out/project-previews/[a-f0-9]{20}/(?:model\.glb|scene\.json)", path)
    hashed_asset = re.fullmatch(r"/assets/[^/]+-[A-Za-z0-9_-]{8,}\.(?:js|css|wasm|woff2?|png|jpe?g|svg|webp|ico)", path)
    if status in (200, 304) and (immutable_preview or hashed_asset):
        return "private, max-age=31536000, immutable"
    return "no-store"


class PreviewQueue:
    """One serial CAD worker per workspace, with persistent last-built previews.

    Cache-only browsing never starts CAD. Explicit build requests return
    immediately and share jobs by input fingerprint. Saves use a separate
    mutation lock; workers discard output if inputs changed during a build.
    """
    def __init__(self):
        self.condition = threading.Condition()
        self.jobs = {}
        self.workers = set()

    @staticmethod
    def _index_path(ws, relative, kind, name, configuration):
        identity = json.dumps([relative, kind, name, configuration or {}], sort_keys=True)
        token = hashlib.sha256(identity.encode()).hexdigest()[:20]
        return ws / "out/project-previews/latest" / (token + ".json")

    def _cached(self, ws, destination, index, *, allow_destination=True):
        # Indices retain the last complete preview across source edits and
        # server restarts. Only directories owned by this cache are accepted.
        previous = None
        try:
            saved = json.loads(index.read_text())
            directory = saved["directory"]
            if re.fullmatch(r"project-previews/[a-f0-9]{20}", directory) and preview_ready(ws / "out" / directory):
                previous = {"status": "ready" if saved["source"] == destination.name else "stale",
                            "directory": directory}
                if previous["status"] == "ready":
                    return previous
        except (OSError, ValueError, KeyError, TypeError):
            pass
        # A running exporter can write both files before reporting failure.
        # Its output is published only after the worker validates success.
        if allow_destination and preview_ready(destination):
            directory = str(destination.relative_to(ws / "out"))
            projectio.write(index, {"source": destination.name, "directory": directory})
            return {"status": "ready", "directory": directory}
        return previous

    def request(self, ws, root, relative, kind, name, configuration=None, *, background=False,
                retry=False, build=True, force=False):
        destination, arguments = project_preview_spec(ws, root, relative, kind, name, configuration)
        source = destination
        key = str(source.resolve())
        workspace = str(ws.resolve())
        index = self._index_path(ws, relative, kind, name, configuration)
        with self.condition:
            job = self.jobs.get(key)
            cached = self._cached(ws, source, index,
                                  allow_destination=not job or job["status"] == "ready")
            # Polling an explicit build preserves its progress even while an
            # older preview remains on screen. A browse never starts CAD.
            if job and job["status"] in ("queued", "building"):
                if build and not background and job["status"] == "queued":
                    job.update(background=False, eligible=time.monotonic())
                    self.condition.notify_all()
                result = self._public(job)
                if cached:
                    result["cached_directory"] = cached["directory"]
                return result
            if not build and job and job["status"] == "failed":
                result = self._public(job)
                if cached:
                    result["cached_directory"] = cached["directory"]
                return result
            if cached and cached["status"] == "ready" and not (build and force):
                return cached
            if not build:
                if cached:
                    cached["message"] = "Showing the last built preview. Rebuild to update it."
                    return cached
                return {"status": "missing", "message": "No preview yet. Build this preview when you are ready."}
            if job is None or (retry and job["status"] == "failed") or job["status"] == "ready" or force:
                # A forced build gets a fresh immutable URL, leaving the last
                # successful files safe while the new build runs or fails.
                if force:
                    nonce = hashlib.sha256(f"{key}:{time.time_ns()}".encode()).hexdigest()[:20]
                    destination = source.with_name(nonce)
                    arguments[arguments.index("--out") + 1] = str(destination)
                directory = str(destination.relative_to(ws / "out"))
                job = {"status": "queued", "directory": directory, "workspace": workspace,
                       "root": root, "destination": destination, "source": source, "index": index,
                       "arguments": arguments, "inputs": (ws, root, relative, kind, name, configuration),
                       "background": background, "eligible": time.monotonic() + (0.75 if background else 0)}
                self.jobs[key] = job
                completed = [k for k, j in self.jobs.items() if j["workspace"] == workspace
                             and j["status"] in ("ready", "failed")]
                for old_key in completed[:-64]:
                    self.jobs.pop(old_key, None)
            if workspace not in self.workers and job["status"] == "queued":
                self.workers.add(workspace)
                threading.Thread(target=self._work, args=(workspace, ws.name), daemon=True).start()
            self.condition.notify_all()
            result = self._public(job)
            if cached:
                result["cached_directory"] = cached["directory"]
            return result

    @staticmethod
    def _public(job):
        return {key: job[key] for key in ("status", "directory", "message", "log") if key in job}

    @staticmethod
    def _priority(job):
        # A user who clicks another item should get their latest selection
        # before older queued selections. Idle warming retains FIFO order.
        return (job["background"], job["eligible"] if job["background"] else -job["eligible"])

    def _work(self, workspace, slug):
        while True:
            with self.condition:
                queued = [j for j in self.jobs.values() if j["workspace"] == workspace and j["status"] == "queued"]
                if not queued:
                    self.workers.discard(workspace)
                    return
                queued.sort(key=self._priority)
                job = queued[0]
                delay = job["eligible"] - time.monotonic()
                if delay > 0:
                    self.condition.wait(timeout=delay)
                    continue
            # Reconsider priorities between builds, without holding the queue
            # guard while a separate export or save finishes.
            lock = build_lock(slug)
            if not lock.acquire(timeout=0.1):
                continue
            try:
                with self.condition:
                    queued = [j for j in self.jobs.values() if j["workspace"] == workspace and j["status"] == "queued"]
                    if min(queued, key=self._priority) is not job:
                        continue
                    job["status"] = "building"
                try:
                    if not preview_ready(job["destination"]):
                        current, _ = project_preview_spec(*job["inputs"])
                        if current != job["source"]:
                            raise ProjectBuildError("Source changed while the preview was queued; request the updated model.")
                        ok, log = run_tool(job["root"], job["arguments"])
                        if not ok:
                            raise ProjectBuildError(log)
                        if not preview_ready(job["destination"]):
                            raise ProjectBuildError("CAD did not produce a complete preview")
                        current, _ = project_preview_spec(*job["inputs"])
                        if current != job["source"]:
                            shutil.rmtree(job["destination"], ignore_errors=True)
                            raise ProjectBuildError("Source changed during the preview build; request the updated model.")
                    with self.condition:
                        projectio.write(job["index"], {"source": job["source"].name, "directory": job["directory"]})
                        job["status"] = "ready"
                except (ProjectBuildError, subprocess.TimeoutExpired, OSError, ValueError, KeyError) as exc:
                    # CAD can leave both files behind before reporting an
                    # error. Never let that unsuccessful output become a hit.
                    shutil.rmtree(job["destination"], ignore_errors=True)
                    with self.condition:
                        job.update(status="failed", message="CAD preview failed", log=str(exc))
            finally:
                lock.release()

    def warm(self, ws, root, relative, data):
        # A short, bounded warm-up keeps the machine responsive and avoids
        # building an entire library nobody has opened. Hover/request can add
        # other definitions; a click always takes priority over queued warm-up.
        manifest = data["manifest"]
        candidates = [("component", name) for name in list(manifest.get("components", {}))[:3]]
        for kind, name in candidates:
            definition = manifest["components"][name]
            if isinstance(definition, dict) and definition.get("instances") == []:
                continue
            try:
                self.request(ws, root, relative, kind, name, background=True)
            except (ValueError, KeyError, OSError):
                # A malformed definition should be reported when opened,
                # without making the entire project library unavailable.
                continue


PREVIEWS = PreviewQueue()


def butai_socket_path() -> str:
    """Caliper owns one Butai daemon inside its Docker container.

    Never discover a host daemon through HOME, XDG or an environment override.
    HTTP and terminal streaming share this same private container socket.
    """
    return "/state/butai/butai.sock"


def daemon_call(method: str, path: str, body: bytes, content_type: str):
    """One HTTP/1.1 request to the butai daemon over its unix socket.

    Returns (status, content_type, body_bytes). The daemon closes the
    connection after each response (Connection: close), so we read to EOF.
    """
    head = (
        f"{method} {path} HTTP/1.1\r\nHost: butai\r\nConnection: close\r\n"
        f"Content-Type: {content_type}\r\nContent-Length: {len(body)}\r\n\r\n"
    ).encode()
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(60)  # uploads/reads can be large
    try:
        s.connect(butai_socket_path())
    except OSError as e:
        return 502, "application/json", (
            b'{"error":"cannot reach butai daemon at %s: %s"}'
            % (butai_socket_path().encode(), str(e).encode())
        )
    try:
        s.sendall(head + body)
        raw = b""
        while True:
            chunk = s.recv(65536)
            if not chunk:
                break
            raw += chunk
    finally:
        s.close()
    head_bytes, _, resp_body = raw.partition(b"\r\n\r\n")
    lines = head_bytes.split(b"\r\n")
    status = 502
    if lines and lines[0].startswith(b"HTTP/"):
        parts = lines[0].split(b" ")
        if len(parts) > 1 and parts[1].isdigit():
            status = int(parts[1])
    ctype = "application/json"
    for ln in lines[1:]:
        k, _, v = ln.partition(b":")
        if k.strip().lower() == b"content-type":
            ctype = v.strip().decode(errors="replace")
    return status, ctype, resp_body


def daemon(method: str, path: str, payload=None):
    """daemon_call for JSON in and JSON out. Returns (status, parsed-or-None)."""
    body = b"" if payload is None else json.dumps(payload).encode()
    status, _ctype, raw = daemon_call(method, path, body, "application/json")
    try:
        return status, (json.loads(raw) if raw.strip() else None)
    except ValueError:
        return status, None


# --------------------------------------------------------------------------
# Framed protocol <-> WebSocket relay (ported from butai/web/server.py)
# --------------------------------------------------------------------------
def recv_exact(sock, n):
    """Read exactly n bytes from a blocking socket, or None at EOF."""
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


def ws_send(conn, payload, opcode=0x1):
    """Send one unmasked server WebSocket frame (server frames are never masked)."""
    header = bytearray([0x80 | opcode])  # FIN + opcode
    n = len(payload)
    if n < 126:
        header.append(n)
    elif n < 65536:
        header.append(126)
        header += struct.pack(">H", n)
    else:
        header.append(127)
        header += struct.pack(">Q", n)
    conn.sendall(bytes(header) + payload)


def ws_recv(sock):
    """Read one WebSocket frame from the client -> (opcode, bytes), or None.

    Coalesces continuation frames; the browser sends our small JSON messages
    unfragmented anyway.
    """
    data = b""
    opcode = None
    while True:
        hdr = recv_exact(sock, 2)
        if hdr is None:
            return None
        fin, op = hdr[0] & 0x80, hdr[0] & 0x0F
        masked, length = hdr[1] & 0x80, hdr[1] & 0x7F
        if length == 126:
            ext = recv_exact(sock, 2)
            if ext is None:
                return None
            length = struct.unpack(">H", ext)[0]
        elif length == 127:
            ext = recv_exact(sock, 8)
            if ext is None:
                return None
            length = struct.unpack(">Q", ext)[0]
        mask = recv_exact(sock, 4) if masked else b"\x00\x00\x00\x00"
        if mask is None:
            return None
        payload = recv_exact(sock, length) if length else b""
        if payload is None:
            return None
        if masked:
            payload = bytes(b ^ mask[i & 3] for i, b in enumerate(payload))
        if opcode is None:
            opcode = op
        data += payload
        if fin:
            return opcode, data


def relay_ws(handler):
    """Bridge one browser WebSocket to one framed butai socket connection.

    Browser text frame == one ClientMsg JSON -> length-prefixed to the daemon.
    Daemon length-prefixed frame == one ServerMsg JSON -> browser text frame.
    """
    key = handler.headers.get("Sec-WebSocket-Key")
    if not key or "websocket" not in (handler.headers.get("Upgrade", "") or "").lower():
        handler.send_error(400, "expected websocket upgrade")
        return
    accept = base64.b64encode(hashlib.sha1((key + WS_GUID).encode()).digest()).decode()
    handler.connection.sendall(
        "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
        f"Connection: Upgrade\r\nSec-WebSocket-Accept: {accept}\r\n\r\n".encode()
    )
    ws = handler.connection
    ws.settimeout(None)

    try:
        d = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        d.connect(butai_socket_path())
    except OSError as e:
        try:
            ws_send(ws, json.dumps({"error": f"butai socket: {e}"}).encode())
            ws_send(ws, b"", opcode=0x8)
        except OSError:
            pass
        return

    stop = threading.Event()

    def daemon_to_browser():
        try:
            while not stop.is_set():
                head = recv_exact(d, 4)
                if head is None:
                    break
                (n,) = struct.unpack(">I", head)
                payload = recv_exact(d, n) if n else b""
                if payload is None:
                    break
                ws_send(ws, payload)  # forward the raw JSON payload verbatim
        except OSError:
            pass
        finally:
            stop.set()
            try:
                ws_send(ws, b"", opcode=0x8)
            except OSError:
                pass

    threading.Thread(target=daemon_to_browser, daemon=True).start()
    try:
        while not stop.is_set():
            frame = ws_recv(ws)
            if frame is None:
                break
            opcode, payload = frame
            if opcode == 0x8:  # close
                break
            if opcode == 0x9:  # ping -> pong
                ws_send(ws, payload, opcode=0xA)
            elif opcode in (0x1, 0x0):  # text / continuation: a ClientMsg JSON
                d.sendall(struct.pack(">I", len(payload)) + payload)
    except OSError:
        pass
    finally:
        stop.set()
        d.close()


# --------------------------------------------------------------------------
# Workspaces
# --------------------------------------------------------------------------
def git(ws: Path, *args: str) -> str:
    """One read-only git command in a workspace. Empty string on any failure."""
    try:
        r = subprocess.run(["git", "-C", str(ws), *args],
                           capture_output=True, text=True, timeout=15)
        return r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def run_tool(ws: Path, args: list[str]) -> tuple[bool, str]:
    """One `caliper <command>` in a workspace -> (ok, the tail of what it said).

    `bin/caliper` picks the interpreter that has build123d, so this hands it
    `sys.executable` (the venv, in the container) and lets it decide. The tail
    matters: when a build fails, that text is the only report the browser gets.
    """
    cmd = [sys.executable, str(APP / "bin" / "caliper"), *args]
    # Don't let tools/ cache bytecode: a half-written or cross-interpreter .pyc
    # in tools/__pycache__ raises "bad marshal data" on the next import and takes
    # every export down with it. Recompiling these small modules each run is free
    # next to the tessellation, and it can never leave a poisoned cache behind.
    env = {**os.environ, "WORKSPACE": str(ws), "APP_DIR": str(APP),
           "PYTHONDONTWRITEBYTECODE": "1"}
    r = subprocess.run(cmd, cwd=str(ws), env=env, capture_output=True, text=True,
                       timeout=BUILD_TIMEOUT_S)
    log = (r.stdout or "") + (r.stderr or "")
    return r.returncode == 0, log[-4000:]


def slugify(name: str) -> str:
    """A display name -> the one identifier used for path, repo, URL and pane."""
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-")
    return slug[:64]


def workspace_dirs() -> list[Path]:
    """Every directory under WORKSPACES that holds a model."""
    if not WORKSPACES.is_dir():
        return []
    return sorted(
        d for d in WORKSPACES.iterdir()
        if not d.is_symlink() and d.is_dir() and SAFE_NAME.fullmatch(d.name) and (d / "cad").is_dir()
    )


def daemon_workspaces() -> dict[str, dict]:
    """The daemon's open workspaces, keyed by resolved cwd."""
    status, rows = daemon("GET", "/v1/workspaces")
    if status != 200 or not isinstance(rows, list):
        return {}
    out = {}
    for w in rows:
        cwd = w.get("cwd") or w.get("path")
        if cwd:
            try:
                out[str(Path(cwd).resolve())] = w
            except OSError:
                pass
    return out


def scene_counts(ws: Path) -> dict:
    """Body/joint counts from the last export, for the hub card."""
    scene = ws / "out" / "scene.json"
    if not scene.is_file():
        return {}
    try:
        data = json.loads(scene.read_text())
    except (OSError, ValueError):
        return {}
    return {k: len(data.get(k, [])) for k in ("bodies", "joints", "decor")}


def out_file(ws: Path, rel: str) -> Path | None:
    """A path inside a workspace's out/, or None if it points anywhere else.

    The one containment check: both the static route for `/w/<slug>/out/...` and
    the download route resolve through here, so a traversal is refused in one
    place rather than in two that can drift apart.
    """
    try:
        base = (ws / "out").resolve()
        if not base.is_relative_to(ws.resolve()):
            return None
        target = (base / unquote(rel)).resolve()
    except (OSError, ValueError, RuntimeError):
        return None
    return target if target == base or base in target.parents else None


# The image types /file will hand back. Narrowing the working-tree route to
# pictures keeps it from becoming a way to read any source file — the daemon's
# own file endpoint already serves text, and this one is only for the <img>.
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico", ".avif"}


def ws_file(ws: Path, rel: str) -> Path | None:
    """A path inside a workspace's working tree, or None if it escapes it.

    Rooted at the workspace itself (not out/), so the file preview can reach a
    picture committed under cad/. Refuses a traversal, the directory itself, and
    anything under .git — the same one-place guard idea as out_file.
    """
    base = ws.resolve()
    try:
        target = (base / unquote(rel)).resolve()
    except (OSError, ValueError, RuntimeError):
        return None
    if base not in target.parents:            # traversal, or the dir itself
        return None
    if ".git" in target.relative_to(base).parts:
        return None
    return target


def newest_source(ws: Path) -> float:
    """When this design's CAD last changed. Anything older than it is stale."""
    return max((p.stat().st_mtime for p in (ws / "cad").rglob("*")
                if p.is_file() and (p.suffix == ".py" or p.name == "project.json")), default=0.0)


def export_state(ws: Path) -> dict:
    """What each export format currently is on disk: built, stale, or missing."""
    source_t = newest_source(ws)
    out = (ws / "out").resolve()

    def entry(p: Path) -> dict:
        """One file, named the way /download wants it: relative to out/."""
        return {"path": str(p.relative_to(out)), "bytes": p.stat().st_size}

    rows = []
    for spec in EXPORTS:
        parts = []
        if "ext" in spec:
            paths = [ws / "out" / "export" / f"{ws.name}.{spec['ext']}"]
            # Per-part files ride along so "one file per part" can download what
            # it just built, instead of quietly handing back only the assembly.
            pdir = ws / "out" / "export" / "parts"
            if pdir.is_dir():
                parts = [entry(p) for p in sorted(pdir.glob(f"*.{spec['ext']}"))]
        else:
            d = ws / "out" / spec["dir"]
            paths = sorted(p for p in d.glob(spec["glob"]) if p.is_file()) if d.is_dir() else []
        have = [p for p in paths if p.is_file()]
        files = [entry(p) for p in have]
        rows.append({
            **{k: v for k, v in spec.items() if k in ("id", "label", "what", "ext")},
            "files": files,
            "parts": parts,
            "bytes": sum(f["bytes"] for f in files),
            "mtime": max((p.stat().st_mtime for p in have), default=0.0),
            # Nothing built is not "stale" — the dialog says "not built" instead,
            # which is a different sentence for a different situation.
            "stale": bool(have) and max(p.stat().st_mtime for p in have) < source_t,
        })
    return {"design": ws.name, "formats": rows, "joints": scene_counts(ws).get("joints", 0)}


def describe(ws: Path, opened: dict | None) -> dict:
    """Everything the hub shows about one workspace.

    Git is read directly rather than through the daemon so the hub still works
    when the daemon is down — the app should never look empty because a socket
    is missing.
    """
    thumb = ws / "out" / "views" / "model.png"
    last = git(ws, "log", "-1", "--format=%h\x1f%s\x1f%cr")
    sha, msg, when = (last.split("\x1f") + ["", "", ""])[:3] if last else ("", "", "")
    dirty = [ln for ln in git(ws, "status", "--porcelain").splitlines() if ln.strip()]
    commits = git(ws, "rev-list", "--count", "HEAD")
    return {
        "slug": ws.name,
        "path": str(ws),
        "branch": git(ws, "rev-parse", "--abbrev-ref", "HEAD") or "—",
        "dirty": len(dirty),
        "commits": int(commits) if commits.isdigit() else 0,
        "last": {"sha": sha, "message": msg, "when": when},
        # The preview's mtime doubles as its cache key, so the hub can poll
        # without re-fetching an image that has not been re-rendered.
        "thumb": thumb.stat().st_mtime_ns // 1_000_000 if thumb.is_file() else 0,
        "exported": (ws / "out" / "model.glb").is_file(),
        **scene_counts(ws),
        # From the daemon: the id every /butai/api call needs, plus the pane counts.
        "id": (opened or {}).get("id"),
        "agents": (opened or {}).get("agents", 0),
        "working": (opened or {}).get("working", 0),
        "waiting": (opened or {}).get("waiting", 0),
        "processes": (opened or {}).get("processes", 0),
    }


def open_in_daemon(ws: Path) -> dict | None:
    """Hand a workspace directory to the daemon, which reads its .butai.toml."""
    status, body = daemon("POST", "/v1/workspaces", {"name": ws.name, "path": str(ws)})
    if status not in (200, 201) or not isinstance(body, dict):
        return None
    return body


def adopt_all() -> None:
    """Open every workspace directory the daemon does not already know about.

    Covers first boot (a fresh /state volume has no session file) and folders
    copied in from outside the app. The daemon restores its own workspaces, so
    this normally finds nothing to do.
    """
    known = daemon_workspaces()
    for ws in workspace_dirs():
        if str(ws.resolve()) not in known:
            if open_in_daemon(ws):
                print(f"[ws] opened {ws.name}")


def agent_pane(ws_id) -> int | None:
    """The pane of the workspace's most recent agent, or None."""
    status, detail = daemon("GET", f"/v1/workspaces/{ws_id}")
    if status != 200 or not isinstance(detail, dict):
        return None
    agents = detail.get("agents") or []
    return agents[-1].get("pane") if agents else None


def send_to_pane(ws_id, pane: int, text: str) -> bool:
    """Type `text` into a pane and press enter — how the app briefs an agent."""
    base = f"/v1/workspaces/{ws_id}/panes/{pane}/input"
    ok, _ = daemon("POST", base, {"paste": text})
    if ok not in (200, 201):
        return False
    # A beat between paste and enter: the CLI redraws its prompt on paste, and
    # an immediate newline can land before it has taken the text.
    time.sleep(0.25)
    ok, _ = daemon("POST", base, {"key": {"code": "enter"}})
    return ok in (200, 201)


def trust_for_claude(ws: Path) -> None:
    """Record that the agent may work in a folder this app just created.

    Claude Code asks "is this a project you trust?" the first time it opens a
    directory, and an agent sitting in that dialog swallows the brief the app
    types at it. Answering for a folder *we* scaffolded, from our own template,
    inside our own container, at the user's explicit request, is a decision the
    app is entitled to make — so it is recorded here rather than clicked past.

    Directories the app merely adopted are deliberately NOT trusted: the app did
    not make those, so their prompt stays for a person to answer.
    """
    cfg = Path.home() / ".claude.json"
    try:
        data = json.loads(cfg.read_text()) if cfg.is_file() else {}
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    projects = data.setdefault("projects", {})
    entry = projects.setdefault(str(ws), {})
    entry["hasTrustDialogAccepted"] = True
    try:
        cfg.write_text(json.dumps(data, indent=2))
    except OSError as e:
        print(f"[ws] could not record trust for {ws}: {e}")


def scaffold(slug: str, brief: str) -> Path:
    """Create the workspace directory from the template and commit it.

    Any failure takes the half-made directory with it: a folder with no git
    history would still show up on the hub, which is worse than nothing.
    """
    dest = WORKSPACES / slug
    WORKSPACES.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copytree(TEMPLATE, dest,
                        ignore=shutil.ignore_patterns("__pycache__", "out", "*.pyc"))

        # Each CLI reads its own conventional instructions filename.
        if brief.strip():
            claude_md = dest / "CLAUDE.md"
            text = claude_md.read_text() if claude_md.is_file() else ""
            claude_md.write_text(
                f"{text.rstrip()}\n\n## What this design should be\n\n{brief.strip()}\n")
        instructions = (dest / "CLAUDE.md").read_text() if (dest / "CLAUDE.md").is_file() else ""
        for filename in ("AGENTS.md", "GEMINI.md"):
            if not (dest / filename).exists():
                (dest / filename).write_text(instructions)

        run = partial(subprocess.run, check=True, capture_output=True, text=True)
        # `git init -b` needs git 2.28; symbolic-ref works on every version.
        run(["git", "init", "-q", str(dest)])
        run(["git", "-C", str(dest), "symbolic-ref", "HEAD", "refs/heads/main"])
        run(["git", "-C", str(dest), "add", "-A"])
        run(["git", "-C", str(dest), "commit", "-q", "-m", f"new workspace: {slug}"])
    except Exception:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    return dest


class Handler(SimpleHTTPRequestHandler):
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".glb": "model/gltf-binary",
        ".gltf": "model/gltf+json",
        ".js": "text/javascript",
        ".json": "application/json",
        ".wasm": "application/wasm",
    }

    # ------------------------------------------------------------------ auth
    def _cookie_token(self) -> str:
        raw = self.headers.get("Cookie") or ""
        for part in raw.split(";"):
            k, _, v = part.strip().partition("=")
            if k == COOKIE:
                return unquote(v)
        return ""

    def _authed(self) -> bool:
        if not TOKEN:
            return True   # no token configured: localhost dev mode
        return hmac.compare_digest(self._cookie_token().encode(), TOKEN.encode())

    def _browser_allowed(self) -> bool:
        # Tokenless access is local only, including the Host header: an attacker
        # must not use DNS rebinding to turn a public origin into localhost.
        try:
            host = urlparse("//" + (self.headers.get("Host") or "")).hostname
        except ValueError:
            host = None
        if not TOKEN and host not in {"localhost", "127.0.0.1", "::1"}:
            self._send_json(403, {"error": "remote access requires WEB_TOKEN"})
            return False
        if self.headers.get("Sec-Fetch-Site") == "cross-site" or not self._same_origin():
            self._send_json(403, {"error": "cross-site request refused"})
            return False
        return True

    def _same_origin(self) -> bool:
        """Reject cross-site writes. The cookie is SameSite=Strict as well, so
        this is the belt to that braces — a request from another page cannot
        make this server start a process in the container."""
        origin = self.headers.get("Origin")
        if not origin:
            return True   # not a browser form/fetch (curl, the mac client)
        try:
            parsed = urlparse(origin)
            return parsed.scheme in {"http", "https"} and parsed.netloc == (self.headers.get("Host") or "")
        except ValueError:
            return False

    def _deny(self):
        """A browser gets the login page; anything else gets an honest 401."""
        wants_html = "text/html" in (self.headers.get("Accept") or "")
        if self.command == "GET" and wants_html:
            self.send_response(302)
            self.send_header("Location", "/login")
            self.end_headers()
        else:
            self._send_json(401, {"error": "not authorised — open / and sign in"})

    def _login_page(self, message: str = ""):
        body = LOGIN_HTML.replace("{{msg}}", message).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _do_login(self):
        length = int(self.headers.get("Content-Length") or 0)
        form = parse_qs(self.rfile.read(length).decode("utf-8", "replace"))
        given = (form.get("token") or [""])[0]
        if not hmac.compare_digest(given.encode(), TOKEN.encode()):
            return self._login_page("That token is not right.")
        self.send_response(302)
        self.send_header("Location", "/")
        self.send_header(
            "Set-Cookie",
            f"{COOKIE}={quote(given, safe='')}; Path=/; HttpOnly; SameSite=Strict; Max-Age=86400")
        self.end_headers()

    # ------------------------------------------------------------- utilities
    def _send_json(self, status: int, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            data = json.loads(self.rfile.read(length))
            return data if isinstance(data, dict) else {}
        except ValueError:
            return {}

    def translate_path(self, path):
        """Serve `/w/<slug>/out/...` out of that workspace's build directory.

        Artifacts live outside the served tree (a workspace is a volume, the app
        is the image), so this is the one mapping that leaves APP.
        """
        m = OUT_RE.match(path.split("?", 1)[0])
        if m and SAFE_NAME.match(m.group(1)):
            ws = WORKSPACES / m.group(1)
            target = out_file(ws, m.group(2))
            if target is not None:
                return str(target)
            # A traversal attempt resolves outside out/. Point at a name that is
            # not there so it 404s, rather than quietly serving the directory.
            # (Not a NUL byte: open() raises ValueError on that, which is a 500.)
            return str((ws / "out").resolve() / ".outside-this-workspace")
        return super().translate_path(path)

    def send_head(self):
        """Serve only contained files, never directory listings or dotfiles."""
        path = self.path.split("?", 1)[0]
        try:
            if any(part.startswith(".") for part in unquote(path).split("/") if part):
                return self.send_error(404)
            match = OUT_RE.match(path)
            if match:
                if not SAFE_NAME.fullmatch(match.group(1)):
                    return self.send_error(404)
                ws = WORKSPACES / match.group(1)
                if ws.is_symlink():
                    return self.send_error(404)
                target = out_file(ws, match.group(2))
            elif path.startswith("/w/"):
                return self.send_error(404)
            else:
                target = Path(super().translate_path(path)).resolve()
                if not target.is_relative_to(DIST.resolve()):
                    return self.send_error(404)
                if target == DIST.resolve():
                    target /= "index.html"
            if target is None or not target.is_file():
                return self.send_error(404)
        except (OSError, ValueError, RuntimeError):
            return self.send_error(404)
        return super().send_head()

    # ------------------------------------------------------------- workspaces
    def _workspaces(self, method: str):
        rest = self.path[len(WS_API):].split("?", 1)[0].strip("/")

        if method == "GET" and not rest:
            # Adopting here (rather than only at boot) is deliberate: a folder
            # copied into /workspaces shows up the next time the hub polls,
            # instead of needing a restart.
            known = daemon_workspaces()
            out = []
            for ws in workspace_dirs():
                opened = known.get(str(ws.resolve()))
                if opened is None:
                    opened = open_in_daemon(ws)
                    if opened is not None:
                        known = daemon_workspaces()
                        opened = known.get(str(ws.resolve()))
                out.append(describe(ws, opened))
            return self._send_json(200, {"workspaces": out})

        if method == "POST" and not rest:
            return self._create()

        parts = rest.split("/")
        slug = parts[0]
        if not SAFE_NAME.match(slug):
            return self._send_json(400, {"error": "invalid workspace name"})
        ws = WORKSPACES / slug
        if ws.is_symlink() or not ws.is_dir():
            return self._send_json(404, {"error": f"no such workspace: {slug}"})

        if method == "POST" and parts[1:] == ["prompt"]:
            return self._prompt(ws)
        if method == "POST" and parts[1:] == ["version"]:
            return self._open_version(ws)
        if method == "GET" and parts[1:] == ["history"]:
            return self._history(ws)
        if method == "GET" and parts[1:] == ["export"]:
            return self._send_json(200, export_state(ws))
        if method == "POST" and parts[1:] == ["export"]:
            return self._export_build(ws)
        if method == "GET" and parts[1:] == ["download"]:
            return self._download(ws)
        if method == "GET" and parts[1:] == ["file"]:
            return self._ws_file(ws)
        if parts[1:] == ["project"] and method in ("GET", "POST"):
            return self._project(ws, method)
        if parts[1:] == ["project-preview"] and method == "POST":
            return self._project_preview_job(ws)
        if method == "DELETE" and len(parts) == 1:
            return self._delete(ws)
        return self._send_json(404, {"error": "unknown workspaces route"})

    def _project(self, ws: Path, method: str):
        query = parse_qs(urlparse(self.path).query)
        body = self._read_json() if method == "POST" else {}
        relative = body.get("project", query.get("project", [""])[0])
        try:
            root = projectio.project_root(ws, relative)
            if method == "GET":
                data = projectio.state(ws, relative)
                data["available_projects"] = [p.name for p in workspace_dirs() if p != ws]
                return self._send_json(200, data)
        except (ValueError, OSError) as exc:
            return self._send_json(400, {"error": str(exc)})
        save_only = body.get("action") in ("save_definition", "save_source") and body.get("build") is False
        # Save-only requests validate and write files without waiting for CAD.
        # Workers verify fingerprints after finishing and discard raced builds.
        lock = mutation_lock(ws.name)
        cad_lock = None if save_only else build_lock(ws.name)
        # Legacy build-and-save actions may wait behind a preview worker.
        # Do not reserve the file mutation lock while they wait for CAD.
        if cad_lock and not cad_lock.acquire(timeout=BUILD_TIMEOUT_S):
            return self._send_json(409, {"error": "a build is already running here"})
        if not lock.acquire(timeout=BUILD_TIMEOUT_S):
            if cad_lock:
                cad_lock.release()
            return self._send_json(409, {"error": "a project change is already running here"})
        try:
            expected = body.get("revision")
            if expected and expected != projectio.revision(root):
                return self._send_json(409, {"error": "project definitions changed; reload before saving"})
            action = body.get("action")
            data = projectio.manifest(root)
            preview = None
            if action == "preview":
                preview = self._project_preview(ws, root, relative, body["kind"], body["name"], body.get("config", {}))
            elif action == "discover":
                self._project_run(root, ["project", "discover"])
            elif action == "initialize":
                self._project_run(root, ["project", "discover"])
                projectio.upgrade(root, APP)
                self._project_run(root, ["export"])
            elif action == "create_component":
                data = projectio.upgrade(root, APP)
                name = projectio.new_component(root, data, body["label"], body.get("recipe", "box"), body.get("hardware"))
                projectio.validate(data, root)
                projectio.write(root / "cad/project.json", data)
                preview = self._project_preview(ws, root, relative, "component", name)
                body["created"] = name
            elif action == "save_definition":
                data = projectio.upgrade(root, APP)
                kind, name = body["kind"], body["name"]
                key = {"component": "components", "assembly": "assemblies", "scene": "scenes"}.get(kind)
                if not key or not projectio.NAME.fullmatch(name):
                    raise ValueError("invalid definition kind or name")
                previous = (root / "cad/project.json").read_bytes()
                data.setdefault(key, {})[name] = body["definition"]
                projectio.validate(data, root)
                projectio.write(root / "cad/project.json", data)
                definition = body["definition"]
                try:
                    if not save_only and not (kind in ("assembly", "scene") and isinstance(definition, dict)
                            and definition.get("instances") == []):
                        preview = self._project_preview(ws, root, relative, kind, name)
                    if not save_only and ((kind in ("component", "assembly") and not (isinstance(definition, dict) and definition.get("instances") == [])) or data.get("active_scene", data["default_scene"]) == name):
                        self._project_run(root, ["export"])
                except Exception:
                    (root / "cad/project.json").write_bytes(previous)
                    raise
            elif action == "activate_scene":
                data = projectio.upgrade(root, APP)
                name = body["name"]
                if name not in data["scenes"]:
                    raise ValueError("unknown scene")
                previous = (root / "cad/project.json").read_bytes()
                data["active_scene"] = name
                projectio.write(root / "cad/project.json", data)
                try:
                    self._project_run(root, ["export"])
                except Exception:
                    (root / "cad/project.json").write_bytes(previous)
                    raise
            elif action == "save_source":
                source = body["path"]
                path = (root / source).resolve()
                if not path.is_relative_to(root.resolve() / "cad") or path.suffix != ".py" or not path.is_file() or "kits" in path.relative_to(root / "cad").parts:
                    raise ValueError("source must be an existing Python file in this project's cad/")
                text = body["text"]
                compile(text, str(path), "exec")
                path.write_text(text)
                if not save_only:
                    preview = self._project_preview(ws, root, relative, body["kind"], body["name"])
                    self._project_run(root, ["export"])
            elif action == "include_project":
                target = body["target"]
                name = body.get("name") or target
                if not projectio.NAME.fullmatch(name) or not projectio.NAME.fullmatch(target):
                    raise ValueError("choose an existing project and a valid local name")
                sibling = WORKSPACES / target
                if sibling == root or not (sibling / ".git").exists():
                    raise ValueError("choose another Git project")
                if not (sibling / "cad/project.json").is_file():
                    raise ValueError("enable the included project library and commit it in its own Git view first")
                # Changes in a sibling remain owned by that repository. A
                # submodule can only clone committed definitions.
                if projectio.git(sibling, "status", "--porcelain"):
                    raise ValueError("commit the included project's definitions in its own Git view first")
                self._project_run(root, ["sub", "add", str(sibling), "--as", name])
            elif action == "sync":
                self._project_run(root, ["sub", "sync"])
            elif action == "commit":
                message = body.get("message", "").strip()
                if not message:
                    raise ValueError("enter a commit message")
                projectio.git(root, "add", "--all", check=True)
                projectio.git(root, "commit", "-m", message, check=True)
            elif action == "stage_pin":
                if not relative:
                    raise ValueError("choose an included project to stage its pin")
                parent = root.parent.parent.parent
                pin = str(root.relative_to(parent))
                projectio.git(parent, "add", "--", pin, check=True)
            else:
                raise ValueError("unknown project action")
            result = projectio.state(ws, relative)
            result.update({"preview": preview, "created": body.get("created")})
            result["available_projects"] = [p.name for p in workspace_dirs() if p != ws]
            return self._send_json(200, result)
        except subprocess.TimeoutExpired:
            return self._send_json(504, {"error": "the CAD build timed out; the previous preview is retained"})
        except ProjectBuildError as exc:
            return self._send_json(422, {"error": "CAD build failed", "log": str(exc)})
        except (ValueError, KeyError, OSError, SyntaxError) as exc:
            return self._send_json(400, {"error": str(exc)})
        finally:
            if cad_lock:
                cad_lock.release()
            lock.release()

    def _project_run(self, root, arguments):
        ok, log = run_tool(root, arguments)
        if not ok:
            raise ProjectBuildError(log)
        return log

    def _project_preview_job(self, ws):
        body = self._read_json()
        try:
            relative = body.get("project", "")
            root = projectio.project_root(ws, relative)
            job = PREVIEWS.request(ws, root, relative, body["kind"], body["name"], body.get("config", {}),
                                   background=bool(body.get("background")), retry=bool(body.get("retry")),
                                   build=body.get("build", True) is not False, force=bool(body.get("force")))
            return self._send_json(200, job)
        except (ValueError, KeyError, OSError) as exc:
            return self._send_json(400, {"error": str(exc)})

    def _project_preview(self, ws, root, relative, kind, name, configuration=None):
        destination, arguments = project_preview_spec(ws, root, relative, kind, name, configuration)
        if not preview_ready(destination):
            self._project_run(root, arguments)
        if not preview_ready(destination):
            raise ProjectBuildError("CAD did not produce a complete preview")
        current, _ = project_preview_spec(ws, root, relative, kind, name, configuration)
        if current != destination:
            shutil.rmtree(destination, ignore_errors=True)
            raise ProjectBuildError("Source changed during the preview build; request the updated model.")
        directory = str(destination.relative_to(ws / "out"))
        index = PREVIEWS._index_path(ws, relative, kind, name, configuration)
        with PREVIEWS.condition:
            projectio.write(index, {"source": destination.name, "directory": directory})
        return directory

    # ---------------------------------------------------------------- export
    def _export_build(self, ws: Path):
        """Build the asked-for formats, synchronously. {formats, parts, all}

        Synchronous because a rebuild is usually a no-op (the tool skips what is
        already newer than cad/), because the daemon's process API returns no
        pane id to follow, and because the caller wants the files in the same
        gesture that asked for them.
        """
        body = self._read_json()
        wanted = [f for f in (body.get("formats") or []) if isinstance(f, str)]
        unknown = [f for f in wanted if f not in EXPORT_IDS]
        if unknown:
            return self._send_json(400, {"error": f"unknown format: {', '.join(unknown)}"})
        if not wanted:
            return self._send_json(400, {"error": "nothing selected to build"})

        # One `caliper bundle` for every geometry format at once — they share a
        # tessellation, so asking for them separately would pay for it twice.
        jobs = []
        geometry = [f for f in wanted if f in BUNDLE_IDS]
        if geometry:
            cmd = ["bundle", "--formats", ",".join(geometry)]
            if body.get("parts"):
                cmd.append("--parts")
            if body.get("all"):
                cmd.append("--all")
            if body.get("force"):
                cmd.append("--force")
            jobs.append(cmd)
        if "views" in wanted:
            jobs.append(["render"])
        if "print" in wanted:
            jobs.append(["print"])

        lock = build_lock(ws.name)
        if not lock.acquire(blocking=False):
            return self._send_json(409, {"error": "a build is already running here"})
        t0, logs = time.time(), []
        try:
            for cmd in jobs:
                ok, log = run_tool(ws, cmd)
                logs.append(log)
                if not ok:
                    # Everything said so far, not just the failing command: the
                    # earlier output is often where the reason is.
                    return self._send_json(500, {
                        "error": f"caliper {cmd[0]} failed", "log": "\n".join(logs)})
        except subprocess.TimeoutExpired:
            return self._send_json(504, {
                "error": f"caliper gave up after {BUILD_TIMEOUT_S // 60} minutes"})
        finally:
            lock.release()
        return self._send_json(200, {"ok": True, "seconds": round(time.time() - t0, 1),
                                     "log": "\n".join(logs), **export_state(ws)})

    def _download(self, ws: Path):
        """?path=… (attachment) or several ?path= (one zip). Paths are under out/."""
        asked = parse_qs(urlparse(self.path).query).get("path") or []
        files = []
        for rel in asked:
            target = out_file(ws, rel)
            if target is None or not target.is_file():
                return self._send_json(404, {"error": f"no such artifact: {rel}"})
            files.append(target)
        if not files:
            return self._send_json(400, {"error": "nothing asked for"})

        if len(files) == 1:
            data = files[0].read_bytes()
            name = files[0].name
        else:
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                for f in files:
                    z.write(f, arcname=str(f.relative_to((ws / "out").resolve())))
            data = buf.getvalue()
            name = f"{ws.name}-export.zip"

        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Disposition", f'attachment; filename="{name}"')
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _ws_file(self, ws: Path):
        """?path=… — one image out of the workspace's working tree, as bytes.

        The Dock loads a file's text through the daemon, which is right for a
        `.svg` but garbage for a `.png`; an <img> needs the raw bytes, so this
        streams them. Contained to the workspace and to image types only.
        """
        rel = (parse_qs(urlparse(self.path).query).get("path") or [""])[0]
        target = ws_file(ws, rel)
        if target is None or not target.is_file() or target.suffix.lower() not in IMAGE_EXTS and not (target.suffix == ".py" and target.is_relative_to((ws / "cad").resolve())):
            return self._send_json(404, {"error": f"no such file: {rel}"})
        data = target.read_bytes()
        ctype = "text/plain; charset=utf-8" if target.suffix == ".py" else (mimetypes.guess_type(target.name)[0] or "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _open_version(self, ws: Path):
        """Check an old commit out on a branch of its own.

        The daemon's own checkout can only branch from HEAD, so going back to a
        specific commit has to happen here — otherwise "open this version"
        would quietly leave you on the current one.
        """
        rev = (self._read_json().get("rev") or "").strip()
        if not re.fullmatch(r"[0-9a-fA-F]{4,40}", rev):
            return self._send_json(400, {"error": "not a commit id"})
        if git(ws, "status", "--porcelain").strip():
            return self._send_json(409, {
                "error": "commit or discard the current changes first — "
                         "opening an old version would carry them along"})
        # If a branch already points exactly at this commit — the design's own
        # `main` at its tip, most often — go back to *that* branch rather than
        # minting a version-* one. That is how "return to latest" lands you on
        # main again instead of a side branch you can never leave.
        for name in git(ws, "branch", "--format=%(refname:short)",
                        "--points-at", rev).splitlines():
            name = name.strip()
            if name and not name.startswith("version-"):
                done = subprocess.run(["git", "-C", str(ws), "checkout", "-q", name],
                                      capture_output=True, text=True)
                if done.returncode == 0:
                    return self._send_json(200, {"branch": name, "rev": rev})

        branch = f"version-{rev[:7]}"
        made = subprocess.run(["git", "-C", str(ws), "checkout", "-q", "-b", branch, rev],
                              capture_output=True, text=True)
        if made.returncode != 0:
            # Already been here before: just go back to that branch.
            back = subprocess.run(["git", "-C", str(ws), "checkout", "-q", branch],
                                  capture_output=True, text=True)
            if back.returncode != 0:
                return self._send_json(500, {
                    "error": (made.stderr or back.stderr or "checkout failed").strip()})
        return self._send_json(200, {"branch": branch, "rev": rev})

    def _history(self, ws: Path):
        """The design's whole commit timeline, plus where HEAD sits now.

        The daemon's recent_commits is HEAD-relative, so after opening an old
        version the newer commits fall off it and there is no way forward.
        Reading every ref here keeps the newest commit present whatever is
        checked out, and `head` lets the UI mark where you are.
        """
        log = git(ws, "log", "--all", "--date-order", "--no-color",
                  "--pretty=%H\x1f%s\x1f%cr")
        commits = []
        for line in log.splitlines():
            sha, summary, when = (line.split("\x1f") + ["", "", ""])[:3]
            if sha:
                commits.append({"id": sha, "summary": summary, "when": when})
        return self._send_json(200, {
            "commits": commits,
            "head": git(ws, "rev-parse", "HEAD"),
        })

    def _create(self):
        body = self._read_json()
        slug = slugify(body.get("name") or "")
        brief = (body.get("brief") or "").strip()
        agent_type = body.get("agentType") or "claude"
        if body.get("agent"):
            status, types = daemon("GET", "/v1/agents")
            if status != 200 or not isinstance(types, list):
                return self._send_json(502, {"error": "could not load the daemon's agent registry"})
            if agent_type not in types:
                return self._send_json(400, {"error": f"agent is not configured: {agent_type}"})
        if not SAFE_NAME.match(slug):
            return self._send_json(400, {
                "error": "give it a name of letters, digits and dashes"})
        if (WORKSPACES / slug).exists():
            return self._send_json(409, {"error": f"{slug} already exists"})
        if not TEMPLATE.is_dir():
            return self._send_json(500, {"error": f"no template at {TEMPLATE}"})

        try:
            ws = scaffold(slug, brief)
        except (OSError, subprocess.CalledProcessError) as e:
            return self._send_json(500, {"error": f"could not create {slug}: {e}"})
        if body.get("agent") and agent_type == "claude":
            trust_for_claude(ws)

        opened = open_in_daemon(ws)
        if opened is None:
            return self._send_json(502, {
                "slug": slug,
                "error": "created on disk, but the daemon would not open it"})

        result = {"slug": slug, "id": opened.get("id")}
        if body.get("agent"):
            status, started = daemon("POST", f"/v1/workspaces/{opened['id']}/agents",
                                    {"type": agent_type})
            result["agent"] = status in (200, 201)
            if not result["agent"]:
                message = started.get("error") if isinstance(started, dict) else None
                result["warning"] = f"Workspace created; {agent_type} could not start. {message or 'Open a shell to check installation and login.'}"
            # Brief is already committed in all provider instruction files.
            # Login/trust/theme prompts must not swallow a blind timed paste.
        return self._send_json(201, result)

    def _prompt(self, ws: Path):
        """Type into an agent's pane: {text, pane?}. Without `pane`, the newest."""
        body = self._read_json()   # the request body can only be read once
        text = (body.get("text") or "").strip()
        if not text:
            return self._send_json(400, {"error": "nothing to send"})
        opened = daemon_workspaces().get(str(ws.resolve()))
        if not opened:
            return self._send_json(409, {"error": "that workspace is not open"})
        pane = body.get("pane")
        target = pane if isinstance(pane, int) else agent_pane(opened["id"])
        if target is None:
            return self._send_json(409, {"error": "no agent is running here yet"})
        ok = send_to_pane(opened["id"], target, text)
        return self._send_json(200 if ok else 502, {"sent": ok, "pane": target})

    def _delete(self, ws: Path):
        """Close it in the daemon, then move it aside. Never delete a design."""
        opened = daemon_workspaces().get(str(ws.resolve()))
        if opened:
            daemon("DELETE", f"/v1/workspaces/{opened['id']}")
        trash = WORKSPACES / ".trash"
        trash.mkdir(exist_ok=True)
        dest = trash / f"{ws.name}-{time.strftime('%Y%m%d-%H%M%S')}"
        try:
            shutil.move(str(ws), str(dest))
        except OSError as e:
            return self._send_json(500, {"error": f"could not move it aside: {e}"})
        return self._send_json(200, {"removed": ws.name, "kept_at": str(dest)})

    # ------------------------------------------------------------------ proxy
    def _proxy_butai(self, method: str):
        """Relay /butai/api/<rest>[?query] -> daemon /v1/<rest>[?query]."""
        rest = self.path[len(API_PREFIX):]  # keeps any ?query
        target = "/v1/" + rest
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        ctype = self.headers.get("Content-Type") or "application/octet-stream"
        status, resp_ctype, resp_body = daemon_call(method, target, body, ctype)
        self.send_response(status)
        self.send_header("Content-Type", resp_ctype)
        self.send_header("Content-Length", str(len(resp_body)))
        self.end_headers()
        self.wfile.write(resp_body)

    # ----------------------------------------------------------------- routes
    def do_GET(self):
        if not self._browser_allowed():
            return
        path = self.path.split("?", 1)[0]
        if path == "/login":
            return self._login_page() if TOKEN else self._redirect("/")
        if not self._authed():
            return self._deny()
        if path == "/ws":
            # Hijacks the socket for the rest of this connection's lifetime.
            self.close_connection = True
            return relay_ws(self)
        if self.path.startswith(API_PREFIX):
            return self._proxy_butai("GET")
        if self.path.startswith(WS_API):
            return self._workspaces("GET")
        # The SPA entry: `/` (and a bare `/index.html`) serve the built app.
        # Routing is client-side (HashRouter), so no deep-link fallback needed.
        if path in ("/", "/index.html"):
            self.path = "/index.html"
        return super().do_GET()

    def do_HEAD(self):
        if not self._browser_allowed():
            return
        if not self._authed():
            return self._deny()
        return super().do_HEAD()

    def do_POST(self):
        if not self._browser_allowed():
            return
        if self.path.split("?", 1)[0] == "/login" and TOKEN:
            return self._do_login()
        if not self._authed():
            return self._deny()
        if not self._same_origin():
            return self._send_json(403, {"error": "cross-site request refused"})
        if self.path.startswith(API_PREFIX):
            return self._proxy_butai("POST")
        if self.path.startswith(WS_API):
            return self._workspaces("POST")
        self.send_error(405, "POST is only for /butai/api/ and /api/workspaces")

    def do_DELETE(self):
        if not self._browser_allowed():
            return
        if not self._authed():
            return self._deny()
        if not self._same_origin():
            return self._send_json(403, {"error": "cross-site request refused"})
        if self.path.startswith(API_PREFIX):
            return self._proxy_butai("DELETE")
        if self.path.startswith(WS_API):
            return self._workspaces("DELETE")
        self.send_error(405, "DELETE is only for /butai/api/ and /api/workspaces")

    def _redirect(self, to: str):
        self.send_response(302)
        self.send_header("Location", to)
        self.end_headers()

    def send_response(self, code, message=None):
        self._response_status = code
        super().send_response(code, message)

    def end_headers(self):
        self.send_header("Cache-Control", response_cache_policy(self.path, getattr(self, "_response_status", 0)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        if self.path.startswith("/w/"):
            # Workspace output may contain HTML/SVG supplied by a model. A
            # direct navigation must not execute it in the workbench's origin.
            self.send_header("Content-Security-Policy", "sandbox; default-src 'none'; style-src 'unsafe-inline'")
        super().end_headers()

    def log_message(self, *a):  # quiet
        pass


# The first screen anyone sees, and the one surface with no CSS pipeline: these
# hexes mirror the tokens in web/src/index.css and the mark mirrors
# web/src/components/Logo.tsx. Change either there and change it here too —
# docs/DESIGN.md names this as the one sanctioned place to hardcode the palette.
LOGIN_HTML = """<!doctype html>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>caliper</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23e6edf6' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M14 4H8a3 3 0 0 0-3 3v10a3 3 0 0 0 3 3h6'/%3E%3Cpath d='M14 4h5'/%3E%3C/svg%3E">
<style>
  body { background:#0b0f17; color:#e6edf6; height:100vh; margin:0; display:grid;
         place-items:center; font:15px/1.6 ui-sans-serif, system-ui, sans-serif; }
  form { background:#131a26; border:1px solid #223049; border-radius:12px;
         padding:26px 28px; width:min(360px, 90vw); display:grid; gap:14px; }
  .lockup { display:flex; align-items:center; gap:9px; }
  .lockup svg { flex:none; }
  h1 { margin:0; font-size:17px; font-weight:650; letter-spacing:-0.01em; }
  h1 .tag { color:#8b9bb4; font-weight:400; }
  p { margin:0; color:#8b9bb4; font-size:13px; }
  input { background:#0f1626; border:1px solid #2c3d5e; border-radius:8px;
          padding:9px 11px; color:#e6edf6; font:inherit; }
  input:focus { outline:none; border-color:#3b82f6; }
  button { background:#3b82f6; border:0; border-radius:8px; padding:9px 11px;
           color:#fff; font:inherit; font-weight:600; cursor:pointer; }
  button:hover { background:#2f76ee; }
  .err { color:#f85149; font-size:13px; }
</style>
<form method="post" action="/login">
  <div class="lockup">
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <path d="M14 4H8a3 3 0 0 0-3 3v10a3 3 0 0 0 3 3h6"/>
      <path d="M14 4h5" stroke="#3b82f6"/>
    </svg>
    <h1>caliper <span class="tag">· agentic CAD</span></h1>
  </div>
  <p>This workbench can run commands in its container, so it asks for the token
     from your <code>.env</code>.</p>
  <input type="password" name="token" placeholder="WEB_TOKEN" autofocus>
  <div class="err">{{msg}}</div>
  <button type="submit">Open</button>
</form>
"""


if __name__ == "__main__":
    WORKSPACES.mkdir(parents=True, exist_ok=True)
    threading.Thread(target=adopt_all, daemon=True).start()
    httpd = ThreadingHTTPServer((SERVER_BIND, PORT), partial(Handler, directory=str(SERVE_DIR)))
    guard = "token required" if TOKEN else "no token — open access (optional: set WEB_TOKEN to require one)"
    print(f"caliper on http://{SERVER_BIND}:{PORT}/  ({guard})")
    print(f"  app        {APP}")
    print(f"  workspaces {WORKSPACES}")
    print(f"  daemon     {butai_socket_path()}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
