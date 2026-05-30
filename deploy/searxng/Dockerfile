# Bakes settings.yml into the image so Coolify never bind-mounts ./searxng (a repo
# bind mount Coolify can materialize as an empty dir / resolve against the wrong
# base dir). COPY overlays settings.yml without shadowing the base image's other
# /etc/searxng files. Build context is the monorepo root (matches the other services).
FROM searxng/searxng:latest
COPY deploy/searxng/settings.yml /etc/searxng/settings.yml
