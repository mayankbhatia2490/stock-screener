"""
Tests for response compression (GZipMiddleware).

Large JSON payloads (scan results, group rankings) must ship gzip-compressed
when the client advertises support; tiny payloads stay uncompressed.
"""
import pytest
import pytest_asyncio
import httpx

from app.main import app

_LARGE_PAYLOAD = {"rows": [{"symbol": f"SYM{i}", "value": i * 1.5} for i in range(500)]}


@app.get("/_test/large-response", include_in_schema=False)
async def _large_response():
    return _LARGE_PAYLOAD


@pytest_asyncio.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
class TestGzipCompression:
    async def test_large_response_is_gzipped(self, client):
        response = await client.get(
            "/_test/large-response", headers={"Accept-Encoding": "gzip"}
        )
        assert response.status_code == 200
        assert response.headers.get("content-encoding") == "gzip"
        # httpx transparently decompresses; body must round-trip intact
        assert response.json() == _LARGE_PAYLOAD

    async def test_small_response_not_gzipped(self, client):
        response = await client.get("/livez", headers={"Accept-Encoding": "gzip"})
        assert response.status_code == 200
        assert response.headers.get("content-encoding") is None

    async def test_no_accept_encoding_returns_identity(self, client):
        response = await client.get(
            "/_test/large-response", headers={"Accept-Encoding": "identity"}
        )
        assert response.status_code == 200
        assert response.headers.get("content-encoding") is None
        assert response.json() == _LARGE_PAYLOAD
