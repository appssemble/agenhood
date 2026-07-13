# images/agent/Dockerfile
# syntax=docker/dockerfile:1.7
# Build context is the monorepo root so we can COPY packages/agentcore + services/shim.

############ builder ############
FROM python:3.12-slim-bookworm AS builder
# Scope cache-mount ids per platform: concurrent multi-arch builds must NOT share
# /var/cache/apt or /root/.cache/uv, or apt/dpkg race on the shared archive dir
# ("dpkg: error: cannot stat .../<pkg>.deb: No such file" -> exit 100).
ARG TARGETARCH

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
RUN --mount=type=cache,target=/var/cache/apt,id=apt-builder-${TARGETARCH} \
    apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl build-essential \
    && rm -rf /var/lib/apt/lists/*

# uv for fast, hash-checked installs
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"

# Shim runtime deps from the hash-locked lockfile, into a self-contained venv.
COPY services/shim/requirements.txt /tmp/requirements.txt
RUN --mount=type=cache,target=/root/.cache/uv,id=uv-${TARGETARCH} \
    uv venv /opt/venv \
    && uv pip install --python /opt/venv/bin/python \
         --require-hashes -r /tmp/requirements.txt

# The shared agentcore package + the shim package (installed editable-free).
COPY packages/agentcore /src/agentcore
COPY services/shim /src/shim
RUN --mount=type=cache,target=/root/.cache/uv,id=uv-${TARGETARCH} \
    uv pip install --python /opt/venv/bin/python --no-deps /src/agentcore \
    && uv pip install --python /opt/venv/bin/python --no-deps /src/shim

############ runtime ############
FROM python:3.12-slim-bookworm AS runtime
ARG VARIANT=full
ARG TARGETARCH        # scopes the apt cache mount per platform (see builder stage)

RUN --mount=type=cache,target=/var/cache/apt,id=apt-runtime-${TARGETARCH} \
    apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl jq ripgrep git tini bash less gnupg \
        openssh-client netcat-openbsd \
    && if [ "$VARIANT" = "full" ]; then \
         apt-get install -y --no-install-recommends chromium chromium-driver; \
       fi \
    && rm -rf /var/lib/apt/lists/*

# --- Node.js (NodeSource) ---------------------------------------------------
# Debian bookworm only ships Node 18, which is EOL (no upstream security
# patches). The agent runs model-generated JS, so keep the runtime on a
# supported LTS. NodeSource provides Node 24 for both amd64 and arm64; the
# setup script self-installs its apt prereqs and bundles a current npm.
ARG NODE_MAJOR=24
RUN --mount=type=cache,target=/var/cache/apt,id=apt-runtime-${TARGETARCH} \
    curl -fsSL "https://deb.nodesource.com/setup_${NODE_MAJOR}.x" | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/* \
    && node --version && npm --version

# --- opencode (Unit 3): the second launch driver shells out to this binary ---
# Best-effort per spec §3.5.2 / index §11.5: if the npm install fails at
# build time (e.g. package not yet published), the build continues and the
# driver handles the missing binary gracefully at runtime.
ARG OPENCODE_VERSION=1.17.18
RUN npm install -g opencode-ai@${OPENCODE_VERSION} \
    && opencode --version \
    || echo "WARNING: opencode-ai@${OPENCODE_VERSION} install failed (best-effort, driver will handle at runtime)"

# --- codex (spec §3.5.3): the codex driver shells out to this binary ---
# Best-effort like opencode: a download failure must not break the build; the
# driver emits codex_unavailable at runtime if the binary is missing. We fetch
# the prebuilt musl release binary rather than the npm package so codex needs no
# Node runtime at all (the binary is self-contained). Verified: the tarball
# contains a single file `codex-<target>` which we rename to `codex`.
ARG CODEX_VERSION=0.144.3
RUN set -eux; \
    arch="$(dpkg --print-architecture)"; \
    case "$arch" in \
      amd64) target="x86_64-unknown-linux-musl" ;; \
      arm64) target="aarch64-unknown-linux-musl" ;; \
      *) echo "WARNING: unsupported arch $arch for codex; skipping" && exit 0 ;; \
    esac; \
    url="https://github.com/openai/codex/releases/download/rust-v${CODEX_VERSION}/codex-${target}.tar.gz"; \
    ( curl -fsSL "$url" -o /tmp/codex.tar.gz \
      && tar -xzf /tmp/codex.tar.gz -C /usr/local/bin \
      && mv "/usr/local/bin/codex-${target}" /usr/local/bin/codex \
      && chmod +x /usr/local/bin/codex \
      && rm -f /tmp/codex.tar.gz \
      && codex --version ) \
    || echo "WARNING: codex ${CODEX_VERSION} install failed (best-effort, driver handles at runtime)"

# --- claude-code: Anthropic's official CLI; the claude-code driver shells out to it ---
# Best-effort like opencode/codex: a download failure must not break the build.
ARG CLAUDE_CODE_VERSION=2.1.191
RUN npm install -g @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION} \
    && claude --version \
    || echo "WARNING: @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION} install failed (best-effort, driver handles at runtime)"

# --- Node fetch proxy shim: make built-in fetch honor HTTP(S)_PROXY/NO_PROXY ---
# Node's bundled undici ignores proxy env vars (unlike curl/git/python), so
# workspace *.mjs scripts that use fetch() can't reach the egress proxy and fail
# with EAI_AGAIN. We install undici (which has EnvHttpProxyAgent) into an
# ISOLATED dir — not -g, so it never shadows opencode/claude-code's own undici —
# and a preload installs it as the global dispatcher for every node process via
# NODE_OPTIONS (set below). Best-effort install; the preload no-ops if undici is
# missing and is written to never throw.
ARG UNDICI_VERSION=6.27.0
RUN mkdir -p /opt/node-proxy \
    && npm install --prefix /opt/node-proxy --no-save --no-audit --no-fund --loglevel=error undici@${UNDICI_VERSION} \
    && node -e "if (typeof require('/opt/node-proxy/node_modules/undici').EnvHttpProxyAgent !== 'function') process.exit(1)" \
    || echo "WARNING: undici@${UNDICI_VERSION} install failed (best-effort; node fetch proxy shim disabled)"
COPY images/agent/node-proxy-preload.cjs /opt/node-proxy/preload.cjs

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"
ENV CHROMIUM_PATH=/usr/bin/chromium
# Load the proxy shim into every node process (workspace scripts included). Set
# after all build-time npm installs so it only affects runtime.
ENV NODE_OPTIONS="--require /opt/node-proxy/preload.cjs"

RUN useradd -u 1000 -m -s /bin/bash agent \
    && mkdir -p /workspace && chown -R agent:agent /workspace

# Privilege separation splits /workspace ownership: the entrypoint root-owns
# /workspace (1777, so the agent can't unlink shim-private .agent-runtime) while
# the shim runs `git init` as the agent uid, leaving .git agent-owned. Git's
# CVE-2022-24765 ownership check then rejects the repo as "dubious ownership"
# for BOTH the agent-uid and the privileged (root) git invocations. Trust the
# fixed workspace path in the SYSTEM config (/etc/gitconfig) — the only config
# scope git honors for safe.directory besides --global, read by every uid, and
# immutable at runtime (read-only rootfs) so the untrusted agent can't widen it.
RUN git config --system --add safe.directory /workspace

COPY images/agent/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

USER agent
WORKDIR /workspace
EXPOSE 8080
ENV AGENT_IMAGE_VARIANT=${VARIANT}
ENTRYPOINT ["/usr/bin/tini", "--", "/entrypoint.sh"]
