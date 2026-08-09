import pytest

@pytest.mark.anyio
async def test_full_link_lifecycle_e2e(client):
    """
    End-to-end test verifying the complete link lifecycle:
    1. Shorten a URL -> get short_code.
    2. Simulate 3 clicks from 2 distinct IP addresses -> verify 302 redirects.
    3. Query /stats -> verify total_clicks == 3, unique_ips == 2, and today's clicks == 3.
    """
    # 1. Shorten URL
    original_target = "https://www.python.org/downloads/"
    create_resp = await client.post("/shorten", json={"url": original_target})
    assert create_resp.status_code == 201
    short_code = create_resp.json()["short_code"]
    assert len(short_code) == 6

    # 2. Simulate Click 1 (IP: 198.51.100.1, Chrome)
    click1 = await client.get(
        f"/{short_code}",
        headers={"x-forwarded-for": "198.51.100.1", "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
        follow_redirects=False
    )
    assert click1.status_code == 302
    assert click1.headers["location"] == original_target

    # Simulate Click 2 (IP: 198.51.100.2, Firefox)
    click2 = await client.get(
        f"/{short_code}",
        headers={"x-forwarded-for": "198.51.100.2", "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15)"},
        follow_redirects=False
    )
    assert click2.status_code == 302

    # Simulate Click 3 (Repeat IP: 198.51.100.1, Safari)
    click3 = await client.get(
        f"/{short_code}",
        headers={"x-forwarded-for": "198.51.100.1", "user-agent": "Mobile Safari/604.1"},
        follow_redirects=False
    )
    assert click3.status_code == 302

    # 3. Fetch Stats
    stats_resp = await client.get(f"/{short_code}/stats")
    assert stats_resp.status_code == 200
    stats = stats_resp.json()

    assert stats["short_code"] == short_code
    assert stats["original_url"] == original_target
    assert stats["total_clicks"] == 3
    assert stats["unique_ips"] == 2
    assert len(stats["clicks_per_day"]) == 1
    assert stats["clicks_per_day"][0]["clicks"] == 3
