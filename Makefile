.PHONY: install lint test test-integration run dev

install:
	uv sync

lint:
	uv run ruff check .

test:
	uv run pytest -m "not integration"

test-integration:
	uv run pytest -m integration

run:
	docker compose -f deploy/docker-compose.yml up --build

dev:
	docker compose -f deploy/docker-compose.yml up -d --build
