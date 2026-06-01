# Self-hosted agent-image registry

Deployed as its own Coolify Docker Compose resource. Coolify provides TLS for
`registry.example.com` and forwards to the `registry` container's port 5000.

## One-time: create the htpasswd credential

The `registry-auth` volume must contain `/auth/htpasswd`. Create it on the server
(or upload via Coolify's file manager) — bcrypt entries only:

```bash
docker run --rm --entrypoint htpasswd httpd:2 -Bbn registry-pusher "$REGISTRY_PUSH_PASSWORD" > htpasswd
docker run --rm --entrypoint htpasswd httpd:2 -Bbn registry-puller "$REGISTRY_PULL_PASSWORD" >> htpasswd
# place this file at the root of the registry-auth volume as `htpasswd`
```

- `registry-pusher` — used by GitHub Actions to push (push+pull).
- `registry-puller` — used by each control-plane host daemon to pull (pull only is fine;
  registry:2 htpasswd does not separate read/write, so treat both as full creds and
  keep the puller password least-privileged operationally).

## Verify

```bash
curl -u registry-puller:$REGISTRY_PULL_PASSWORD https://registry.example.com/v2/_catalog
# -> {"repositories":[...]}  (200, not 401)
```
