# images/agent/Makefile
VERSION  ?= 1.0.0
REGISTRY ?=
IMAGE    := $(REGISTRY)agent-runtime
# Build context is the monorepo root (two levels up from this Makefile).
ROOT     := ../..

.PHONY: image image-slim
image:
	docker buildx build --build-arg VARIANT=full \
	  -f Dockerfile \
	  -t $(IMAGE):$(VERSION) -t $(IMAGE):$(VERSION)-full -t $(IMAGE):latest \
	  $(ROOT)

image-slim:
	docker buildx build --build-arg VARIANT=slim \
	  -f Dockerfile \
	  -t $(IMAGE):$(VERSION)-slim \
	  $(ROOT)

# Multi-arch build + push to a registry (linux/amd64 + linux/arm64).
# REGISTRY must end with a trailing slash, e.g. registry.example.com/
# Requires: docker buildx with a builder that has QEMU for the foreign arch.
.PHONY: image-push
image-push:
	@test -n "$(REGISTRY)" || { echo "REGISTRY required, e.g. REGISTRY=registry.example.com/"; exit 1; }
	docker buildx build --build-arg VARIANT=full \
	  --platform linux/amd64,linux/arm64 \
	  -f Dockerfile \
	  -t $(REGISTRY)agent-runtime:$(VERSION) \
	  -t $(REGISTRY)agent-runtime:$(VERSION)-full \
	  --push \
	  $(ROOT)
