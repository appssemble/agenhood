import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _stublib as s  # noqa: E402


def _d(script):
    return "go\n@@SCRIPT@@ " + json.dumps(script)


def test_parse_directive_present_and_absent():
    assert s.parse_directive(_d({"a": 1})) == {"a": 1}
    assert s.parse_directive("nothing") == {}


def test_final_text_prefers_done_output_string():
    assert s.final_text({"turns": [{"done": {"success": True,
                                             "output": "hello"}}]}) == "hello"


def test_final_text_serializes_structured_output():
    out = s.final_text({"turns": [{"done": {"success": True,
                                            "output": {"k": 1}}}]})
    assert json.loads(out) == {"k": 1}


def test_materialize_files(tmp_path):
    script = {"turns": [{"tool": "write_file",
                         "input": {"path": "a/b.txt", "content": "hi"}}]}
    s.materialize_files(script, str(tmp_path))
    assert (tmp_path / "a" / "b.txt").read_text() == "hi"


def test_usage_defaults():
    assert s.usage({}) == (0, 0)
    assert s.usage({"usage": {"input_tokens": 5, "output_tokens": 2}}) == (5, 2)
