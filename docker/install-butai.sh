#!/bin/sh
# Put the butai binary at $1 — from butai's public GitHub releases, or from the
# build context when a binary was dropped there.
#
# This exists so `docker compose up --build` is the whole install. The old
# Dockerfile did `COPY docker/butai`, which fails the build outright when
# nobody has run a fetch script yet — a first-run error message about a missing
# file in the build context, which explains nothing.
#
# A binary at docker/butai still wins, so an air-gapped build, a local dev
# build of the daemon, or a pre-release copy all work the same way they did.
#
# Whatever the source, the binary is checked before the build goes on: a
# downloaded tarball against the release's SHA256SUMS, and every binary against
# `--version`, because caliper speaks butai's 1.x wire protocol and a daemon
# older than that answers some of these routes differently or not at all.
set -eu

DEST="${1:?usage: install-butai.sh <dest>}"
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="dieterpl/butai"
VERSION="${BUTAI_VERSION:-latest}"
# butai 1.0.0 put its command set, config format and wire protocol under
# semantic versioning. caliper is written against that; below it the framed
# protocol and `/v1/*` are still moving, so the floor is a real one.
MIN="1.0.0"

mkdir -p "$(dirname "$DEST")"

# `butai --version` prints "butai 1.1.1"; take the number.
version_of() {
    "$1" --version 2>/dev/null | head -n 1 | tr -d '\r' | awk '{print $NF}'
}

# True when $1 sorts below $MIN. `sort -V` is coreutils', present in the image
# this runs in; a version we cannot parse is let through rather than guessed at.
older_than_min() {
    case "$1" in ''|*[!0-9.]*) return 1 ;; esac
    [ "$(printf '%s\n%s\n' "$MIN" "$1" | sort -V | head -n 1)" = "$1" ] &&
        [ "$1" != "$MIN" ]
}

# Everything that lands at $DEST comes through here: it has to run, and it has
# to be new enough to talk to.
check_binary() {
    got="$(version_of "$DEST")" || got=""
    if [ -z "$got" ]; then
        cat >&2 <<MSG
butai: the binary at $DEST does not run here.

That is usually the wrong build for this machine — a musl binary on glibc, or
another architecture. Remove docker/butai and let the build download the
release for this platform, or fetch the right one by hand.
MSG
        exit 1
    fi
    if older_than_min "$got"; then
        cat >&2 <<MSG
butai: found $got, and caliper needs $MIN or newer.

butai 1.0.0 is where its wire protocol settled; caliper's proxy and its live
pane are written against it. To move up:

    rm docker/butai && docker compose up --build     # download a release
    BUTAI_BIN=/path/to/newer/butai scripts/fetch-butai.sh

MSG
        exit 1
    fi
    echo "butai: $got at $DEST ($(du -h "$DEST" | cut -f1))"
}

# --- a binary in the build context wins --------------------------------------
if [ -f "$HERE/butai" ]; then
    cp "$HERE/butai" "$DEST"
    chmod +x "$DEST"
    echo "butai: took the binary from the build context"
    check_binary
    exit 0
fi

# --- work out which artifact this platform wants -----------------------------
# Same rules as butai's own scripts/install.sh; keep them in step.
arch="$(uname -m)"
case "$arch" in
    x86_64|amd64)  arch_name=x86_64 ;;
    arm64|aarch64) arch_name=aarch64 ;;
    armv7l|armv7)  arch_name=armv7 ;;
    *) echo "butai: unsupported architecture $arch" >&2; exit 1 ;;
esac

if [ "$arch_name" = armv7 ]; then
    target="armv7-unknown-linux-gnueabihf"
elif ldd --version 2>&1 | grep -qi musl; then
    # `ldd --version` writes to stderr on glibc and stdout on musl, hence 2>&1.
    target="${arch_name}-unknown-linux-musl"
else
    target="${arch_name}-unknown-linux-gnu"
fi

if [ "$VERSION" = latest ]; then
    VERSION="$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" \
        | sed -n 's/.*"tag_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' \
        | head -n 1)" || true
fi

if [ -z "${VERSION:-}" ] || [ "$VERSION" = latest ]; then
    cat >&2 <<MSG
butai: could not ask github.com which release is current.

That is the network, not the repository — https://github.com/$REPO is public.
Behind a proxy or offline, install from a binary you already have:

    BUTAI_BIN=/path/to/butai scripts/fetch-butai.sh
    docker compose up --build

or name a version to skip the lookup: BUTAI_VERSION=v$MIN docker compose build

MSG
    exit 1
fi

bare="${VERSION#v}"
if older_than_min "$bare"; then
    echo "butai: BUTAI_VERSION=$VERSION is below the $MIN caliper needs" >&2
    exit 1
fi

base="https://github.com/$REPO/releases/download/$VERSION"
tarball="butai-${bare}-${target}.tar.gz"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT INT TERM

echo "butai: downloading $VERSION for $target"
if ! curl -fsSL "$base/$tarball" -o "$tmp/$tarball"; then
    cat >&2 <<MSG
butai: $VERSION has no $tarball.

The release publishes one tarball per target triple and this platform's is not
among them. Check the assets on https://github.com/$REPO/releases/tag/$VERSION.
MSG
    exit 1
fi

# Verify the release checksum before extracting or running the binary.
# A missing checksum file is a failed download, not permission to skip it.
if curl -fsSL "$base/SHA256SUMS" -o "$tmp/SHA256SUMS" 2>/dev/null; then
    want="$(awk -v f="$tarball" '$2 == f || $2 == "*" f {print $1}' "$tmp/SHA256SUMS")"
    got="$(sha256sum "$tmp/$tarball" | cut -d' ' -f1)"
    if [ -z "$want" ]; then
        echo "butai: SHA256SUMS does not list $tarball" >&2
        exit 1
    elif [ "$want" != "$got" ]; then
        echo "butai: checksum mismatch for $tarball" >&2
        echo "  expected $want" >&2
        echo "  got      $got" >&2
        exit 1
    fi
    echo "butai: sha256 ok"
else
    echo "butai: could not download SHA256SUMS for $VERSION; refusing unverified install" >&2
    exit 1
fi

tar -xzf "$tmp/$tarball" -C "$tmp"
found="$(find "$tmp" -type f -name butai -perm -u+x | head -n 1)"
[ -n "$found" ] || { echo "butai: no butai binary inside $tarball" >&2; exit 1; }
cp "$found" "$DEST"
chmod +x "$DEST"
check_binary
