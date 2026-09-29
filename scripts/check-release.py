#!/usr/bin/env python3
"""Check publishable files for local-only content; use Gitleaks for secrets."""
from pathlib import Path
import re
import argparse
import hashlib
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--history", action="store_true", help="also scan every local Git ref and commit message")
args = parser.parse_args()
paths = subprocess.check_output(
    ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=ROOT
).decode().split("\0")
blocked_dirs = {".git", ".openai", ".codex", ".gemini", "node_modules", "__pycache__", ".ssh", ".aws", ".azure", ".kube", ".gnupg", ".terraform"}
blocked_roots = {"workspaces", "projects", "out", ".venv", "dashboard", ".claude"}
patterns = {
    "personal absolute path": re.compile(r"(?<![\w/])/(?:home|Users|media)/[\w.-]+/", re.I),
    "private LAN address": re.compile(r"(?<![\w.])(?:192\.168|10\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}(?![\w.])"),
    "provider session link": re.compile(r"https://(?:claude\.ai/code/session_|chatgpt\.com/(?:c|share)/)"),
    "private VPN hostname": re.compile(r"\b[\w.-]+\.ts\.net\b", re.I),
    "deployment identifier": re.compile(r"appgprj_[a-zA-Z0-9]+"),
}
# These obsolete screenshot blobs contain host RAM/container information.
# Block their exact Git object IDs even if someone renames or restores them.
PRIVATE_IMAGE_BLOBS = {
    "6194f516d0068f9fc56b046a6fec94303b24569c",
    "28e76ca093f5fb6285c20659e2c75de1de6fc59e",
}
issues = set()


def check_name(name):
    path = Path(name)
    parts = path.parts
    if not parts:
        return
    sensitive = path.name.startswith(".env") and not path.name.endswith(".example")
    provider_state = ".claude" in parts and not name.startswith("template/.claude/skills/")
    credential_file = path.name in {".npmrc", ".netrc", "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519"}
    if (parts[0] in blocked_roots or blocked_dirs.intersection(parts) or provider_state
            or sensitive or credential_file or path.suffix in {".pem", ".key", ".p12", ".pfx"}):
        issues.add(f"{name}: local-only file")


def check_data(name, data, oid=None):
    if oid is None:
        oid = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
    if oid in PRIVATE_IMAGE_BLOBS:
        issues.add(f"{name}: screenshot contains host resource information")
    if b"\0" in data:
        return
    text = data.decode("utf-8", "replace")
    for label, pattern in patterns.items():
        if pattern.search(text):
            # Never print matched values: CI logs must not repeat the disclosure.
            issues.add(f"{name}: {label}")


for name in sorted(set(filter(None, paths))):
    path = ROOT / name
    if path.is_symlink():
        issues.add(f"{name}: symlink requires review")
        continue
    if not path.is_file():
        continue  # removed tracked files are absent from the release snapshot
    check_name(name)
    check_data(name, path.read_bytes())

if args.history:
    commits = subprocess.check_output(["git", "rev-list", "--all"], cwd=ROOT).decode().splitlines()
    blobs = {}
    for commit in commits:
        check_data(f"commit {commit[:12]}", subprocess.check_output(
            ["git", "cat-file", "commit", commit], cwd=ROOT))
        tree = subprocess.check_output(["git", "ls-tree", "-rz", commit], cwd=ROOT)
        for entry in tree.split(b"\0"):
            if not entry:
                continue
            metadata, name = entry.split(b"\t", 1)
            mode, kind, oid = metadata.decode().split()
            name = name.decode("utf-8", "replace")
            check_name(name)
            if mode == "120000":
                issues.add(f"{name}: historical symlink requires review")
            if kind == "blob":
                blobs.setdefault(oid, name)
    if blobs:
        # Read each unique historical blob once; large vendored files need no
        # repeated scanning for each commit or branch.
        batch = subprocess.run(["git", "cat-file", "--batch"], cwd=ROOT,
                               input=("\n".join(blobs) + "\n").encode(),
                               stdout=subprocess.PIPE, check=True).stdout
        offset = 0
        for oid, name in blobs.items():
            end = batch.index(b"\n", offset)
            size = int(batch[offset:end].split()[-1])
            offset = end + 1
            check_data(f"{name} (history)", batch[offset:offset + size], oid)
            offset += size + 1
    print(f"History checked: {len(commits)} commits, {len(blobs)} unique file versions.")

for issue in sorted(issues):
    print(issue)
if issues:
    sys.exit(1)
print("Release file checks passed (also run Gitleaks and review images/history).")
