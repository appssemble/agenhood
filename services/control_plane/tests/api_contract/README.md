# Control-plane API contract gates (Unit C)

Three meta-gates lock the HTTP surface so it cannot regress or grow untested:

- `test_route_inventory.py` — every registered route on `create_app(...)` has a
  CONTRACTS entry (auth→401 / public→non-401 / redirect→308). A new route with
  no entry fails the gate. Allow-list: FastAPI docs/openapi/redoc only.
- `test_role_matrix_gate.py` — every role-gated route maps to a known gate helper
  (require_admin/require_session_admin/require_staff) or an explicit
  SELF_SCOPED_MUTATIONS entry; a gate-class × principal matrix asserts allow/deny.
- `test_error_envelope.py` — every APIError response is `{"error":{"code","message"}}`;
  422 is the one documented exception (`{"detail":[...]}`, input/ctx stripped).

## Running

From `services/control_plane/`:

```bash
# Run only the contract-gate suite
.venv/bin/python -m pytest tests/api_contract -q

# Full unit suite with coverage
.venv/bin/python -m pytest -m unit --cov=control_plane --cov-report=term-missing -q
```

## Coverage floor

The floor is **85%** (Units C + D jointly). Unit C adds API-contract breadth
(route-inventory, role-matrix, error-envelope, gap-fill). Unit D adds
domain/service depth (lifecycle, workflows, scheduler). After Unit C the
measured total is **67%** (up from the 66% baseline); the remaining gap is
Unit D's job.

To assert the floor once Unit D is complete:

```bash
.venv/bin/python -m pytest -m unit --cov=control_plane --cov-fail-under=85 -q
```

Do **not** add `--cov-fail-under=85` as a gate until Unit D is merged — it
would fail the CI before that work lands.

## Adding a route

Add it to its router as usual, then add a CONTRACTS entry in `contracts.py`
(and, if the route mutates state and self-authorizes instead of using a
`require_*` gate, a SELF_SCOPED_MUTATIONS entry). The gates fail until you do.
This is the regression guarantee a coverage percentage cannot give.

### CONTRACTS entry format

```python
# Single-line when the full line fits within 100 chars:
("POST", "/v1/my-resource/{rid}", "/v1/my-resource/r_x", "auth"),

# Two-line when path_template + sample_url would exceed 100 chars:
("GET", "/v1/my-resource/{rid}/very-long-sub-path",
 "/v1/my-resource/r_x/very-long-sub-path", "auth"),
```

`kind` values:
- `"auth"` — unauthenticated request must return 401 + `{"error":{"code":"unauthorized",...}}`
- `"public"` — unauthenticated request must return any status other than 401
- `"redirect"` — unauthenticated request must return 307 or 308 with a Location header
