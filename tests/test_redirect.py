import pytest
from sqlalchemy import select
from app.models import Link, ClickEvent

@pytest.mark.anyio
async def test_redirect_success_increments_click_count_and_logs_event(client, db_session):
    """
    GET /{short_code} should:
    1. Look up the short_code in PostgreSQL.
    2. Increment link.click_count.
    3. Insert a ClickEvent with client IP and User-Agent.
    4. Redirect the client to original_url with HTTP 302 Found.
    """
    test_code = "fast01"
    target_url = "https://fastapi.tiangolo.com/tutorial/bigger-applications/"
    
    link = Link(short_code=test_code, original_url=target_url, click_count=0)
    db_session.add(link)
    await db_session.commit()

    headers = {
        "user-agent": "CustomTestBrowser/2.0",
        "x-forwarded-for": "203.0.113.195"
    }
    
    # 1. First redirect request
    response1 = await client.get(f"/{test_code}", headers=headers, follow_redirects=False)
    assert response1.status_code == 302
    assert response1.headers["location"] == target_url
    
    # Verify click_count and ClickEvent in database
    db_session.expire_all()
    stmt = select(Link).where(Link.short_code == test_code)
    res = await db_session.execute(stmt)
    updated_link = res.scalar_one()
    assert updated_link.click_count == 1

    event_stmt = select(ClickEvent).where(ClickEvent.link_id == updated_link.id)
    event_res = await db_session.execute(event_stmt)
    events = event_res.scalars().all()
    assert len(events) == 1
    assert events[0].ip_address == "203.0.113.195"
    assert events[0].user_agent == "CustomTestBrowser/2.0"
    assert events[0].clicked_at is not None
    
    # 2. Second redirect request
    response2 = await client.get(f"/{test_code}", follow_redirects=False)
    assert response2.status_code == 302
    
    # Verify click_count is now 2 and 2 events exist
    db_session.expire_all()
    stmt = select(Link).where(Link.short_code == test_code)
    res = await db_session.execute(stmt)
    updated_link = res.scalar_one()
    assert updated_link.click_count == 2

    event_stmt = select(ClickEvent).where(ClickEvent.link_id == updated_link.id)
    event_res = await db_session.execute(event_stmt)
    events = event_res.scalars().all()
    assert len(events) == 2


@pytest.mark.anyio
async def test_redirect_returns_404_for_unknown_code(client):
    """
    GET /{short_code} should return HTTP 404 Not Found when the code does not exist.
    """
    response = await client.get("/unknown_code_123", follow_redirects=False)
    assert response.status_code == 404
    assert response.json()["detail"] == "Short code not found"
