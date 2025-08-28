#!/bin/bash
# images/agent/entrypoint.sh
# Runs as root (container started with user="0:0"); prepares the workspace
# trust boundary, then execs the shim. The shim drops to the agent uid for all
# untrusted work (see agentcore.sandbox).
set -euo pipefail

WS=/workspace
AGENT_UID=1000
AGENT_GID=1000

# Privilege separation requires this entrypoint to run as root so it can set up
# the trust boundary below. Fail loudly (instead of a confusing chown EPERM) if
# the container was started as a non-root user.
if [ "$(id -u)" != "0" ]; then
    echo "FATAL: entrypoint must run as root (uid 0) for privilege separation; got uid=$(id -u)." >&2
    echo "       The control plane must provision the container with user=\"0:0\"." >&2
    exit 1
fi

mkdir -p "$WS"
# Root owns the workspace; world-writable + sticky (the /tmp model) lets the
# agent create and manage its OWN files but NOT unlink/rename the root-owned
# .agent-runtime below — the agent is neither that dir's owner nor the parent's.
# chown-before-chmod so root sets the mode on a dir it owns (needs only CHOWN,
# not CAP_FOWNER), regardless of the volume's prior ownership.
chown "0:0" "$WS"
chmod 1777 "$WS"

# Shim-private (root-only): event logs, status, task metadata.
mkdir -p "$WS/.agent-runtime"
chown -R "0:0" "$WS/.agent-runtime"
chmod 700 "$WS/.agent-runtime"

# Per-task agent-writable: driver homes, credentials, skills, git askpass.
# Take root ownership first so root can chmod it (CHOWN cap only, no CAP_FOWNER),
# then hand it to the agent uid. Doing chown-to-agent before chmod would make
# root chmod a file it does not own → EPERM without CAP_FOWNER.
mkdir -p "$WS/.agent-state"
chown "0:0" "$WS/.agent-state"
chmod 700 "$WS/.agent-state"
chown "${AGENT_UID}:${AGENT_GID}" "$WS/.agent-state"

exec python3 -m shim.main --port 8080 --workspace "$WS"
