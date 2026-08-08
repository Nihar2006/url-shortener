import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select, text
from app.main import app
from app.database import async_session
from app.models import Link, ClickEvent

@pytest.fixture
def anyio_backend():
    return "asyncio"

@pytest.fixture(autouse=True)
async def clean_db():
    async with async_session() as session:
        await session.execute(text("TRUNCATE TABLE links RESTART IDENTITY CASCADE;"))
        await session.commit()

@pytest.mark.anyio
async def test_redirect_success_and_click_event_logging():
    # 1. Pre-populate a test link
    test_code = "fast01"
    target_url = "https://fastapi.tiangolo.com/tutorial/bigger-applications/"
    
    async with async_session() as session:
        link = Link(short_code=test_code, original_url=target_url, click_count=0)
        session.add(link)
        await session.commit()

    transport = ASGITransport(app=app)
    headers = {
        "user-agent": "CustomTestBrowser/2.0",
        "x-forwarded-for": "203.0.113.195"
    }
    
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 2. First redirect request
        response1 = await client.get(f"/{test_code}", headers=headers, follow_redirects=False)
        assert response1.status_code == 302
        assert response1.headers["location"] == target_url
        
        # Verify click_count and click_event record in the database
        async with async_session() as session:
            # Check Link
            stmt = select(Link).where(Link.short_code == test_code)
            res = await session.execute(stmt)
            updated_link = res.scalar_one()
            assert updated_link.click_count == 1

            # Check ClickEvents
            event_stmt = select(ClickEvent).where(ClickEvent.link_id == updated_link.id)
            event_res = await session.execute(event_stmt)
            events = event_res.scalars().all()
            assert len(events) == 1
            assert events[0].ip_address == "203.0.113.195"
            assert events[0].user_agent == "CustomTestBrowser/2.0"
            assert events[0].clicked_at is not None
            
        # 3. Second redirect request
        response2 = await client.get(f"/{test_code}", follow_redirects=False)
        assert response2.status_code == 302
        
        # Verify click_count is now 2 and 2 events exist
        async with async_session() as session:
            stmt = select(Link).where(Link.short_code == test_code)
            res = await session.execute(stmt)
            updated_link = res.scalar_one()
            assert updated_link.click_count == 2

            event_stmt = select(ClickEvent).where(ClickEvent.link_id == updated_link.id)
            event_res = await session.execute(event_stmt)
            events = event_res.scalars().all()
            assert len(events) == 2


@pytest.mark.anyio
async def test_redirect_not_found():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/nonexistent99", follow_redirects=False)
        assert response.status_code == 404
        assert response.json()["detail"] == "Short code not found"

