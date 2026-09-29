"""Provider creation checks without launching CLIs or connecting to a daemon."""
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

APP = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("provider_test_server", APP / "web/server.py")
server = importlib.util.module_from_spec(spec)
with patch.object(sys, "argv", ["server.py"]):
    spec.loader.exec_module(server)


class AgentProvidersTest(unittest.TestCase):
    def test_container_socket_ignores_host_daemon_environment(self):
        with patch.dict(os.environ, {"HOME": "/home/host", "BUTAI_SOCKET": "/tmp/host.sock", "XDG_RUNTIME_DIR": "/run/user/1000"}):
            self.assertEqual(server.butai_socket_path(), "/state/butai/butai.sock")

    def request(self, body):
        result = []
        handler = SimpleNamespace(_read_json=lambda: body,
                                  _send_json=lambda status, data: result.append((status, data)))
        server.Handler._create(handler)
        return result[0]

    def test_scaffold_commits_brief_for_each_provider(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(server, "WORKSPACES", Path(folder)), patch.dict(os.environ, {
                "GIT_AUTHOR_NAME": "Provider test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
                "GIT_COMMITTER_NAME": "Provider test", "GIT_COMMITTER_EMAIL": "test@example.invalid",
            }):
                workspace = server.scaffold("provider-design", "A 60 mm fan bracket")
                for name in ("CLAUDE.md", "AGENTS.md", "GEMINI.md"):
                    self.assertIn("A 60 mm fan bracket", (workspace / name).read_text())
                self.assertTrue((workspace / ".git").is_dir())

    def test_selected_provider_starts_without_timed_input(self):
        with tempfile.TemporaryDirectory() as folder:
            for provider in ("codex", "gemini", "claude"):
                with self.subTest(provider=provider), patch.object(server, "WORKSPACES", Path(folder)), \
                     patch.object(server, "scaffold", return_value=Path(folder) / "new-design"), \
                     patch.object(server, "open_in_daemon", return_value={"id": 7}), \
                     patch.object(server, "trust_for_claude") as trust, \
                     patch.object(server, "send_to_pane") as send, \
                     patch.object(server.time, "sleep") as sleep, \
                     patch.object(server, "daemon", side_effect=[(200, [provider]), (201, {"pane": 2})]) as daemon:
                    status, result = self.request({"name": "new-design", "brief": "A bracket", "agent": True, "agentType": provider})
                    self.assertEqual(status, 201)
                    self.assertTrue(result["agent"])
                    self.assertEqual(daemon.call_args.args, ("POST", "/v1/workspaces/7/agents", {"type": provider}))
                    self.assertEqual(trust.call_count, int(provider == "claude"))
                    send.assert_not_called()
                    sleep.assert_not_called()

    def test_failed_agent_reports_workspace_success_and_warning(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(server, "WORKSPACES", Path(folder)), \
             patch.object(server, "scaffold", return_value=Path(folder) / "design"), \
             patch.object(server, "open_in_daemon", return_value={"id": 7}), \
             patch.object(server, "daemon", side_effect=[(200, ["codex"]), (400, {"error": "binary missing"})]):
            status, result = self.request({"name": "design", "agent": True, "agentType": "codex"})
            self.assertEqual(status, 201)
            self.assertFalse(result["agent"])
            self.assertIn("binary missing", result["warning"])

    def test_unknown_provider_is_rejected_before_creating_files(self):
        with patch.object(server, "daemon", return_value=(200, ["claude"])), \
             patch.object(server, "scaffold") as scaffold:
            status, _ = self.request({"name": "design", "agent": True, "agentType": "missing"})
            self.assertEqual(status, 400)
            scaffold.assert_not_called()

    def test_no_agent_needs_no_registry_or_login(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(server, "WORKSPACES", Path(folder)), \
             patch.object(server, "scaffold", return_value=Path(folder) / "design"), \
             patch.object(server, "open_in_daemon", return_value={"id": 7}), \
             patch.object(server, "trust_for_claude") as trust, \
             patch.object(server, "daemon") as daemon:
            status, _ = self.request({"name": "design", "agent": False})
            self.assertEqual(status, 201)
            daemon.assert_not_called()
            trust.assert_not_called()


if __name__ == "__main__":
    unittest.main()
