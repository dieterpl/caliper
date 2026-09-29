"""Exercise privacy checks against real disposable Git repositories."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check-release.py"


class ReleaseChecksTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "scripts").mkdir()
        shutil.copy(SCRIPT, self.root / "scripts/check-release.py")
        self.git("init", "-q")
        self.git("config", "user.name", "Release test")
        self.git("config", "user.email", "test@example.invalid")

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.root, check=True,
                              capture_output=True, text=True)

    def check(self, history=False):
        return subprocess.run([sys.executable, "scripts/check-release.py",
                               *(["--history"] if history else [])], cwd=self.root,
                              capture_output=True, text=True)

    def commit(self, message="Example"):
        self.git("add", "-A")
        self.git("commit", "-qm", message)

    def test_deleted_private_file_is_found_only_in_history(self):
        # Construct fixture values so the test source itself is publishable.
        value = ".".join(["172", "20", "4", "5"])
        path = self.root / "notes.txt"
        path.write_text(value)
        self.commit()
        path.unlink()
        self.commit("Remove notes")
        self.assertEqual(self.check().returncode, 0)
        result = self.check(history=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("private LAN address", result.stdout)
        self.assertNotIn(value, result.stdout)

    def test_commit_message_on_other_branch_is_checked(self):
        self.commit()
        original = self.git("branch", "--show-current").stdout.strip()
        self.git("checkout", "-qb", "old-work")
        (self.root / "example.txt").write_text("Example")
        value = "https://claude.ai/" + "code/" + "session_" + "example"
        self.commit(value)
        self.git("checkout", "-q", original)
        result = self.check(history=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("provider session link", result.stdout)
        self.assertNotIn(value, result.stdout)

    def test_credentials_are_rejected_but_templates_are_allowed(self):
        (self.root / ".env.example").write_text("WEB_TOKEN=\n")
        skill = self.root / "template/.claude/skills/cad/SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("CAD instructions")
        self.commit()
        self.assertEqual(self.check(history=True).returncode, 0)
        credentials = self.root / ".aws/credentials"
        credentials.parent.mkdir()
        credentials.write_text("example")
        self.assertEqual(self.check().returncode, 1)

    def test_all_private_ipv4_ranges_are_rejected(self):
        for octets in [(10, 1, 2, 3), (172, 16, 1, 2), (172, 31, 2, 3), (192, 168, 1, 2)]:
            with self.subTest(octets=octets):
                value = ".".join(map(str, octets))
                (self.root / "notes.txt").write_text(value)
                result = self.check()
                self.assertEqual(result.returncode, 1)
                self.assertNotIn(value, result.stdout)


if __name__ == "__main__":
    unittest.main()
