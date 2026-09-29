"""HTTP boundary regressions; no daemon, credentials or agent sessions needed."""
import http.client
import importlib.util
from functools import partial
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

APP = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("security_test_server", APP / "web/server.py")
server = importlib.util.module_from_spec(spec)
with patch.object(sys, "argv", ["server.py"]):
    spec.loader.exec_module(server)


class SecurityTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.dist = self.root / "dist"
        self.dist.mkdir()
        (self.dist / "index.html").write_text("public app")
        (self.root / ".env").write_text("private configuration")
        self.ws = self.root / "workspaces" / "example"
        (self.ws / "out").mkdir(parents=True)
        (self.ws / "cad").mkdir()
        (self.ws / "out" / "scene.json").write_text("{}")
        (self.ws / "out" / "page.html").write_text("<script>alert(1)</script>")
        for name, value in {"DIST": self.dist, "WORKSPACES": self.ws.parent, "TOKEN": ""}.items():
            patcher = patch.object(server, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.http = server.ThreadingHTTPServer(("127.0.0.1", 0), partial(server.Handler, directory=str(self.dist)))
        thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.http.server_close)
        self.addCleanup(self.http.shutdown)

    def request(self, path, method="GET", headers=None, body=None):
        conn = http.client.HTTPConnection(*self.http.server_address, timeout=3)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            response = conn.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            conn.close()

    def test_missing_build_does_not_serve_repository(self):
        (self.dist / "index.html").unlink()
        for path in ("/", "/.env", "/%2eenv", "/../.env", "/.git/config", "/web/server.py"):
            with self.subTest(path=path):
                self.assertEqual(self.request(path)[0], 404)

    def test_static_files_but_no_listing_or_symlink_escape(self):
        (self.dist / "assets").mkdir()
        (self.dist / "escape.txt").symlink_to(self.root / ".env")
        self.assertEqual(self.request("/")[2], b"public app")
        for method in ("GET", "HEAD"):
            for path in ("/assets/", "/escape.txt"):
                self.assertEqual(self.request(path, method)[0], 404)

    def test_artifacts_and_downloads_refuse_traversal(self):
        (self.ws / "out" / "escape.txt").symlink_to(self.root / ".env")
        self.assertEqual(self.request("/w/example/out/scene.json")[0], 200)
        for path in ("../cad/model.py", "%2e%2e/%2e%2e/.env", "escape.txt", "%00"):
            with self.subTest(path=path):
                self.assertEqual(self.request("/w/example/out/" + path)[0], 404)
                self.assertEqual(self.request("/api/workspaces/example/download?path=" + path)[0], 404)

    def test_symlinked_output_root_and_workspace_are_refused(self):
        other = self.ws.parent / "other"
        other.mkdir()
        (other / "out").symlink_to(self.dist, target_is_directory=True)
        (self.ws.parent / "linked").symlink_to(self.ws, target_is_directory=True)
        self.assertEqual(self.request("/w/other/out/index.html")[0], 404)
        self.assertEqual(self.request("/w/linked/out/scene.json")[0], 404)
        self.assertEqual(self.request("/api/workspaces/linked/history")[0], 404)
        self.assertNotIn(self.ws.parent / "linked", server.workspace_dirs())

    def test_token_guards_files_api_and_websocket(self):
        with patch.object(server, "TOKEN", "test password"):
            for path in ("/", "/w/example/out/scene.json", "/api/workspaces", "/butai/api/workspaces", "/ws"):
                self.assertEqual(self.request(path)[0], 401)
            self.assertEqual(self.request("/", "HEAD")[0], 401)
            status, headers, _ = self.request("/login", "POST", body=urlencode({"token": "test password"}))
            self.assertEqual(status, 302)
            cookie = headers["Set-Cookie"]
            self.assertIn("HttpOnly", cookie)
            self.assertIn("SameSite=Strict", cookie)
            self.assertEqual(self.request("/", headers={"Cookie": cookie.split(";")[0]})[0], 200)
            self.assertEqual(self.request("/", headers={"Cookie": "caliper_token=%C3%A9"})[0], 401)

    def test_cross_site_get_write_login_and_websocket_are_refused(self):
        for token in ("", "test password"):
            with patch.object(server, "TOKEN", token):
                for method, path in (("GET", "/"), ("GET", "/ws"), ("POST", "/login"),
                                     ("POST", "/api/workspaces"), ("DELETE", "/api/workspaces/example")):
                    for headers in ({"Origin": "https://attacker.invalid"}, {"Sec-Fetch-Site": "cross-site"}):
                        self.assertEqual(self.request(path, method, headers, body="")[0], 403)

    def test_tokenless_dns_rebinding_and_remote_hosts_are_refused(self):
        for host in ("attacker.invalid", "192.0.2.1", "localhost.attacker.invalid"):
            self.assertEqual(self.request("/", headers={"Host": host})[0], 403)
        self.assertEqual(self.request("/", headers={"Host": "localhost:8017"})[0], 200)

    def test_active_artifacts_are_sandboxed(self):
        status, headers, _ = self.request("/w/example/out/page.html")
        self.assertEqual(status, 200)
        self.assertIn("sandbox", headers["Content-Security-Policy"])
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(headers["Referrer-Policy"], "no-referrer")


if __name__ == "__main__":
    unittest.main()
