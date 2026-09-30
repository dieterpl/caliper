# The whole workbench in one image: the CAD toolchain, the butai daemon that owns
# the workspaces, the web app, and Claude, Codex and Gemini CLIs.
#
# The web app is a Vite/React build now, compiled in the stage below and copied
# in as static files — there is still exactly one runtime container (the daemon
# and web server, tied together by entrypoint.sh), no separate front-end service.
# butai is installed as a released binary rather than built here: the stage
# below downloads one from its public releases, or uses the binary you dropped
# at docker/butai. That is why `docker compose up --build` is the whole
# install. Pin a version with `--build-arg BUTAI_VERSION=v1.1.1` (or
# BUTAI_VERSION in .env, which compose passes through).

# --- build the SPA -----------------------------------------------------------
FROM node:22-bookworm-slim AS webbuild
WORKDIR /build/web
COPY LICENSE NOTICE /build/
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# --- fetch the butai daemon --------------------------------------------------
# Its own stage so curl never lands in the runtime image. Copying the whole
# docker/ directory rather than `COPY docker/butai` is deliberate: the file is
# optional, and a COPY of a missing path fails the build with a message about
# the build context instead of one about butai.
#
# The script checks the tarball against the release's SHA256SUMS and runs
# `butai --version` before this stage succeeds, so a wrong-platform binary or a
# daemon older than caliper's floor fails here rather than at first boot.
FROM debian:bookworm-slim AS butai
ARG BUTAI_VERSION=latest
ENV BUTAI_VERSION=${BUTAI_VERSION}
RUN apt-get update && apt-get install -y --no-install-recommends \
      curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*
COPY docker/ /src/
RUN sh /src/install-butai.sh /out/butai

# --- the runtime image (the only container that runs) ------------------------
FROM node:22-bookworm-slim

# OCCT (under build123d) links against GL and X even when it never opens a
# window; git is the versioning layer every workspace is built on.
RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 python3-venv git ca-certificates tini \
      libgl1 libglu1-mesa libxrender1 libxext6 libsm6 libx11-6 \
      fontconfig \
 && rm -rf /var/lib/apt/lists/*

# The CAD stack lives in its own venv so the system python stays untouched.
COPY requirements.lock /tmp/requirements.lock
RUN python3 -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
 && /opt/venv/bin/pip install --no-cache-dir --require-hashes -r /tmp/requirements.lock

# Credentials live in the state volume or come from runtime environment.
# Optional version args allow repeatable deployments without baking in logins.
ARG CLAUDE_CLI_VERSION=latest
ARG CODEX_CLI_VERSION=latest
ARG GEMINI_CLI_VERSION=latest
RUN npm install -g @anthropic-ai/claude-code@${CLAUDE_CLI_VERSION} \
      @openai/codex@${CODEX_CLI_VERSION} @google/gemini-cli@${GEMINI_CLI_VERSION} \
 && npm cache clean --force
RUN claude --version && codex --version && gemini --version

COPY --from=butai /out/butai /usr/local/bin/butai

# The app itself: tools shared by every workspace, the web client, the workspace
# template, and the one command an agent needs.
COPY LICENSE NOTICE /opt/caliper/
COPY tools/ /opt/caliper/tools/
COPY web/ /opt/caliper/web/
# The compiled SPA (web/dist) served by web/server.py in production.
COPY --from=webbuild /build/web/dist /opt/caliper/web/dist
COPY template/ /opt/caliper/template/
COPY bin/caliper /opt/caliper/bin/caliper
COPY docker/entrypoint.sh /opt/caliper/entrypoint.sh
RUN chmod +x /opt/caliper/bin/caliper /opt/caliper/entrypoint.sh \
 && ln -s /opt/caliper/bin/caliper /usr/local/bin/caliper

# The socket goes on the /state volume, and so does everything else the daemon
# keeps: butai stores its session list, pane dumps and logs under `~/.butai`,
# and HOME below is on that volume. Deliberately not keyed off the socket path
# — butai's own paths.rs stopped doing that, so pointing BUTAI_SOCKET somewhere
# else does not drag the session file along with it.
ENV APP_DIR=/opt/caliper \
    CAD_PYTHON=/opt/venv/bin/python \
    PYTHONUNBUFFERED=1 \
    DISABLE_AUTOUPDATER=1 \
    RAPIER_PATH=/opt/caliper/web/vendor/rapier.es.js \
    BUTAI_SOCKET=/state/butai/butai.sock \
    WORKSPACES_DIR=/workspaces \
    TEMPLATE_DIR=/opt/caliper/template \
    SERVER_BIND=0.0.0.0 \
    PORT=8017 \
    HOME=/state/home

# HOME lives on the /state volume so everything the agent accumulates — its
# settings, its per-project history, the git identity — survives a restart. The
# host's ~/.claude is mounted *inside* it for credentials; `~/.claude.json` is
# deliberately NOT shared, since the host's own Claude Code writes that file
# constantly and two writers would clobber each other.
#
# The base image's `node` user is already uid 1000, which is what keeps files on
# the bind-mounted /workspaces owned by you rather than by root.
RUN mkdir -p /workspaces /state/home && chown -R node:node /workspaces /state
USER node

EXPOSE 8017
ENTRYPOINT ["/usr/bin/tini", "--", "/opt/caliper/entrypoint.sh"]
