import pytest

@pytest.mark.anyio
async def test_health_check_not_intercepted_by_short_code_route(client):
    """
    GET /health should match the static /health route and return HTTP 200 with {"status": "ok"},
    rather than being intercepted by the /{short_code} wildcard redirect route.
    """
    response = await client.get("/health", follow_redirects=False)
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
