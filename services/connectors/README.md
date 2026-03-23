# Connectors Service

Standalone GitHub/Slack bridge for the agent runtime. Inbound provider webhooks
trigger agent tasks on the control plane; an outbound relay subscribes to the
control plane's SSE event stream and edits the originating thread or PR comment
in place with the agent's reasoning and final result. Black-box service: owns its
own Postgres database and AES-GCM encryption layer; it communicates with the
control plane exclusively through the control plane's existing public API.

## Flows

### Inbound (webhook → task)

```
GitHub / Slack
     │  POST /v1/webhooks/{provider}
     ▼
connectors  (verify signature · dedupe on delivery ID · resolve routing rule)
     │  POST /v1/tasks  (control-plane public API, tenant API key)
     ▼
control plane → agent container
```

1. The provider posts a signed webhook payload.
2. Connectors verifies the signature, deduplicates on the provider's delivery ID,
   and resolves a `routing_rule` to find the target container.
3. A `delivery` record is persisted and a task is submitted to the control plane
   using the tenant's API key stored in the matching `connection` row.

### Outbound (task events → provider edit)

```
control plane SSE  GET /v1/tasks/{id}/events
     │  stream
     ▼
connectors relay  (coalesce · render Markdown)
     │  Slack chat.update  /  GitHub comment PATCH
     ▼
original thread / PR comment (edited in place)
```

1. A background relay task subscribes to the control plane's SSE event stream for
   each in-flight delivery.
2. Updates are coalesced over `RELAY_COALESCE_MS` milliseconds, rendered to
   Markdown, and written back to the provider message via a single edit API call.
3. On service restart, all open deliveries are resumed automatically.

## Endpoints

| Prefix | Visibility | Description |
|--------|------------|-------------|
| `POST /v1/webhooks/{github,slack}` | **Public ingress** | Receive signed provider events |
| `GET /v1/oauth/{slack,github}/callback` | **Public ingress** | OAuth / GitHub App install callback |
| `/v1/connections` | Management (internal) | List and revoke tenant connections |
| `/v1/bindings` | Management (internal) | Map connections to containers (`container_binding`) |
| `/v1/routing-rules` | Management (internal) | Match rules to target containers |
| `GET /healthz` | Internal | Liveness check |

Traefik routes only `/v1/webhooks` and `/v1/oauth` to this service. The
management endpoints (`/v1/connections`, `/v1/bindings`, `/v1/routing-rules`) are
not exposed through the public reverse proxy.

## Configuration

| Variable | Required | Description |
|----------|----------|-------------|
| `CONNECTORS_DATABASE_URL` | Yes | `postgresql+asyncpg://…` connection string for the connectors Postgres database |
| `CONNECTORS_MASTER_KEY` | Yes (prod) | Base64-encoded 32-byte AES key used to encrypt stored provider access tokens |
| `CONTROL_PLANE_BASE_URL` | Yes | Internal base URL of the control-plane service (e.g. `http://control-plane:8443`) |
| `CONNECTORS_PUBLIC_BASE_URL` | Yes | Public base URL of this service; used when constructing OAuth redirect URIs |
| `RELAY_COALESCE_MS` | No | Milliseconds to wait before flushing a relay update to the provider; default `1000` |
| `SLACK_SIGNING_SECRET` | Slack only | Slack signing secret for webhook HMAC verification |
| `SLACK_CLIENT_ID` | Slack only | Slack OAuth app client ID |
| `SLACK_CLIENT_SECRET` | Slack only | Slack OAuth app client secret |
| `GITHUB_APP_ID` | GitHub only | GitHub App ID |
| `GITHUB_APP_PRIVATE_KEY` | GitHub only | GitHub App private key in PEM format |
| `GITHUB_WEBHOOK_SECRET` | GitHub only | Secret used to verify GitHub webhook HMAC signatures |

## Operator Setup Checklist

To wire a tenant up from scratch:

1. **Create the provider app.**
   - *GitHub App*: set the webhook URL to
     `${CONNECTORS_PUBLIC_BASE_URL}/v1/webhooks/github`, configure a webhook
     secret, and grant the necessary repository/issue/PR permissions and events.
     Note the App ID and download the private key PEM.
   - *Slack app*: enable Event Subscriptions with request URL
     `${CONNECTORS_PUBLIC_BASE_URL}/v1/webhooks/slack`; add the OAuth redirect
     URI `${CONNECTORS_PUBLIC_BASE_URL}/v1/oauth/slack/callback`.

2. **Create a control-plane API key** for the tenant via the control plane's
   existing `POST /v1/api-keys` endpoint. Note the key value.

3. **Run the connect flow.** Initiate the GitHub App installation or Slack OAuth
   flow with `state="{tenant_id}|{control_plane_api_key}"`. On callback,
   connectors stores the connection and encrypts the access token under the master
   key.

4. **Create a container binding** (`PUT /v1/bindings`) linking the new
   `connection_id` to the target `container_id`, with optional `resource_filters`
   (e.g. repo slugs or channel IDs).

5. **Create one or more routing rules** (`PUT /v1/routing-rules`) specifying the
   `match` condition and the `target.container_id`.

## Development & Tests

```bash
# Fast unit tests — no Docker required
python -m pytest services/connectors/tests -m unit

# Full-loop integration tests — Docker daemon required
python -m pytest services/connectors/tests -m integration

# Lint
ruff check services/connectors

# Type-check
mypy services/connectors/connectors
```
