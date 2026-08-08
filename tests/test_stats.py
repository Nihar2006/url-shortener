import pytest
from datetime import datetime, timedelta, timezone, date
from httpx import AsyncClient, ASGITransport
from sqlalchemy import text
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
async def test_stats_success_with_group_by_breakdown():
    test_code = "stat01"
    target_url = "https://docs.python.org/3/"
    
    now = datetime.now(timezone.utc)
    today = now.date()
    yesterday = (now - timedelta(days=1)).date()
    two_days_ago = (now - timedelta(days=2)).date()
    eight_days_ago = now - timedelta(days=8) # Outside 7-day window

    async with async_session() as session:
        link = Link(short_code=test_code, original_url=target_url, click_count=5)
        session.add(link)
        await session.flush()

        events = [
            # Today: 2 clicks from IP '10.0.0.1' and '10.0.0.2'
            ClickEvent(link_id=link.id, clicked_at=now, ip_address="10.0.0.1", user_agent="Chrome"),
            ClickEvent(link_id=link.id, clicked_at=now - timedelta(minutes=5), ip_address="10.0.0.2", user_agent="Firefox"),
            
            # Yesterday: 2 clicks from '10.0.0.1' (repeated IP) and None IP
            ClickEvent(link_id=link.id, clicked_at=now - timedelta(days=1, minutes=10), ip_address="10.0.0.1", user_agent="Safari"),
            ClickEvent(link_id=link.id, clicked_at=now - timedelta(days=1, minutes=20), ip_address=None, user_agent="Edge"),
            
            # 8 days ago (should be excluded from 7-day daily breakdown)
            ClickEvent(link_id=link.id, clicked_at=eight_days_ago, ip_address="10.0.0.9", user_agent="OldBrowser"),
        ]
        session.add_all(events)
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/{test_code}/stats")
        assert response.status_code == 200
        data = response.json()
        
        assert data["short_code"] == test_code
        assert data["original_url"] == target_url
        assert data["total_clicks"] == 5
        
        # Unique IPs: '10.0.0.1', '10.0.0.2', '10.0.0.9' (distinct non-null)
        assert data["unique_ips"] == 3
        
        # Daily breakdown (within 7 days): should have entries for yesterday and today
        daily_stats = data["clicks_per_day"]
        assert len(daily_stats) == 2
        
        # Map by date string
        daily_map = {entry["date"]: entry["clicks"] for entry in daily_stats}
        assert daily_map[str(today)] == 2
        assert daily_map[str(yesterday)] == 2
        assert str(eight_days_ago.date()) not in daily_map


@pytest.mark.anyio
async def test_stats_empty_clicks():
    test_code = "empty0"
    async with async_session() as session:
        link = Link(short_code=test_code, original_url="https://empty.org", click_count=0)
        session.add(link)
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/{test_code}/stats")
        assert response.status_code == 200
        data = response.json()
        assert data["total_clicks"] == 0
        assert data["unique_ips"] == 0
        assert data["clicks_per_day"] == []


@pytest.mark.anyio
async def test_stats_not_found():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/nonexistent_code/stats")
        assert response.status_code == 404
        assert response.json()["detail"] == "Short code not found"
