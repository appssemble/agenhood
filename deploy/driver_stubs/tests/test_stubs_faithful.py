import json
import os
import subprocess
import sys

STUBS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Import the real driver parse functions to prove the stub output is faithful.
REPO = os.path.dirname(os.path.dirname(STUBS))
sys.path.insert(0, os.path.join(REPO, "packages", "agentcore"))

from agentcore.drivers import opencode as oc  # noqa: E402


def _script(d):
    return "task\n@@SCRIPT@@ " + json.dumps(d)


def _run_argv_stub(name, script, cwd):
    return subprocess.run(
        [os.path.join(STUBS, name), "--", _script(script)],
        capture_output=True, text=True, cwd=cwd,
    )


def test_opencode_success_parses_to_text_and_usage(tmp_path):
    script = {"turns": [{"text": "the answer",
                         "done": {"success": True, "output": "the answer"}}],
              "usage": {"input_tokens": 11, "output_tokens": 4}}
    proc = _run_argv_stub("opencode", script, str(tmp_path))
    assert proc.returncode == 0, proc.stderr
    last_text, tin, tout = None, 0, 0
    for line in proc.stdout.splitlines():
        kind, ev = oc.parse_opencode_line(line)
        if kind != "event":
            continue
        if oc.event_text(ev) is not None:
            last_text = oc.event_text(ev)
        u = oc.event_tokens(ev)
        if u:
            tin, tout = tin + u[0], tout + u[1]
    assert last_text == "the answer"
    assert (tin, tout) == (11, 4)


def test_opencode_error_exits_nonzero_with_error_event(tmp_path):
    script = {"turns": [{"done": {"success": False, "reason": "boom"}}]}
    proc = _run_argv_stub("opencode", script, str(tmp_path))
    assert proc.returncode != 0
    msgs = [oc.event_error(oc.parse_opencode_line(l)[1])
            for l in proc.stdout.splitlines()
            if oc.parse_opencode_line(l)[0] == "event"]
    assert "boom" in [m for m in msgs if m]


def test_opencode_writes_workspace_file(tmp_path):
    script = {"turns": [{"tool": "write_file",
                         "input": {"path": "out.md", "content": "X"}},
                        {"done": {"success": True, "output": "ok"}}]}
    proc = _run_argv_stub("opencode", script, str(tmp_path))
    assert proc.returncode == 0, proc.stderr
    assert (tmp_path / "out.md").read_text() == "X"


from agentcore.drivers import codex as cx  # noqa: E402


def _run_stdin_stub(name, script, cwd):
    return subprocess.run(
        [os.path.join(STUBS, name)],
        input=_script(script), capture_output=True, text=True, cwd=cwd,
    )


def test_codex_success_parses_to_text_and_usage(tmp_path):
    script = {"turns": [{"done": {"success": True, "output": "done text"}}],
              "usage": {"input_tokens": 9, "output_tokens": 3}}
    proc = _run_stdin_stub("codex", script, str(tmp_path))
    assert proc.returncode == 0, proc.stderr
    last_text, tin, tout = None, 0, 0
    for line in proc.stdout.splitlines():
        kind, ev = cx.parse_codex_line(line)
        if kind != "event":
            continue
        if cx.event_text(ev) is not None:
            last_text = cx.event_text(ev)
        u = cx.event_usage(ev)
        if u:
            tin, tout = tin + u[0], tout + u[1]
    assert last_text == "done text"
    assert (tin, tout) == (9, 3)


def test_codex_error_turn_failed(tmp_path):
    script = {"turns": [{"done": {"success": False, "reason": "nope"}}]}
    proc = _run_stdin_stub("codex", script, str(tmp_path))
    assert proc.returncode != 0
    errs = [cx.event_error(cx.parse_codex_line(l)[1])
            for l in proc.stdout.splitlines()
            if cx.parse_codex_line(l)[0] == "event"]
    assert "nope" in [e for e in errs if e]


from agentcore.drivers import claude_code as cc  # noqa: E402


def test_claude_success_parses_to_text_and_usage(tmp_path):
    script = {"turns": [{"done": {"success": True, "output": "final"}}],
              "usage": {"input_tokens": 6, "output_tokens": 2}}
    proc = _run_stdin_stub("claude", script, str(tmp_path))
    assert proc.returncode == 0, proc.stderr
    last_text, tin, tout = None, 0, 0
    for line in proc.stdout.splitlines():
        kind, ev = cc.parse_claude_line(line)
        if kind != "event":
            continue
        if cc.result_text(ev) is not None:
            last_text = cc.result_text(ev)
        u = cc.result_usage(ev)
        if u:
            tin, tout = tin + u[0], tout + u[1]
    assert last_text == "final"
    assert (tin, tout) == (6, 2)


def test_claude_is_error_result(tmp_path):
    script = {"turns": [{"done": {"success": False, "reason": "bad"}}]}
    proc = _run_stdin_stub("claude", script, str(tmp_path))
    errs = [cc.result_error(cc.parse_claude_line(l)[1])
            for l in proc.stdout.splitlines()
            if cc.parse_claude_line(l)[0] == "event"]
    assert proc.returncode == 0  # claude exits 0 even on error; failure is signalled via is_error
    assert "bad" in [e for e in errs if e]
