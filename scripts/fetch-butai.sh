#!/bin/bash
# Put a butai binary in the build context, so the image uses it instead of
# downloading one.
#
#   scripts/fetch-butai.sh                    # find one on this machine
#   BUTAI_BIN=/path/to/butai scripts/fetch-butai.sh
#
# You do not normally need this: butai is public, and `docker compose up
# --build` downloads the release itself (docker/install-butai.sh). Run this when
# you want the build to use a specific binary instead — a local dev build of the
# daemon, an unreleased commit, or a machine with no network.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$HERE/docker/butai"

SRC="${BUTAI_BIN:-}"
if [ -z "$SRC" ]; then
  for cand in "$(command -v butai || true)" \
              "$HOME/.local/bin/butai" \
              "$HOME/butai-dl/butai-linux-x86_64"; do
    if [ -n "$cand" ] && [ -x "$cand" ]; then SRC="$cand"; break; fi
  done
fi

if [ -z "$SRC" ]; then
  cat >&2 <<MSG
no butai binary found on this machine.

Either point this at one:

    BUTAI_BIN=/path/to/butai scripts/fetch-butai.sh

or skip this script entirely and let the image download a release:

    docker compose up --build
MSG
  exit 1
fi

# The build refuses anything below this, so say it here rather than three
# minutes into a docker build: caliper speaks butai's 1.x wire protocol.
MIN=1.0.0
VER="$("$SRC" --version 2>/dev/null | head -n 1 | awk '{print $NF}')"
if [ -z "$VER" ]; then
  echo "$SRC does not run on this machine — wrong architecture or libc?" >&2
  exit 1
fi
if [ "$(printf '%s\n%s\n' "$MIN" "$VER" | sort -V | head -n 1)" = "$VER" ] \
   && [ "$VER" != "$MIN" ]; then
  echo "$SRC is butai $VER; caliper needs $MIN or newer." >&2
  echo "Leave docker/butai out and the build downloads a current release." >&2
  exit 1
fi

mkdir -p "$HERE/docker"
cp "$SRC" "$DEST"
chmod +x "$DEST"
echo "copied $SRC -> docker/butai — butai $VER ($(du -h "$DEST" | cut -f1))"
echo "the next \`docker compose up --build\` will use it instead of downloading."
