# Bakes the declawed Traefik static + dynamic config into the image so Coolify
# never bind-mounts these repo files. On Coolify, single-file repo bind mounts can
# be pre-created as empty DIRECTORIES and/or resolve against the wrong base dir —
# which would start the SOLE ingress proxy with zero routers and take down
# console + /v1 api + webhooks together. Baking removes that whole failure class.
# Build context is the monorepo root (matches the other services + Base Directory `/`).
FROM traefik:v3
COPY deploy/traefik/traefik.coolify.yml /etc/traefik/traefik.yml
COPY deploy/traefik/dynamic.yml /etc/traefik/dynamic.yml
