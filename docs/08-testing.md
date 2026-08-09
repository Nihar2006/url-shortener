# 08 - Automated Testing & Database Isolation Strategy

This document explains our approach to writing automated unit and integration tests for our FastAPI + async SQLAlchemy 2.0 + PostgreSQL URL shortener backend.

---

## 1. The Core Challenge: Test Isolation & Data Pollution

When writing integration tests against a database, tests must be **isolated** and **deterministic**:
* Test B should never fail simply because Test A inserted a record with the same `short_code`.
* Running tests should never pollute development or staging databases with fake test URLs.
* Every test must start from a known, clean state.

---

## 2. Comparing Isolation Strategies: Rollback vs. Fixture Truncation

| Isolation Strategy | How It Works | Strengths | Why We Chose Truncation for This App |
|---|---|---|---|
| **Transaction / Session Rollback** | The test wraps each test run in an outer transaction and calls `ROLLBACK` at teardown. | Very fast; no DDL or cleanup commands needed. | **Breaks Real Commits**: Our application code explicitly uses `async with db.begin_nested():` and `await db.commit()`. Application-level commits interfere with outer test transactions unless heavily mocked. |
| **Fixture-Driven Table Truncation (`TRUNCATE ... CASCADE`)** | An automated `autouse` fixture truncates all tables and resets primary key sequences before each test. | **100% Real-World Fidelity**: Actual commits, foreign key cascades (`ondelete="CASCADE"`), unique constraint violations, and collision retries execute against PostgreSQL exactly as they do in production. | **Selected Approach**: Guarantees zero data leakage between test runs while testing true end-to-end database behavior. |

---

## 3. Test Fixture Architecture ([tests/conftest.py](../tests/conftest.py))

Our shared test configuration manages four key fixtures:

```python
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import text
from app.main import app
from app.database import async_session

@pytest.fixture(scope="session")
def anyio_backend():
    """Forces anyio to use asyncio for all async test cases."""
    return "asyncio"

@pytest.fixture(autouse=True)
async def clean_database():
    """
    Autouse fixture: Truncates tables and resets primary keys before each test.
    Guarantees clean state and zero data leakage.
    """
    async with async_session() as session:
        await session.execute(text("TRUNCATE TABLE links RESTART IDENTITY CASCADE;"))
        await session.commit()

@pytest.fixture
async def client():
    """Provides an isolated AsyncClient for making HTTP requests to FastAPI."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

@pytest.fixture
async def db_session():
    """Yields a direct database session for test-side assertions."""
    async with async_session() as session:
        yield session
```

---

## 4. Test Suite Coverage

### 1. Shorten Endpoint ([tests/test_shorten.py](../tests/test_shorten.py))
* `test_shorten_url_returns_valid_short_code`: Verifies a valid URL generates a 6-character Base62 string and persists in PostgreSQL with `click_count = 0`.
* `test_shorten_url_invalid_format_returns_422`: Verifies Pydantic rejects non-URL payloads with `422 Unprocessable Entity`.
* `test_shorten_collision_retry_success`: Mocks short code generation to simulate a collision, verifying the savepoint rollback catches the conflict and retries with a fresh code.
* `test_shorten_max_retries_exhausted_returns_500`: Verifies that if 5 consecutive collisions occur, the API returns a graceful HTTP 500 error.

### 2. Redirect Endpoint ([tests/test_redirect.py](../tests/test_redirect.py))
* `test_redirect_success_increments_click_count_and_logs_event`: Verifies `302 Found` status, `Location` header, sequential counter increments (`0 -> 1 -> 2`), and insertion of `ClickEvent` records with client IP and User-Agent.
* `test_redirect_returns_404_for_unknown_code`: Verifies `404 Not Found` for non-existent short codes.

### 3. Analytics & Stats Endpoint ([tests/test_stats.py](../tests/test_stats.py))
* `test_stats_returns_correct_totals_and_group_by_breakdown`: Populates click events across multiple days and IP addresses. Verifies `total_clicks`, `COUNT(DISTINCT ip_address)`, `GROUP BY DATE(clicked_at)` daily distribution, and exclusion of events older than 7 days.
* `test_stats_empty_link_with_zero_clicks`: Verifies zeroed metrics for new links.
* `test_stats_returns_404_for_unknown_code`: Verifies `404 Not Found` for stats on unknown links.

### 4. End-to-End User Journey ([tests/test_e2e.py](../tests/test_e2e.py))
* `test_full_link_lifecycle_e2e`: Simulates a complete real-world flow:
  1. `POST /shorten` -> receives short code.
  2. Multiple `GET /{short_code}` visits with custom IP addresses and User-Agents.
  3. `GET /{short_code}/stats` -> verifies all metrics match aggregate and time-series behavior.

---

## 5. How to Run the Test Suite

Execute pytest in your terminal:
```bash
python -m pytest -v
```
