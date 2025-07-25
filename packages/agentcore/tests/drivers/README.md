# Driver conformance suite

Golden-snapshot tests that lock each driver's observable runtime contract:
driver metadata/capabilities, emitted event streams (success/error/multi-step +
cancel/timeout/missing-binary), and cross-driver security invariants. Static
render surfaces (argv, env, MCP/skill renders, auth files) are covered by the
per-driver helper tests (`test_*_helpers.py`, `test_mcp_config.py`,
`test_skills_md.py`, oauth tests), not here.

## Running
From `packages/agentcore/`: `.venv/bin/python -m pytest tests/drivers/conformance -q`

## Regenerating goldens
After an INTENTIONAL contract change, regenerate and review the diff:
`UPDATE_GOLDEN=1 .venv/bin/python -m pytest tests/drivers/conformance -q`
Never commit a golden you have not eyeballed — the diff IS the review.

## Corpus
`corpus/<driver>/*.jsonl` is real CLI output captured ONCE and committed. To
refresh after a CLI upgrade: run the real binary on a throwaway task, scrub
secrets, replace the file, regenerate the affected `events_*` goldens, review.

## Adding a driver
Add it to `ALL_DRIVERS` in `conformance/matrix.py` and regenerate goldens; the
meta-test fails until every applicable scenario has a golden.
