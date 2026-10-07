"""Record ``codex exec --json`` and ``codex app-server`` streams for the same tasks.

Feeds the translator tests (packages/agentcore/tests/drivers/fixtures/codex_streams).
Run inside the agent image with a logged-in CODEX_HOME:

    docker run --rm -i -u root -e CODEX_HOME=/ch -v <codex-home>:/ch -v <out>:/out \\
      -v $PWD/scripts/record_codex_streams.py:/rec.py:ro \\
      --entrypoint /opt/venv/bin/python ghcr.io/appssemble/agent-runtime:<tag> /rec.py --out /out

Check the output for tokens before committing it.
"""

import argparse
import asyncio
import json
import os
import shutil

from agentcore.drivers.codex import SIDE_CHANNEL_OVERRIDES, tool_args

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["answer"],
    "properties": {"answer": {"type": "string"}},
}

CASES = {
    "plain": {"prompt": "Reply with exactly OK."},
    "shell": {
        "prompt": "Run the shell command `echo hello` and reply with its output only."
    },
    "file_edit": {
        "prompt": "Create a file named note.txt containing the word hi, then reply DONE."
    },
    "web_search": {
        "prompt": "Use web search to find the latest stable Python version. "
                  "Reply with the version only."
    },
    "reasoning": {"prompt": "A bat and a ball cost 1.10 in total. The bat costs 1.00 more than "
                            "the ball. Then a second ball costs twice the first. Work it out step "
                            "by step and reply with the price of the second ball only.",
                  "summary": True, "effort": "high"},
    "structured": {"prompt": "Reply with the answer OK.", "schema": SCHEMA},
    "failed": {"prompt": "Reply OK.", "model": "gpt-does-not-exist"},
}


def overrides(case: dict) -> list[str]:
    out = [arg for o in SIDE_CHANNEL_OVERRIDES for arg in ("-c", o)]
    out += tool_args(["web_search"])
    if case.get("effort"):
        out += ["-c", f"model_reasoning_effort={case['effort']}"]
    if case.get("summary"):
        out += ["-c", "model_reasoning_summary=auto"]
    return out


async def record_exec(ws: str, model: str, case: dict) -> list:
    cmd = ["codex", "exec", "--json", "--skip-git-repo-check", "--ephemeral", "-C", ws,
           "-m", case.get("model", model), *overrides(case)]
    if case.get("schema"):
        schema_path = os.path.join(ws, "schema.json")
        with open(schema_path, "w") as f:
            json.dump(case["schema"], f)
        cmd += ["--output-schema", schema_path]
    cmd += ["--dangerously-bypass-approvals-and-sandbox", "-"]
    proc = await asyncio.create_subprocess_exec(
        *cmd, cwd=ws, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT, limit=1 << 24,
    )
    proc.stdin.write(case["prompt"].encode())
    proc.stdin.close()
    out = []
    async for raw in proc.stdout:
        line = raw.decode(errors="replace").rstrip("\n")
        try:
            out.append(json.loads(line))
        except ValueError:
            out.append({"_stdout": line})
    out.append({"_exit": await proc.wait()})
    return out


async def record_app_server(ws: str, model: str, case: dict) -> list:
    proc = await asyncio.create_subprocess_exec(
        "codex", "app-server", *overrides(case), cwd=ws, stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, limit=1 << 24,
    )
    out: list = []
    done = asyncio.Event()
    replies: dict[int, asyncio.Future] = {}

    def send(msg: dict) -> None:
        proc.stdin.write((json.dumps(msg) + "\n").encode())

    async def reader() -> None:
        async for raw in proc.stdout:
            msg = json.loads(raw)
            out.append(msg)
            if "id" in msg and ("result" in msg or "error" in msg):
                replies.pop(msg["id"]).set_result(msg)
            elif "id" in msg:
                send({"id": msg["id"], "error": {"code": -32601, "message": "declined"}})
            elif msg.get("method") == "turn/completed":
                done.set()
        done.set()

    async def call(i: int, method: str, params: dict) -> dict:
        replies[i] = asyncio.get_running_loop().create_future()
        send({"id": i, "method": method, "params": params})
        return await replies[i]

    task = asyncio.create_task(reader())
    await call(1, "initialize", {"clientInfo": {"name": "recorder", "version": "0"}})
    send({"method": "initialized"})
    started = await call(2, "thread/start", {
        "model": case.get("model", model), "cwd": ws, "ephemeral": True,
        "approvalPolicy": "never", "sandbox": "danger-full-access",
    })
    if "result" in started:
        params = {"threadId": started["result"]["thread"]["id"],
                  "input": [{"type": "text", "text": case["prompt"]}]}
        if case.get("schema"):
            params["outputSchema"] = case["schema"]
        turn = await call(3, "turn/start", params)
        if "result" in turn:
            await asyncio.wait_for(done.wait(), 180)
    proc.stdin.close()
    try:
        await asyncio.wait_for(proc.wait(), 10)
    except TimeoutError:
        proc.kill()
    await task
    return out


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="gpt-5.6-sol")
    parser.add_argument("--out", required=True)
    parser.add_argument("--cases", default=",".join(CASES))
    args = parser.parse_args()
    os.makedirs(args.out, exist_ok=True)
    for name in args.cases.split(","):
        case = CASES[name]
        result = {"case": name}
        for mode, record in (("exec", record_exec), ("app_server", record_app_server)):
            ws = f"/tmp/ws-{name}-{mode}"
            shutil.rmtree(ws, ignore_errors=True)
            os.makedirs(ws)
            result[mode] = await record(ws, args.model, case)
        with open(os.path.join(args.out, f"{name}.json"), "w") as f:
            json.dump(result, f, indent=1)
        print(
            name,
            "exec",
            len(result["exec"]),
            "app_server",
            len(result["app_server"]),
            flush=True,
        )


asyncio.run(main())
