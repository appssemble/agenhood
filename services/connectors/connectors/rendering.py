from __future__ import annotations

from typing import Any

_TRUNC = "…(continued)"


class TranscriptRenderer:
    """Accumulates task events into one provider message body.

    `surface` controls which event classes appear: "reasoning"
    (assistant_message), "tools" (tool_call/tool_result), "result"
    (the final status_change output).
    """

    def __init__(self, *, surface: list[str], max_chars: int = 3500):
        self.surface = set(surface)
        self.max_chars = max_chars
        self._lines: list[str] = []
        self.is_final = False
        self._final_body = ""

    def ingest(self, event: dict[str, Any]) -> bool:
        """Add an event. Returns True if this event is terminal (finalizes)."""
        etype = event.get("type")
        payload = event.get("payload", {})
        if etype == "assistant_message" and "reasoning" in self.surface:
            text = _text_from_content(payload.get("content", []))
            if text:
                self._lines.append(text)
        elif etype == "tool_call" and "tools" in self.surface:
            name = payload.get("name", "tool")
            cmd = payload.get("input", {}).get("command") or ""
            self._lines.append(f"🔧 {name}: {cmd}".rstrip())
        elif etype == "tool_result" and "tools" in self.surface:
            ok = payload.get("ok", True)
            self._lines.append("  ✓ done" if ok else "  ✗ failed")
        elif etype == "status_change":
            to = payload.get("to")
            if to in ("succeeded", "failed", "error", "cancelled", "canceled"):
                self.is_final = True
                if payload.get("error"):
                    self._final_body = f"❌ {payload['error'].get('message', 'failed')}"
                else:
                    out = (payload.get("result") or {}).get("output", "")
                    self._final_body = f"✅ {out}"
                return True
        return False

    def render(self) -> str:
        if self.is_final:
            body = self._final_body
        else:
            body = "🤖 working…\n\n" + "\n".join(self._lines)
        if len(body) > self.max_chars:
            body = body[: self.max_chars] + "\n" + _TRUNC
        return body


def _text_from_content(content: list[dict[str, Any]]) -> str:
    parts = [c.get("text", "") for c in content if c.get("type") == "text"]
    return " ".join(p for p in parts if p).strip()
