#!/usr/bin/env python3
"""Re-export the model whenever the CAD source changes.

Runs `export.py` once on startup, then again (debounced) on every save to a
`.py` file or project.json in cad/. This is the workspace's watcher, so
editing `model.py` — by hand or by the agent — refreshes out/model.glb +
scene.json, and the web viewer hot-reloads.

    python cad/watch.py

Two things keep this from eating the machine, both learned the hard way:

  * **Only content-changing events count.** Launching `python export.py` makes
    the interpreter *read* export.py, and inotify reports that as `opened` +
    `closed_no_write` on a `.py` path. Treating every event type as a change
    meant each export triggered the next one, forever.
  * **At most one export runs at a time.** Triggers set a flag that a single
    worker drains, so a burst of saves collapses into one re-export instead of
    starting an unbounded pile of concurrent OCCT tessellations.
"""

from __future__ import annotations

import subprocess
import os
import sys
import threading
import time
from pathlib import Path

from watchdog.events import (
    EVENT_TYPE_CLOSED,
    EVENT_TYPE_CREATED,
    EVENT_TYPE_MODIFIED,
    EVENT_TYPE_MOVED,
    FileSystemEventHandler,
)
from watchdog.observers import Observer

HERE = Path(__file__).resolve().parent
EXPORT = HERE / "export.py"
DEBOUNCE_S = 0.25

# Everything else — notably `opened` and `closed_no_write` — is a read, and a
# read is what our own subprocess does to export.py on every single run.
WRITE_EVENTS = frozenset({
    EVENT_TYPE_MODIFIED,
    EVENT_TYPE_CREATED,
    EVENT_TYPE_MOVED,
    EVENT_TYPE_CLOSED,  # IN_CLOSE_WRITE: a writer closed the file
})


def run_export() -> None:
    t0 = time.time()
    app = Path(os.environ.get("APP_DIR", "/opt/caliper"))
    cli = app / "bin/caliper"
    command = ([sys.executable, str(cli), "export"]
               if (HERE / "project.json").is_file() and cli.is_file()
               else [sys.executable, str(EXPORT)])
    proc = subprocess.run(command, cwd=str(HERE))
    dt = (time.time() - t0) * 1000
    tag = "ok" if proc.returncode == 0 else f"FAILED({proc.returncode})"
    print(f"[watch] export {tag} in {dt:.0f} ms", flush=True)


class Exporter:
    """Serializes exports: triggers set a flag, one worker drains it.

    Never runs two exports concurrently, and never queues more than one pending
    run no matter how many events arrive while an export is in flight.
    """

    def __init__(self) -> None:
        self._cv = threading.Condition()
        self._pending = False
        self._stop = False
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def trigger(self) -> None:
        with self._cv:
            self._pending = True
            self._cv.notify()

    def stop(self) -> None:
        with self._cv:
            self._stop = True
            self._cv.notify()

    def _loop(self) -> None:
        while True:
            with self._cv:
                while not self._pending and not self._stop:
                    self._cv.wait()
                if self._stop:
                    return
                self._pending = False
            # Let a burst of saves settle, then collapse them into one run.
            time.sleep(DEBOUNCE_S)
            with self._cv:
                self._pending = False
            run_export()


class Handler(FileSystemEventHandler):
    def __init__(self, exporter: Exporter) -> None:
        self.exporter = exporter

    def on_any_event(self, event) -> None:
        if event.is_directory or event.event_type not in WRITE_EVENTS:
            return
        paths = [Path(str(event.src_path))]
        if getattr(event, "dest_path", None):
            paths.append(Path(str(event.dest_path)))
        if not any((p.suffix == ".py" or p.name == "project.json")
                   and "__pycache__" not in p.parts for p in paths):
            return
        self.exporter.trigger()


def main() -> int:
    print("[watch] initial export…", flush=True)
    run_export()

    exporter = Exporter()
    exporter.start()
    observer = Observer()
    # Recursive: the model is split across cad/parts/, and edits there must
    # re-export too. The __pycache__ guard in Handler drops the extra noise.
    observer.schedule(Handler(exporter), str(HERE), recursive=True)
    observer.start()
    print(f"[watch] watching {HERE} (recursive) for *.py and project.json changes", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        exporter.stop()
    observer.join()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
