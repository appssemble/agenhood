from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession


async def db_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield an AsyncSession from the app's session factory.

    Shared FastAPI dependency used by all connectors routers. Kept as a single
    function object so a future ``dependency_overrides[db_session]`` overrides
    every router at once.
    """
    async with request.app.state.session_factory() as session:
        yield session
