#!/bin/bash
# Bring up the two long-lived processes and tie their lifetimes together.
#
# The daemon owns every workspace and its panes; the web server is the only way
# in from a browser. If either dies the container should die too, so Docker's
# restart policy puts the whole desk back rather than leaving a half-running
# container that answers HTTP but has no daemon behind it.
set -euo pipefail

# `docker run caliper caliper sim --seconds 8` runs that command instead of the
# app. Handy for one-off toolchain work; the daemon is not needed for it.
if [ "$#" -gt 0 ]; then
  exec "$@"
fi

# Always use the daemon owned by this container, even if an override is passed.
export BUTAI_SOCKET=/state/butai/butai.sock
SOCK_DIR="$(dirname "$BUTAI_SOCKET")"
mkdir -p "$SOCK_DIR" "$WORKSPACES_DIR" "$HOME"
# The daemon insists on 0700 for the socket's parent and refuses to start otherwise.
chmod 700 "$SOCK_DIR"

# Claude Code asks a first-run question (pick a theme) until this file says
# otherwise — and an agent sitting in that picker would swallow the brief the
# app types at it instead of reading it as a prompt. Seed it once; after that
# the CLI owns the file, on the state volume, so its history survives restarts.
if [ ! -f "$HOME/.claude.json" ]; then
  cat > "$HOME/.claude.json" <<JSON
{
  "hasCompletedOnboarding": true,
  "lastOnboardingVersion": "$(claude --version 2>/dev/null | cut -d' ' -f1)",
  "theme": "dark"
}
JSON
fi

# Codex owns its interactive account login. Its cache is on the persistent
# state volume; never replace the user's login with a runtime API key.

# Commits need an author. Nothing here overrides a ~/.gitconfig you mounted in.
if [ ! -f "$HOME/.gitconfig" ]; then
  git config --global user.name "${GIT_AUTHOR_NAME:-caliper}"
  git config --global user.email "${GIT_AUTHOR_EMAIL:-caliper@localhost}"
  git config --global init.defaultBranch main
  git config --global --add safe.directory '*'
fi

echo "[boot] starting $(butai --version) on $BUTAI_SOCKET"
butai daemon &
BUTAI_PID=$!

# The socket appears a beat after the process does; the web server's first act
# is to talk to it, so wait rather than race.
for _ in $(seq 1 100); do
  [ -S "$BUTAI_SOCKET" ] && break
  sleep 0.1
done
if [ ! -S "$BUTAI_SOCKET" ]; then
  echo "[boot] butai daemon never created $BUTAI_SOCKET" >&2
  exit 1
fi
echo "[boot] daemon up"

"$CAD_PYTHON" "$APP_DIR/web/server.py" &
WEB_PID=$!

# Whichever exits first takes the container with it.
wait -n "$BUTAI_PID" "$WEB_PID"
STATUS=$?
echo "[boot] a process exited ($STATUS) — shutting down" >&2
kill "$BUTAI_PID" "$WEB_PID" 2>/dev/null || true
exit "$STATUS"
