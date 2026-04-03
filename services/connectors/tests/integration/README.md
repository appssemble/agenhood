# Connectors integration tier (Tier 2 — Postgres)

These `integration`-marked tests run the connectors service logic against a real
Postgres (testcontainers `postgres:16`). The provider HTTP seam (Slack/GitHub)
and the control-plane client are stubbed in-process — only the database is real.
They lock the things SQLite cannot prove: the `webhook_events` UNIQUE-index
dedupe (`IntegrityError`), JSONB column round-trips, and asyncpg transaction
semantics, plus relay/resume/rendering and cross-tenant isolation end-to-end.

## Running
From `services/connectors/` with docker running:
`.venv/bin/python -m pytest tests/integration -m integration -q`
Without a docker daemon every test self-skips (the `pg_url` fixture skips).

## Layout
- `conftest.py` — docker-gated session Postgres + `metadata.create_all`;
  per-test `session_factory` (own engine + TRUNCATE); `pg_app` builder.
- `test_dedupe_relay_pg.py` — slack inbound loop + dedupe + JSONB.
- `test_resume_isolation_pg.py` — resume/rendering + tenant isolation.

## Adding a provider
The provider meta-gate (`tests/test_provider_meta_gate.py`) forces every new
provider to cite inbound + outbound + isolation tests; add a Postgres inbound
case here if the provider has DB-visible side effects beyond the unit tier.
