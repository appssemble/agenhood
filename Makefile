VERSION    ?= 1.3.1
REGISTRY   ?=
IMAGE      := $(REGISTRY)agent-runtime

.PHONY: image image-slim
image:
	$(MAKE) -C images/agent image VERSION=$(VERSION) REGISTRY=$(REGISTRY)

image-slim:
	$(MAKE) -C images/agent image-slim VERSION=$(VERSION) REGISTRY=$(REGISTRY)

.PHONY: models-catalog
models-catalog: ensure-agent-image
	AGENT_IMAGE=agent-runtime:$(VERSION) .venv/bin/python scripts/gen_model_catalog.py

# ---- Project runner -----------------------------------------------------------
DEV_PROJECT   := agenhood-dev
PROD_PROJECT  := agenhood
DEV_ENV       := deploy/.env.dev
PROD_ENV      := deploy/.env
BASE_COMPOSE  := deploy/docker-compose.yml
DEV_COMPOSE   := deploy/docker-compose.dev.yml
DEV_SERVICES  := postgres egress-proxy searxng control-plane web-console-dev

DEV_DC  := docker compose -p $(DEV_PROJECT) -f $(BASE_COMPOSE) -f $(DEV_COMPOSE) --env-file $(DEV_ENV)
PROD_DC := docker compose -p $(PROD_PROJECT) -f $(BASE_COMPOSE) --env-file $(PROD_ENV)

.PHONY: ensure-agent-image dev stop logs prod prod-stop smoke

ensure-agent-image:
	@docker image inspect agent-runtime:$(VERSION) >/dev/null 2>&1 \
		|| $(MAKE) image VERSION=$(VERSION)

dev: ensure-agent-image
	$(DEV_DC) up -d --build $(DEV_SERVICES)
	sh deploy/scripts/wait-healthy.sh $(DEV_PROJECT) $(DEV_ENV) $(BASE_COMPOSE) $(DEV_COMPOSE) -- 120
	sh deploy/scripts/bootstrap-dev.sh $(DEV_PROJECT) $(DEV_ENV) $(BASE_COMPOSE) $(DEV_COMPOSE)
	@echo ""
	@echo "  Console:  http://localhost:5173"
	@echo "  Login:    admin@example.com / devpassword123  (you'll be asked to change it on first login)"
	@echo "  API key:  tk_live_seedkey  (seed tenant, for API use)"
	@echo "  Note:     add an Anthropic API key in Settings > Credentials before running tasks"
	@echo ""

stop:
	sh deploy/scripts/stop-agents.sh
	-$(DEV_DC) down

logs:
	$(DEV_DC) logs -f --tail=200

prod: ensure-agent-image
	@test -f $(PROD_ENV) || { echo "Missing $(PROD_ENV). Copy deploy/.env.example and fill it in."; exit 1; }
	@! grep -q "change-me" $(PROD_ENV) || { echo "$(PROD_ENV) still has placeholder values (change-me). Fill in real secrets."; exit 1; }
	$(PROD_DC) up -d --build

prod-stop:
	sh deploy/scripts/stop-agents.sh
	-$(PROD_DC) down

smoke:
	sh deploy/scripts/smoke.sh
