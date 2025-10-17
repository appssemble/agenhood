"""One-shot: recycle a running container onto the current agent image by
destroy (running -> archived, keeps volume) + rehydrate (run_from_volume ->
new image). Uses the real lifecycle code so locks/transitions stay consistent
with the background reconciler. Pass the container id as argv[1]."""
import asyncio
import sys

from control_plane.config import Settings
from control_plane.db import make_engine, make_session_factory
from control_plane import lifecycle
import docker


async def main(cid: str) -> None:
    settings = Settings.from_env()
    engine = make_engine(settings)
    session_factory = make_session_factory(engine)
    docker_client = docker.from_env()

    class _NoopShim:
        async def post(self, *a, **k):  # best-effort /shutdown
            return None

        async def cancel_all(self, *a, **k):
            return None

    shim = _NoopShim()

    async with session_factory() as db:
        ok = await lifecycle.destroy(db, docker_client, shim, cid,
                                     actor_type="staff", actor_id="recycle-script")
        await db.commit()
        print(f"destroy -> archived: {ok}")

    async with session_factory() as db:
        await lifecycle.rehydrate(db, docker_client, cid, settings=settings)
        await db.commit()
        print("rehydrate -> running (run_from_volume on current image)")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
