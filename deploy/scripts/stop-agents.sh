#!/usr/bin/env sh
# Remove agent containers spawned by the control plane (they live outside the
# compose project). Identified by the label set in docker_ctl/provision.py.
set -eu

IDS="$(docker ps -aq --filter label=agent-runtime.container_id || true)"
if [ -n "$IDS" ]; then
  echo "Removing agent containers:"
  # shellcheck disable=SC2086
  docker rm -f $IDS
else
  echo "No dangling agent containers."
fi
