import pytest
from datetime import datetime, timedelta, timezone
from app.models import Link, ClickEvent

@pytest.mark.anyio
async def test_stats_returns_correct_totals_and_group_by_breakdown(client, db_session):
    """
    GET /{short_code}/stats should return:
    1. total_clicks
    2. count of unique IP addresses
    3. per-day breakdown for the last 7 days using GROUP BY
    """
    test_code = "stat01"
    target_url = "https://docs.python.org/3/"
    
    now = datetime.now(timezone.utc)
    today = now.date()
    yesterday = (now - timedelta(days=1)).date()
    eight_days_ago = now - timedelta(days=8)

    link = Link(short_code=test_code, original_url=target_url, click_count=5)
    db_session.add(link)
    await db_session.flush()

    events = [
        # Today: 2 clicks from '10.0.0.1' and '10.0.0.2'
        ClickEvent(link_id=link.id, clicked_at=now, ip_address="10.0.0.1", user_agent="Chrome"),
        ClickEvent(link_id=link.id, clicked_at=now - timedelta(minutes=5), ip_address="10.0.0.2", user_agent="Firefox"),
        
        # Yesterday: 2 clicks from '10.0.0.1' (repeated IP) and None IP
        ClickEvent(link_id=link.id, clicked_at=now - timedelta(days=1, minutes=10), ip_address="10.0.0.1", user_agent="Safari"),
        ClickEvent(link_id=link.id, clicked_at=now - timedelta(days=1, minutes=20), ip_address=None, user_agent="Edge"),
        
        # 8 days ago (should be excluded from 7-day daily breakdown)
        ClickEvent(link_id=link.id, clicked_at=eight_days_ago, ip_address="10.0.0.9", user_agent="OldBrowser"),
    ]
    db_session.add_all(events)
    await db_session.commit()

    response = await client.get(f"/{test_code}/stats")
    assert response.status_code == 200
    data = response.json()
    
    assert data["short_code"] == test_code
    assert data["original_url"] == target_url
    assert data["total_clicks"] == 5
    
    # 3 unique non-null IPs: '10.0.0.1', '10.0.0.2', '10.0.0.9'
    assert data["unique_ips"] == 3
    
    # 7-day daily breakdown: yesterday and today only
    daily_stats = data["clicks_per_day"]
    assert len(daily_stats) == 2
    
    daily_map = {entry["date"]: entry["clicks"] for entry in daily_stats}
    assert daily_map[str(today)] == 2
    assert daily_map[str(yesterday)] == 2
    assert str(eight_days_ago.date()) not in daily_map


@pytest.mark.anyio
async def test_stats_empty_link_with_zero_clicks(client, db_session):
    """
    GET /{short_code}/stats for a newly created link with 0 clicks returns zeroed metrics.
    """
    test_code = "empty0"
    link = Link(short_code=test_code, original_url="https://empty.org", click_count=0)
    db_session.add(link)
    await db_session.commit()

    response = await client.get(f"/{test_code}/stats")
    assert response.status_code == 200
    data = response.json()
    assert data["total_clicks"] == 0
    assert data["unique_ips"] == 0
    assert data["clicks_per_day"] == []


@pytest.mark.anyio
async def test_stats_returns_404_for_unknown_code(client):
    """
    GET /{short_code}/stats returns 404 when the short_code does not exist.
    """
    response = await client.get("/nonexistent_code/stats")
    assert response.status_code == 404
    assert response.json()["detail"] == "Short code not found"
