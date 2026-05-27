# syntax=docker/dockerfile:1
# Build context MUST be the repo root (see deploy/docker-compose.yml).
FROM python:3.12-slim

# curl is used by the dev health-wait and bootstrap scripts (run via exec).
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Editable install: bind-mounting this path in dev makes edits live.
COPY services/connectors /app/services/connectors
RUN pip install --no-cache-dir -e /app/services/connectors

# alembic.ini + migrations resolve from this directory.
WORKDIR /app/services/connectors

# Ensure the connectors DB exists, run DB migrations on container start
# (alembic upgrade head), then exec the CMD.  Keeps the schema in sync with
# the code on every start — dev's uvicorn --reload reloads code without
# re-running migrations, which otherwise drifts the DB.
RUN chmod +x docker-entrypoint.sh
ENTRYPOINT ["/app/services/connectors/docker-entrypoint.sh"]

EXPOSE 8090
CMD ["uvicorn", "connectors.asgi:app", "--host", "0.0.0.0", "--port", "8090"]
