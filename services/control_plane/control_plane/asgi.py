"""Module-level ASGI app for uvicorn (`uvicorn control_plane.asgi:app`).

Built from environment-derived settings at import time. Construction does not
open a DB connection; DB/Docker work happens in the FastAPI lifespan at startup.
"""
from __future__ import annotations

from control_plane.app import create_app
from control_plane.config import Settings

app = create_app(Settings.from_env())
