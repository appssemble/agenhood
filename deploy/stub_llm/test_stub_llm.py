import json

from app import app, extract_script
from fastapi.testclient import TestClient

client = TestClient(app)


def _script_prompt(script: dict) -> str:
    return "do the thing\n@@SCRIPT@@ " + json.dumps(script)


def test_legacy_default_unchanged():
    body = {"model": "claude-stub",
            "messages": [{"role": "user", "content": "research email"}]}
    r = client.post("/v1/messages", json=body)
    assert r.status_code == 200
    assert r.json()["content"][0]["text"] == "Searching the web."


def test_script_done_first_turn():
    script = {"turns": [{"done": {"success": True, "output": {"ok": 1}}}],
              "usage": {"input_tokens": 7, "output_tokens": 3}}
    body = {"model": "m", "messages": [{"role": "user",
            "content": _script_prompt(script)}]}
    r = client.post("/v1/messages", json=body)
    data = r.json()
    block = data["content"][0]
    assert block["name"] == "done"
    assert block["input"] == {"success": True, "output": {"ok": 1}}
    assert data["usage"] == {"input_tokens": 7, "output_tokens": 3}


def test_script_http_error():
    script = {"turns": [], "http_error": {"status": 529}}
    body = {"model": "m", "messages": [{"role": "user",
            "content": _script_prompt(script)}]}
    r = client.post("/v1/messages", json=body)
    assert r.status_code == 529


def test_extract_script_absent_returns_none():
    assert extract_script("no directive here") is None
