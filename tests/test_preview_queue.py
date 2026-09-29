"""Preview caching/concurrency checks without loading OCCT or the daemon."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch


APP = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("caliper_preview_server", APP / "web/server.py")
server = importlib.util.module_from_spec(spec)
with patch.object(sys, "argv", ["server.py"]):
    spec.loader.exec_module(server)


class PreviewQueueTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "preview-test"
        (self.root / "cad").mkdir(parents=True)
        self.source = self.root / "cad/part.py"
        self.source.write_text("width = 10\n")
        (self.root / "cad/project.json").write_text(json.dumps({
            "version": 1, "default_scene": "main", "components": {
                "a": {"builder": "part:build"}, "b": {"builder": "part:build"}},
            "assemblies": {}, "scenes": {"main": {"instances": []}},
        }))
        self.queue = server.PreviewQueue()

    def request(self, name="a", **options):
        return self.queue.request(self.root, self.root, "", "component", name, **options)

    def wait_finished(self, name="a"):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            result = self.request(name)
            if result["status"] in ("ready", "failed"):
                return result
            time.sleep(0.01)
        self.fail("preview worker did not finish")

    @staticmethod
    def artifacts(arguments):
        destination = Path(arguments[arguments.index("--out") + 1])
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "scene.json").write_text("{}")
        (destination / "model.glb").write_bytes(b"geometry")

    def test_source_content_deletion_and_assets_invalidate_cache(self):
        original = server.preview_fingerprint(self.root)
        stamp = self.source.stat()
        self.source.write_text("width = 11\n")
        os.utime(self.source, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        edited = server.preview_fingerprint(self.root)
        self.assertNotEqual(original, edited)
        self.source.unlink()
        deleted = server.preview_fingerprint(self.root)
        self.assertNotEqual(edited, deleted)
        (self.root / "cad/shape.step").write_bytes(b"CAD asset")
        self.assertNotEqual(deleted, server.preview_fingerprint(self.root))
        cached = server.preview_fingerprint(self.root)
        (self.root / "cad/__pycache__").mkdir()
        (self.root / "cad/__pycache__/part.pyc").write_bytes(b"bytecode")
        self.assertEqual(cached, server.preview_fingerprint(self.root))

    def test_browser_caches_only_successful_content_addressed_files(self):
        immutable = "private, max-age=31536000, immutable"
        preview = "/w/design/out/project-previews/0123456789abcdef0123/model.glb"
        self.assertEqual(server.response_cache_policy(preview, 200), immutable)
        self.assertEqual(server.response_cache_policy(preview + "?t=123", 200), immutable)
        self.assertEqual(server.response_cache_policy("/assets/index-AbcD1234.js", 200), immutable)
        self.assertEqual(server.response_cache_policy(preview, 404), "no-store")
        self.assertEqual(server.response_cache_policy(preview, 401), "no-store")
        self.assertEqual(server.response_cache_policy("/w/design/out/model.glb", 200), "no-store")
        self.assertEqual(server.response_cache_policy("/api/workspaces/design/project", 200), "no-store")
        self.assertEqual(server.response_cache_policy("/assets/index.js", 200), "no-store")
        self.assertEqual(server.response_cache_policy("/", 200), "no-store")

    def test_duplicate_requests_share_one_build_and_disk_cache(self):
        started, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        def run(root, arguments):
            started.set()
            release.wait(5)
            self.artifacts(arguments)
            return True, "built"
        with patch.object(server, "run_tool", side_effect=run) as runner:
            first = self.request()
            self.assertIn(first["status"], ("queued", "building"))
            self.assertTrue(started.wait(2))
            duplicate = self.request()
            self.assertEqual(duplicate["status"], "building")
            self.assertEqual(first["directory"], duplicate["directory"])
            release.set()
            self.assertEqual(self.wait_finished()["status"], "ready")
            self.assertEqual(self.request()["status"], "ready")
            self.assertEqual(runner.call_count, 1)
            # A restarted server finds the same completed files immediately.
            self.assertEqual(server.PreviewQueue().request(self.root, self.root, "", "component", "a")["status"], "ready")

    def test_cache_only_browse_never_starts_cad(self):
        with patch.object(server, "run_tool") as runner:
            self.assertEqual(self.request(build=False)["status"], "missing")
            self.assertEqual(self.request("b", build=False)["status"], "missing")
            runner.assert_not_called()
            self.assertEqual(self.queue.jobs, {})

    def test_in_progress_files_are_not_published_as_successful_cache(self):
        written, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        def run(root, arguments):
            self.artifacts(arguments)
            written.set()
            release.wait(5)
            return False, "export failed after writing files"
        with patch.object(server, "run_tool", side_effect=run):
            self.request()
            self.assertTrue(written.wait(2))
            pending = self.request(build=False)
            self.assertEqual(pending["status"], "building")
            self.assertNotIn("cached_directory", pending)
            index = self.queue._index_path(self.root, "", "component", "a", {})
            self.assertFalse(index.exists())
            release.set()
            self.assertEqual(self.wait_finished()["status"], "failed")

    def test_synchronous_preview_retains_last_geometry_after_edit(self):
        handler = server.Handler.__new__(server.Handler)
        def run(root, arguments):
            self.artifacts(arguments)
            return True, "built"
        with patch.object(server, "run_tool", side_effect=run):
            directory = handler._project_preview(self.root, self.root, "", "component", "a")
        self.source.write_text("width = 20\n")
        with patch.object(server, "run_tool") as runner:
            stale = self.request(build=False)
            self.assertEqual(stale["status"], "stale")
            self.assertEqual(stale["directory"], directory)
            runner.assert_not_called()

    def test_cache_only_retains_last_preview_after_edit_and_restart(self):
        def run(root, arguments):
            self.artifacts(arguments)
            return True, "built"
        with patch.object(server, "run_tool", side_effect=run):
            first = self.wait_finished()
        self.source.write_text("width = 12\n")
        restarted = server.PreviewQueue()
        with patch.object(server, "run_tool") as runner:
            stale = restarted.request(self.root, self.root, "", "component", "a", build=False)
            self.assertEqual(stale["status"], "stale")
            self.assertEqual(stale["directory"], first["directory"])
            self.assertEqual(restarted.request(self.root, self.root, "", "component", "b", build=False)["status"], "missing")
            runner.assert_not_called()

    def test_force_build_uses_new_immutable_directory_and_survives_restart(self):
        started, release = threading.Event(), threading.Event()
        def run(root, arguments):
            self.artifacts(arguments)
            return True, "built"
        with patch.object(server, "run_tool", side_effect=run):
            first = self.wait_finished()
        def rebuild(root, arguments):
            started.set()
            release.wait(5)
            self.artifacts(arguments)
            return True, "rebuilt"
        self.addCleanup(release.set)
        with patch.object(server, "run_tool", side_effect=rebuild) as runner:
            forced = self.request(force=True)
            self.assertTrue(started.wait(2))
            self.assertNotEqual(first["directory"], forced["directory"])
            pending = self.request(build=False)
            self.assertEqual(pending["status"], "building")
            self.assertEqual(pending["cached_directory"], first["directory"])
            self.assertTrue(server.preview_ready(self.root / "out" / first["directory"]))
            release.set()
            complete = self.wait_finished()
            self.assertEqual(complete["directory"], forced["directory"])
            self.assertEqual(runner.call_count, 1)
        restarted = server.PreviewQueue()
        ready = restarted.request(self.root, self.root, "", "component", "a", build=False)
        self.assertEqual(ready["status"], "ready")
        self.assertEqual(ready["directory"], forced["directory"])

    def test_failed_force_build_keeps_previous_preview_and_reports_error(self):
        def run(root, arguments):
            self.artifacts(arguments)
            return True, "built"
        with patch.object(server, "run_tool", side_effect=run):
            first = self.wait_finished()
        with patch.object(server, "run_tool", return_value=(False, "build error")):
            self.request(force=True)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                status = self.request(build=False)
                if status["status"] == "failed":
                    break
                time.sleep(0.01)
            self.assertEqual(status["status"], "failed")
            self.assertEqual(status["cached_directory"], first["directory"])
            self.assertTrue(server.preview_ready(self.root / "out" / first["directory"]))

    def test_failed_build_with_complete_files_is_never_a_cache_hit(self):
        def fail(root, arguments):
            self.artifacts(arguments)
            return False, "export failed after writing artifacts"
        with patch.object(server, "run_tool", side_effect=fail):
            self.request()
            failed = self.wait_finished()
            self.assertEqual(failed["status"], "failed")
        destination = self.root / "out" / failed["directory"]
        self.assertFalse(destination.exists())
        restarted = server.PreviewQueue()
        self.assertEqual(restarted.request(self.root, self.root, "", "component", "a", build=False)["status"], "missing")

    def project_request(self, body, method="POST"):
        result = []
        handler = server.Handler.__new__(server.Handler)
        handler.path = "/api/workspaces/preview-test/project"
        handler._read_json = lambda: body
        handler._send_json = lambda status, data: result.append((status, data))
        with patch.object(server, "workspace_dirs", return_value=[]), \
             patch.object(server.projectio, "state", return_value={"manifest": {}}):
            handler._project(self.root, method)
        return result[0]

    def test_save_only_validates_without_cad_or_waiting_for_cad_lock(self):
        lock = server.build_lock(self.root.name)
        lock.acquire()
        try:
            with patch.object(server, "run_tool") as runner:
                status, _ = self.project_request({"action": "save_source", "path": "cad/part.py",
                                                 "text": "width = 30\n", "kind": "component", "name": "a", "build": False})
                self.assertEqual(status, 200)
                self.assertEqual(self.source.read_text(), "width = 30\n")
                definition = {"builder": "part:build", "parameters": {"width": 31}}
                status, _ = self.project_request({"action": "save_definition", "kind": "component", "name": "a",
                                                 "definition": definition, "build": False})
                self.assertEqual(status, 200)
                self.assertEqual(server.projectio.manifest(self.root)["components"]["a"], definition)
                runner.assert_not_called()
        finally:
            lock.release()

    def test_save_only_rejects_invalid_source_and_definition(self):
        original = self.source.read_text()
        status, _ = self.project_request({"action": "save_source", "path": "cad/part.py", "text": "invalid (", "build": False})
        self.assertEqual(status, 400)
        self.assertEqual(self.source.read_text(), original)
        original = (self.root / "cad/project.json").read_bytes()
        status, _ = self.project_request({"action": "save_definition", "kind": "component", "name": "a",
                                         "definition": {"instances": "invalid"}, "build": False})
        self.assertEqual(status, 400)
        self.assertEqual((self.root / "cad/project.json").read_bytes(), original)

    def test_project_get_does_not_warm_previews(self):
        with patch.object(server.PREVIEWS, "warm") as warm:
            status, _ = self.project_request({}, method="GET")
            self.assertEqual(status, 200)
            warm.assert_not_called()

    def test_selected_preview_precedes_queued_warming(self):
        order = []
        lock = server.build_lock(self.root.name)
        lock.acquire()
        def run(root, arguments):
            order.append(arguments[arguments.index("--name") + 1])
            self.artifacts(arguments)
            return True, "built"
        with patch.object(server, "run_tool", side_effect=run):
            try:
                self.request("a", background=True)
                self.request("b")
            finally:
                lock.release()
            self.assertEqual(self.wait_finished("b")["status"], "ready")
            self.assertEqual(self.wait_finished("a")["status"], "ready")
        self.assertEqual(order, ["b", "a"])

    def test_latest_selection_precedes_older_pending_selection(self):
        order = []
        lock = server.build_lock(self.root.name)
        lock.acquire()
        def run(root, arguments):
            order.append(arguments[arguments.index("--name") + 1])
            self.artifacts(arguments)
            return True, "built"
        with patch.object(server, "run_tool", side_effect=run):
            try:
                self.request("a")
                self.request("b")
            finally:
                lock.release()
            self.assertEqual(self.wait_finished("b")["status"], "ready")
            self.assertEqual(self.wait_finished("a")["status"], "ready")
        self.assertEqual(order, ["b", "a"])

    def test_partial_output_is_rebuilt_and_failure_requires_explicit_retry(self):
        destination, _ = server.project_preview_spec(self.root, self.root, "", "component", "a")
        destination.mkdir(parents=True)
        (destination / "scene.json").write_text("{}")
        with patch.object(server, "run_tool", return_value=(False, "invalid geometry")) as runner:
            self.assertIn(self.request()["status"], ("queued", "building"))
            failed = self.wait_finished()
            self.assertEqual(failed["status"], "failed")
            self.assertEqual(failed["log"], "invalid geometry")
            self.assertEqual(self.request()["status"], "failed")
            self.assertEqual(runner.call_count, 1)
        def run(root, arguments):
            self.artifacts(arguments)
            return True, "built"
        with patch.object(server, "run_tool", side_effect=run):
            self.request(retry=True)
            self.assertEqual(self.wait_finished()["status"], "ready")

    def test_source_change_during_build_never_poisons_the_old_cache(self):
        started, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        def run(root, arguments):
            started.set()
            release.wait(5)
            self.artifacts(arguments)
            return True, "built"
        with patch.object(server, "run_tool", side_effect=run) as runner:
            first = self.request()
            self.assertTrue(started.wait(2))
            self.source.write_text("width = 99\n")
            release.set()
            destination = self.root / "out" / first["directory"]
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                with self.queue.condition:
                    job = self.queue.jobs[str(destination.resolve())]
                    finished = job["status"] == "failed"
                if finished:
                    break
                time.sleep(0.01)
            self.assertTrue(finished)
            self.assertFalse(destination.exists())
            updated = self.wait_finished()
            self.assertEqual(updated["status"], "ready")
            self.assertNotEqual(first["directory"], updated["directory"])
            self.assertEqual(runner.call_count, 2)


if __name__ == "__main__":
    unittest.main()
