"""Shared HTTP helpers for the OAuth clients (anthropic_oauth, openai_oauth).

Dependency-free by design: this module imports NOTHING from either oauth module,
so the anthropic_oauth -> openai_oauth ``DeviceFlowError`` import chain cannot
become circular.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

log = logging.getLogger("oauth")

TIMEOUT = 15.0


def safe_json(resp: httpx.Response) -> dict[str, Any]:
    """Return the response JSON as a dict, or ``{}`` if it is not valid JSON / not a dict."""
    try:
        data = resp.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}
