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
from agentcore.drivers.cli_stream import classify_json_line  # noqa: E402


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
        kind, ev = classify_json_line(line)
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
    errs = [cx.event_error(classify_json_line(l)[1])
            for l in proc.stdout.splitlines()
            if classify_json_line(l)[0] == "event"]
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


import itertools  # noqa: E402

from agentcore.drivers.codex_events import ExecEventTranslator  # noqa: E402


def _app_server_session(script, cwd, requests=None):
    reqs = requests or [
        {"id": 1, "method": "initialize", "params": {}},
        {"method": "initialized"},
        {"id": 2, "method": "thread/start", "params": {}},
        {"id": 3, "method": "turn/start",
         "params": {"threadId": "t", "input": [{"type": "text", "text": _script(script)}]}},
        {"id": 4, "method": "thread/delete", "params": {"threadId": "t"}},
    ]
    proc = subprocess.run(
        [os.path.join(STUBS, "codex"), "app-server", "-c", "features.apps=false"],
        input="".join(json.dumps(r) + "\n" for r in reqs),
        capture_output=True, text=True, cwd=cwd, timeout=20,
    )
    return proc, [json.loads(ln) for ln in proc.stdout.splitlines() if ln.startswith("{")]


def _translate(messages):
    tr = ExecEventTranslator()
    return list(itertools.chain.from_iterable(
        tr.translate(m) for m in messages if "method" in m))


def test_codex_app_server_replies_to_every_request(tmp_path):
    script = {"turns": [{"done": {"success": True, "output": "hi"}}]}
    proc, msgs = _app_server_session(script, str(tmp_path))
    assert proc.returncode == 0, proc.stderr
    replies = {m["id"]: m for m in msgs if "id" in m}
    assert set(replies) == {1, 2, 3, 4}
    assert replies[2]["result"]["thread"]["id"]


def test_codex_app_server_success_translates_to_exec_events(tmp_path):
    script = {"turns": [{"done": {"success": True, "output": "done text"}}],
              "usage": {"input_tokens": 9, "output_tokens": 3}}
    _, msgs = _app_server_session(script, str(tmp_path))
    events = _translate(msgs)
    assert [e["type"] for e in events] == ["turn.started", "item.completed", "turn.completed"]
    assert events[1]["item"]["text"] == "done text"
    assert events[2]["usage"]["input_tokens"] == 9
    assert events[2]["usage"]["output_tokens"] == 3


def test_codex_app_server_error_fails_the_turn(tmp_path):
    script = {"turns": [{"done": {"success": False, "reason": "nope"}}]}
    _, msgs = _app_server_session(script, str(tmp_path))
    events = _translate(msgs)
    assert events[-1] == {"type": "turn.failed", "error": {"message": "nope"}}


def test_codex_app_server_writes_workspace_file(tmp_path):
    script = {"turns": [{"tool": "write_file",
                         "input": {"path": "out.md", "content": "X"}},
                        {"done": {"success": True, "output": "ok"}}]}
    _app_server_session(script, str(tmp_path))
    assert (tmp_path / "out.md").read_text() == "X"


def test_codex_app_server_unknown_method_is_a_rpc_error(tmp_path):
    reqs = [{"id": 1, "method": "bogus/method", "params": {}}]
    _, msgs = _app_server_session({}, str(tmp_path), reqs)
    assert msgs[0]["error"]["code"] == -32601


def test_codex_app_server_threads_get_unique_ids(tmp_path):
    reqs = [{"id": 1, "method": "thread/start", "params": {}},
            {"id": 2, "method": "thread/start", "params": {}}]
    _, msgs = _app_server_session({}, str(tmp_path), reqs)
    ids = [m["result"]["thread"]["id"] for m in msgs]
    assert ids[0] != ids[1]
