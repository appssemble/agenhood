"""ShimClient export/import methods against a MockTransport shim."""
from __future__ import annotations

import httpx
import pytest

from control_plane.shim_client import (
    ShimClient,
    ShimExportUnmatched,
    ShimTransferTooLarge,
)

pytestmark = pytest.mark.unit


def _client_with(handler):
    c = ShimClient(base_url="http://shim", token="t")
    c._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://shim"
    )
    return c


@pytest.mark.asyncio
async def test_export_manifest_params_and_result():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["params"] = httpx.QueryParams(request.url.query)
        return httpx.Response(200, json={"files": [{"path": "a", "size": 1}],
                                         "total_bytes": 1})

    async with _client_with(handler) as c:
        out = await c.export_manifest(["a", "b/**"], max_bytes=99)
    assert out["total_bytes"] == 1
    assert seen["params"].get_list("paths") == ["a", "b/**"]
    assert seen["params"]["dry_run"] == "true"
    assert seen["params"]["max_bytes"] == "99"


@pytest.mark.asyncio
async def test_export_manifest_unmatched_raises():
    def handler(request):
        return httpx.Response(422, json={"error": {"code": "unmatched_exports",
                                                   "unmatched": ["dist/**"]}})

    async with _client_with(handler) as c:
        with pytest.raises(ShimExportUnmatched) as ei:
            await c.export_manifest(["dist/**"])
    assert ei.value.unmatched == ["dist/**"]
    assert "dist/**" in str(ei.value)


@pytest.mark.asyncio
async def test_export_manifest_too_large_raises():
    def handler(request):
        return httpx.Response(413, json={"error": {"code": "transfer_too_large",
                                                   "total_bytes": 100}})

    async with _client_with(handler) as c:
        with pytest.raises(ShimTransferTooLarge):
            await c.export_manifest(["big.bin"], max_bytes=10)


@pytest.mark.asyncio
async def test_export_stream_yields_bytes():
    def handler(request):
        assert httpx.QueryParams(request.url.query).get("dry_run") is None
        return httpx.Response(200, content=b"tarbytes")

    async with _client_with(handler) as c:
        chunks = [chunk async for chunk in c.export_stream(["a"])]
    assert b"".join(chunks) == b"tarbytes"


@pytest.mark.asyncio
async def test_export_stream_unmatched_raises():
    def handler(request):
        return httpx.Response(422, json={"error": {"code": "unmatched_exports",
                                                   "unmatched": ["x"]}})

    async with _client_with(handler) as c:
        with pytest.raises(ShimExportUnmatched):
            async for _ in c.export_stream(["x"]):
                pass


@pytest.mark.asyncio
async def test_import_archive_posts_stream_and_returns_counts():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.read()
        seen["params"] = httpx.QueryParams(request.url.query)
        return httpx.Response(200, json={"files_written": 2, "bytes_written": 7})

    async def gen():
        yield b"tar"
        yield b"bytes"

    async with _client_with(handler) as c:
        out = await c.import_archive(gen(), max_bytes=50)
    assert out == {"files_written": 2, "bytes_written": 7}
    assert seen["body"] == b"tarbytes"
    assert seen["params"]["max_bytes"] == "50"


@pytest.mark.asyncio
async def test_import_archive_too_large_raises():
    def handler(request):
        request.read()
        return httpx.Response(413, json={"error": {"code": "transfer_too_large"}})

    async def gen():
        yield b"x"

    async with _client_with(handler) as c:
        with pytest.raises(ShimTransferTooLarge):
            await c.import_archive(gen())
