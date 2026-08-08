import pytest
from unittest.mock import patch
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select
from app.main import app
from app.database import async_session
from app.models import Link

@pytest.fixture
def anyio_backend():
    return "asyncio"

@pytest.fixture(autouse=True)
async def clean_db():
    async with async_session() as session:
        from sqlalchemy import text
        await session.execute(text("TRUNCATE TABLE links RESTART IDENTITY CASCADE;"))
        await session.commit()

@pytest.mark.anyio
async def test_shorten_url_success():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {"url": "https://fastapi.tiangolo.com/tutorial/"}
        response = await client.post("/shorten", json=payload)
        
        assert response.status_code == 201
        data = response.json()
        assert "short_code" in data
        assert len(data["short_code"]) == 6
        
        # Verify it was inserted into the database
        async with async_session() as session:
            stmt = select(Link).where(Link.short_code == data["short_code"])
            result = await session.execute(stmt)
            link_record = result.scalar_one_or_none()
            assert link_record is not None
            assert str(link_record.original_url).rstrip("/") == "https://fastapi.tiangolo.com/tutorial"
            assert link_record.click_count == 0


@pytest.mark.anyio
async def test_shorten_url_invalid_format():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Invalid URL schema
        payload = {"url": "not-a-valid-url"}
        response = await client.post("/shorten", json=payload)
        assert response.status_code == 422


@pytest.mark.anyio
async def test_shorten_collision_retry_success():
    fixed_collision_code = "FIXED1"
    fixed_fresh_code = "FIXED2"
    
    # Pre-populate database with the colliding code
    async with async_session() as session:
        existing_link = Link(short_code=fixed_collision_code, original_url="https://initial-site.org")
        session.add(existing_link)
        try:
            await session.commit()
        except Exception:
            await session.rollback()
    
    # Mock code generator to return colliding code first, then fresh code
    with patch("app.routers.links.generate_short_code", side_effect=[fixed_collision_code, fixed_fresh_code]):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            payload = {"url": "https://python.org"}
            response = await client.post("/shorten", json=payload)
            
            assert response.status_code == 201
            assert response.json()["short_code"] == fixed_fresh_code
            
            # Verify the fresh code was saved
            async with async_session() as session:
                stmt = select(Link).where(Link.short_code == fixed_fresh_code)
                res = await session.execute(stmt)
                record = res.scalar_one_or_none()
                assert record is not None
                assert str(record.original_url).rstrip("/") == "https://python.org"


@pytest.mark.anyio
async def test_shorten_max_retries_exhausted():
    exhausted_code = "EXHAUS"
    
    # Pre-populate database with this code
    async with async_session() as session:
        existing_link = Link(short_code=exhausted_code, original_url="https://existing.org")
        session.add(existing_link)
        try:
            await session.commit()
        except Exception:
            await session.rollback()
        
    # Mock code generator to always return exhausted_code to force all 5 retries to collide
    with patch("app.routers.links.generate_short_code", return_value=exhausted_code):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            payload = {"url": "https://exhaust-test.com"}
            response = await client.post("/shorten", json=payload)
            assert response.status_code == 500
            assert "Could not generate a unique short code" in response.json()["detail"]
