"""Model catalog: classification of `opencode models` ids into a categorized,
credential-aware, driver-aware catalog; plus runtime load/validate/availability.

The base catalog is a build artifact (model_catalog.json) regenerated only when
the agent image / opencode version changes (see scripts/gen_model_catalog.py).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("model_catalog")

# Non-conversational model classes that opencode lists but the platform can't run
# as a chat task (embeddings, image, audio/tts, moderation, realtime).
_NON_CHAT_SUBSTRINGS = (
    "embedding", "dall-e", "dalle", "-image", "image-", "whisper",
    "tts-", "-tts", "-audio", "audio-", "transcribe", "moderation", "realtime",
)


def _is_chat_model(model_id: str) -> bool:
    name = model_id.split("/", 1)[-1].lower()
    return not any(s in name for s in _NON_CHAT_SUBSTRINGS)


# Providers the platform supports, mapped to the api-key credential method.
_API_KEY_METHOD = {"anthropic": "anthropic_api_key", "openai": "openai_api_key"}
# Drivers that can run a given provider's models. claude-code is intentionally
# absent here: the bundled `claude` CLI only honors family aliases (it silently
# falls back to its default model for any full/dated id it doesn't serve), so we
# offer claude-code exclusively through the alias entries below, never the
# full-name anthropic models.
_PROVIDER_DRIVERS = {
    "opencode": ["opencode"],          # Zen keyless
    "anthropic": ["opencode", "vanilla"],
    "openai": ["opencode", "codex"],
}

# The only model ids the claude-code driver offers. The `claude` CLI resolves
# these aliases to the latest model of each family at run time (e.g.
# `--model opus`), so selection always takes effect and never silently degrades
# to the CLI default. Mirrors the codex pattern of an authoritative runnable set.
_CLAUDE_CODE_ALIASES = ("opus", "sonnet", "haiku")


def _claude_code_alias_entries() -> list[dict]:  # type: ignore[type-arg]
    return [
        {
            "id": alias,
            "provider": "anthropic",
            "label": alias,
            "category": "api_key",
            "credentials": ["anthropic_api_key", "anthropic_subscription"],
            "drivers": ["claude-code"],
        }
        for alias in _CLAUDE_CODE_ALIASES
    ]


def _label(model_id: str) -> str:
    return model_id.split("/", 1)[1] if "/" in model_id else model_id


def _codex_can_run(entry_id: str) -> bool:
    """Legacy substring heuristic: treat ``*codex*`` ids as Codex-runnable.

    Only used as a fallback when no authoritative codex model list is available
    at build time. It is wrong in both directions — it lets through models a
    ChatGPT account rejects at run time (e.g. ``gpt-5.3-codex``) and drops models
    Codex can actually run (e.g. ``gpt-5.4``) — so prefer ``codex_ids`` from
    ``codex debug models`` whenever it can be obtained (see scripts/gen_model_catalog.py).
    """
    return "codex" in entry_id.lower()


def _codex_runnable(entry_id: str, codex_ids: set[str] | None) -> bool:
    """Whether the codex driver should be offered for ``entry_id``.

    ``codex_ids`` is the authoritative set of Codex-runnable model slugs from
    ``codex debug models``; when provided, membership is exact. ``None`` means no
    such list was available, so fall back to the substring heuristic.
    """
    if codex_ids is None:
        return _codex_can_run(entry_id)
    return entry_id in codex_ids


def _drivers_for(
    provider: str, entry_id: str, codex_ids: set[str] | None = None
) -> list[str]:
    """Per-model driver list: the provider's drivers, minus ``codex`` for any
    OpenAI model Codex can't run."""
    drivers = list(_PROVIDER_DRIVERS.get(provider, []))
    if "codex" in drivers and not _codex_runnable(entry_id, codex_ids):
        drivers.remove("codex")
    return drivers


def build_catalog_entries(
    base_ids: list[str],
    sub_ids: list[str],
    codex_ids: list[str] | None = None,
) -> list[dict]:  # type: ignore[type-arg]
    """Classify `opencode models` ids into catalog entries (pure).

    base_ids:  from a query with placeholder api keys (free + anthropic + openai api).
    sub_ids:   from a query with a real ChatGPT token (openai Codex subscription set).
    codex_ids: authoritative Codex-runnable model slugs from ``codex debug models``
               (visibility == "list"). When ``None``, codex-driver membership falls
               back to the ``*codex*`` substring heuristic.
    """
    sub_set = {m for m in sub_ids if m.startswith("openai/")}
    codex_set = None if codex_ids is None else set(codex_ids)
    out: list[dict] = []  # type: ignore[type-arg]
    seen: set[str] = set()

    for model_id in [*base_ids, *sub_ids]:
        if "/" not in model_id:
            continue
        if not _is_chat_model(model_id):
            continue
        provider = model_id.split("/", 1)[0]
        drivers = _PROVIDER_DRIVERS.get(provider)
        if drivers is None:
            continue  # unsupported provider

        entry_id = model_id if provider == "opencode" else model_id.split("/", 1)[1]
        if entry_id in seen:
            continue
        seen.add(entry_id)

        if provider == "opencode":
            category, creds = "free", ["keyless"]
        elif provider == "anthropic":
            category, creds = "api_key", ["anthropic_api_key", "anthropic_subscription"]
        else:  # openai
            in_base = model_id in base_ids
            in_sub = model_id in sub_set
            if in_base and in_sub:
                category, creds = "api_key", ["openai_api_key", "openai_subscription"]
            elif in_sub:
                category, creds = "subscription", ["openai_subscription"]
            else:
                category, creds = "api_key", ["openai_api_key"]

        out.append({
            "id": entry_id,
            "provider": provider,
            "label": _label(model_id),
            "category": category,
            "credentials": creds,
            "drivers": _drivers_for(provider, entry_id, codex_set),
        })
    # claude-code is offered only via family aliases (see _CLAUDE_CODE_ALIASES).
    out.extend(_claude_code_alias_entries())
    return out


@dataclass(frozen=True)
class ModelEntry:
    id: str
    provider: str
    label: str
    category: str
    credentials: tuple[str, ...]
    drivers: tuple[str, ...]


def _default_path() -> Path:
    return Path(__file__).with_name("model_catalog.json")


def load_catalog(path: Path | None = None) -> list[ModelEntry]:
    """Load the committed catalog artifact. Returns [] (logged) if missing/invalid."""
    p = path or _default_path()
    try:
        data = json.loads(p.read_text())
    except (OSError, ValueError):
        log.warning("model_catalog: could not load %s; serving empty catalog", p)
        return []
    return [
        ModelEntry(
            id=m["id"], provider=m["provider"], label=m["label"], category=m["category"],
            credentials=tuple(m.get("credentials", [])), drivers=tuple(m.get("drivers", [])),
        )
        for m in data.get("models", [])
    ]


def is_valid(catalog: list[ModelEntry], model_id: str, driver: str) -> bool:
    """True if the model exists in the catalog AND the driver can run it.

    If the catalog is empty (artifact missing), returns True so submissions are
    not blocked by a missing build artifact.
    """
    if not catalog:
        return True
    for e in catalog:
        if e.id == model_id:
            return driver in e.drivers
    return False


# Per driver, the providers whose ``oauth_subscription`` the driver can actually
# consume. Each driver shells out to a CLI/SDK whose subscription support is
# provider-specific:
#   - opencode / codex register only the OpenAI (Codex) backend from an OAuth
#     credential, so an *anthropic* subscription cannot drive them.
#   - claude-code is anthropic-only and is built around the anthropic subscription.
#   - vanilla calls the raw Anthropic API with ``x-api-key``, which an OAuth token
#     is not — it needs an API key.
# A provider NOT listed for a driver requires an API key for that driver; a
# subscription alone does not make its models runnable there.
_DRIVER_SUBSCRIPTION_PROVIDERS: dict[str, set[str]] = {
    "vanilla": set(),
    "opencode": {"openai"},
    "codex": {"openai"},
    "claude-code": {"anthropic"},
}


def driver_can_use_subscription(driver: str, provider: str) -> bool:
    """Whether ``driver`` can run a ``provider`` model from an oauth subscription."""
    return provider in _DRIVER_SUBSCRIPTION_PROVIDERS.get(driver, set())


def _driver_usable_credentials(driver: str | None, creds: tuple[str, ...]) -> list[str]:
    """The subset of a model's credential methods that ``driver`` can actually use.

    Without a driver (the unfiltered list) every method is usable — some driver
    can. With a driver, a ``*_subscription`` method is dropped unless that driver
    supports that provider's subscription (see _DRIVER_SUBSCRIPTION_PROVIDERS), so
    e.g. an anthropic model is not reported runnable on opencode/vanilla from a
    subscription alone.
    """
    if driver is None:
        return list(creds)
    usable: list[str] = []
    for c in creds:
        if c.endswith("_subscription"):
            sub_provider = c[: -len("_subscription")]
            if not driver_can_use_subscription(driver, sub_provider):
                continue
        usable.append(c)
    return usable


def methods_from_credential_rows(rows: list[dict]) -> set[str]:  # type: ignore[type-arg]
    """Map a tenant's credential rows to the catalog credential-method set.

    `keyless` is always present. Each row contributes its method if active.
    """
    methods: set[str] = {"keyless"}
    for r in rows:
        provider, auth_method = r.get("provider"), r.get("auth_method")
        if auth_method == "oauth_subscription" and provider == "openai":
            if r.get("status", "active") == "active":
                methods.add("openai_subscription")
        elif auth_method == "oauth_subscription" and provider == "anthropic":
            if r.get("status", "active") == "active":
                methods.add("anthropic_subscription")
        elif auth_method == "api_key":
            m = _API_KEY_METHOD.get(provider or "")
            if m:
                methods.add(m)
    return methods


def annotate(
    catalog: list[ModelEntry], driver: str | None, methods: set[str]
) -> list[dict]:  # type: ignore[type-arg]
    """Filter the catalog by driver and annotate availability for the given methods."""
    out: list[dict] = []  # type: ignore[type-arg]
    for e in catalog:
        if driver is not None and driver not in e.drivers:
            continue
        # Only count credentials the requested driver can actually use, so a model
        # is not advertised as runnable from a subscription the driver can't honor.
        usable = _driver_usable_credentials(driver, e.credentials)
        satisfied = [c for c in usable if c in methods]
        out.append({
            "id": e.id, "provider": e.provider, "label": e.label,
            "category": e.category, "drivers": list(e.drivers),
            "available": bool(satisfied),
            "requires": [] if satisfied else [c for c in usable if c != "keyless"],
        })
    return out
