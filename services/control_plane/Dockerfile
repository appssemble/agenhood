# syntax=docker/dockerfile:1
# Build context MUST be the repo root (see deploy/docker-compose.yml).
FROM python:3.12-slim

# curl is used by the dev health-wait and bootstrap scripts (run via exec).
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Editable installs: bind-mounting these paths in dev makes edits live.
COPY packages/agentcore /app/packages/agentcore
COPY services/control_plane /app/services/control_plane
RUN pip install --no-cache-dir -e /app/packages/agentcore \
    && pip install --no-cache-dir -e /app/services/control_plane

# alembic.ini + migrations resolve from this directory.
WORKDIR /app/services/control_plane

# Run DB migrations on container start (alembic upgrade head), then exec the CMD.
# Keeps the schema in sync with the code on every start — dev's uvicorn --reload
# reloads code without re-running migrations, which otherwise drifts the DB.
RUN chmod +x docker-entrypoint.sh
ENTRYPOINT ["/app/services/control_plane/docker-entrypoint.sh"]

EXPOSE 8443
CMD ["uvicorn", "control_plane.asgi:app", "--host", "0.0.0.0", "--port", "8443"]
