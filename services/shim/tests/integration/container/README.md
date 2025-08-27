# Container Integration Suite

Tests the **real agent container** end-to-end with the model/CLI seam stubbed.
The production image is unchanged; stubs are injected only by
`deploy/docker-compose.shim-it.yml` (bind-mount `deploy/driver_stubs/` +
`PATH` prepend) and the enhanced `deploy/stub_llm`.

## Run

```bash
make -C images/agent image
python -m pytest services/shim/tests/integration/container/ -m integration -v
```

Requires Docker. The `stack` fixture (in `conftest.py`) builds the image, runs
`compose up`, waits for `/healthz`, and tears down with `down -v` on exit.
Without Docker the module skips via the `docker_or_skip` fixture.

Set `REQUIRE_DOCKER=1` to turn a skip into a hard failure (useful in CI).

## The @@SCRIPT@@ directive

Each task's behavior is encoded in its prompt as `@@SCRIPT@@ {json}` and
replayed by the per-driver stub as a pure function of the request (no shared
state — concurrency-safe). Schema:

```jsonc
{
  "turns": [
    {"text": "thinking aloud…"},
    {"tool": "write_file", "input": {"path": "out.txt", "content": "hello"}},
    {"done": {"success": true, "output": "all done"}}
  ],
  "usage": {"input_tokens": 10, "output_tokens": 5},
  "delay_ms": 0,
  "http_error": {"status": 529},
  "malformed": false,
  "never_done": false
}
```

Field reference:

| Field | Effect |
|---|---|
| `turns` | Sequence of text narrations, tool calls, and the terminal `done` marker |
| `usage` | Token counts reported back in the task status |
| `delay_ms` | Sleep before emitting output (latency simulation) |
| `http_error` | The stub returns this HTTP status instead of a valid response |
| `malformed` | The stub emits unparseable output instead of valid JSONL/SSE |
| `never_done` | The stub loops forever (timeout tests) |

Build payloads with `scripting.task_body(...)` and `scripting.script_prompt(...)`;
never hand-write the directive.

### How each driver stub reads the script

| Driver | Source | Output format |
|---|---|---|
| `vanilla` | `stub_llm` service (HTTP SSE) | Anthropic SSE stream |
| `opencode` | positional argv (`sys.argv[-1]`) | OpenCode JSONL |
| `codex` | stdin (`sys.stdin.read()`) | Codex JSONL |
| `claude-code` | stdin (`sys.stdin.read()`) | Claude-Code JSONL |

The stubs share `_stublib.py` helpers (`read_script`, `materialize_files`,
`final_text`, `is_error`, `is_malformed`, `is_never_done`, `usage`,
`error_message`, `hang_forever`, `maybe_sleep`).

## Lean compose stack

`deploy/docker-compose.shim-it.yml` starts two services:

```
stub-llm   → localhost:19001  (Anthropic SSE stub, for the vanilla driver)
agent      → localhost:8080   (real agent-runtime image, stubs on PATH)
```

The agent container is configured with:
- `SHIM_TOKEN=test-shim-token` (tests send `Authorization: Bearer test-shim-token`)
- `ANTHROPIC_BASE_URL=http://stub-llm:9000` (vanilla driver points here)
- `PATH` prepended with `/opt/driver-stubs` (so `opencode`, `codex`,
  `claude` resolve to our fakes instead of real CLIs)
- `deploy/driver_stubs/` bind-mounted read-only at `/opt/driver-stubs`

The production image is **not rebuilt** between test runs; only the stub
mount changes.

## Test modules

| Module | What it covers |
|---|---|
| `test_driver_matrix.py` | success / model-error / file-write for all 4 drivers; meta-gate |
| `test_events.py` | SSE event stream shape, turn events, token counts |
| `test_concurrency.py` | 429 back-pressure, per-task isolation, cancel, shutdown, dup-submit |
| `test_files.py` | multi-step tool chains, file listing, directory creation |
| `test_git.py` | git diff output, commit log, scratch-file workspace hygiene |
| `test_errors.py` | 5xx / overloaded / malformed / model-error / timeout / bad-payload / 404 |
| `test_auth.py` | missing / invalid / expired token → 401/403 |
| `test_boundary.py` | privilege separation, extended scenario, legacy fold |

## Driver-stub faithfulness cross-check

The stubs in `deploy/driver_stubs/` are unit-tested against the **real parser
functions** from `agentcore.drivers.*` (not just a corpus snapshot).

```bash
packages/agentcore/.venv/bin/python -m pytest deploy/driver_stubs/tests/ \
    deploy/stub_llm/test_stub_llm.py -v
```

Each faithfulness case:
1. Calls the stub with a known `@@SCRIPT@@`.
2. Parses the stub's output with the same function the driver uses at runtime.
3. Asserts the parsed result matches the expected task outcome.

This ensures a stub update that silently breaks the contract is caught before
the container suite ever runs.

## Adding a new driver/stub

1. **Write the stub** at `deploy/driver_stubs/<binary>` (executable, no
   extension). It should call `_stublib.read_script("argv")` (positional
   prompt CLIs) or `_stublib.read_script("stdin")` (piped input) and emit
   the driver's native JSONL format using the `_stublib` helpers.

2. **Add a faithfulness test** in `deploy/driver_stubs/tests/test_stubs_faithful.py`
   that drives your stub and parses its output with the real driver parser.

3. **Register the driver name** in `ALL_DRIVERS` inside
   `test_driver_matrix.py`.

4. `test_meta_all_registered_drivers_in_matrix` (in `test_driver_matrix.py`)
   will fail until **both** the driver is registered in `agentcore.drivers`
   **and** its name appears in `ALL_DRIVERS`. This is the enforcement gate.
