from __future__ import annotations

import pytest


@pytest.mark.unit
def test_seed_main_runs_apply_seed_and_disposes(monkeypatch) -> None:
    import control_plane.seed as seed

    calls: dict[str, int] = {"apply": 0, "dispose": 0}

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    class _FakeFactory:
        def __call__(self):
            return _FakeSession()

    class _FakeEngine:
        async def dispose(self):
            calls["dispose"] += 1

    async def _fake_apply_seed(session, settings):
        calls["apply"] += 1

    monkeypatch.setattr(seed, "make_engine", lambda settings: _FakeEngine())
    monkeypatch.setattr(seed, "make_session_factory", lambda engine: _FakeFactory())
    monkeypatch.setattr(seed, "apply_seed", _fake_apply_seed)

    seed.main()

    assert calls["apply"] == 1
    assert calls["dispose"] == 1


@pytest.mark.unit
def test_seed_main_disposes_on_apply_seed_error(monkeypatch) -> None:
    import control_plane.seed as seed

    calls: dict[str, int] = {"dispose": 0}

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    class _FakeFactory:
        def __call__(self):
            return _FakeSession()

    class _FakeEngine:
        async def dispose(self):
            calls["dispose"] += 1

    async def _failing_apply_seed(session, settings):
        raise RuntimeError("db error")

    monkeypatch.setattr(seed, "make_engine", lambda s: _FakeEngine())
    monkeypatch.setattr(seed, "make_session_factory", lambda e: _FakeFactory())
    monkeypatch.setattr(seed, "apply_seed", _failing_apply_seed)

    with pytest.raises(RuntimeError, match="db error"):
        seed.main()

    assert calls["dispose"] == 1


@pytest.mark.unit
def test_claude_code_builtin_template_seeded() -> None:
    from control_plane.seed import build_builtin_template_rows

    rows = build_builtin_template_rows()
    assert any(r["driver"] == "claude-code" for r in rows)
