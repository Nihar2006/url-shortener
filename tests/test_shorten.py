import pytest
from unittest.mock import patch
from sqlalchemy import select
from app.models import Link

@pytest.mark.anyio
async def test_shorten_url_returns_valid_short_code(client, db_session):
    """
    POST /shorten should accept a valid original URL, generate a 6-character
    unique short code, save it in the database with click_count=0, and return 201 Created.
    """
    payload = {"url": "https://fastapi.tiangolo.com/tutorial/"}
    response = await client.post("/shorten", json=payload)
    
    assert response.status_code == 201
    data = response.json()
    assert "short_code" in data
    assert len(data["short_code"]) == 6
    
    # Assert database record was inserted
    stmt = select(Link).where(Link.short_code == data["short_code"])
    result = await db_session.execute(stmt)
    link_record = result.scalar_one_or_none()
    
    assert link_record is not None
    assert str(link_record.original_url).rstrip("/") == "https://fastapi.tiangolo.com/tutorial"
    assert link_record.click_count == 0


@pytest.mark.anyio
async def test_shorten_url_invalid_format_returns_422(client):
    """
    POST /shorten should reject invalid URL schemas with HTTP 422 Unprocessable Entity.
    """
    payload = {"url": "invalid-url-schema"}
    response = await client.post("/shorten", json=payload)
    assert response.status_code == 422


@pytest.mark.anyio
async def test_shorten_collision_retry_success(client, db_session):
    """
    If a generated code collides with an existing code in the database, the savepoint
    rollback should catch the collision and retry with a fresh code without failing the request.
    """
    fixed_collision_code = "FIXED1"
    fixed_fresh_code = "FIXED2"
    
    # Pre-populate database with the colliding code
    existing_link = Link(short_code=fixed_collision_code, original_url="https://initial-site.org")
    db_session.add(existing_link)
    await db_session.commit()
    
    # Mock code generator to return colliding code first, then fresh code
    with patch("app.routers.links.generate_short_code", side_effect=[fixed_collision_code, fixed_fresh_code]):
        payload = {"url": "https://python.org"}
        response = await client.post("/shorten", json=payload)
        
        assert response.status_code == 201
        assert response.json()["short_code"] == fixed_fresh_code
        
        # Verify the fresh code was persisted
        stmt = select(Link).where(Link.short_code == fixed_fresh_code)
        res = await db_session.execute(stmt)
        record = res.scalar_one_or_none()
        assert record is not None
        assert str(record.original_url).rstrip("/") == "https://python.org"


@pytest.mark.anyio
async def test_shorten_max_retries_exhausted_returns_500(client, db_session):
    """
    If all 5 collision retry attempts fail, the endpoint returns a 500 Internal Server Error.
    """
    exhausted_code = "EXHAUS"
    
    existing_link = Link(short_code=exhausted_code, original_url="https://existing.org")
    db_session.add(existing_link)
    await db_session.commit()
    
    with patch("app.routers.links.generate_short_code", return_value=exhausted_code):
        payload = {"url": "https://exhaust-test.com"}
        response = await client.post("/shorten", json=payload)
        assert response.status_code == 500
        assert "Could not generate a unique short code" in response.json()["detail"]
