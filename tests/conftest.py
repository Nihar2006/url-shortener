import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import text
from app.main import app
from app.database import async_session

@pytest.fixture(scope="session")
def anyio_backend():
    """Forces anyio to use asyncio as the event loop for all async test cases."""
    return "asyncio"

@pytest.fixture(autouse=True)
async def clean_database():
    """
    Autouse fixture that runs before each test function.
    Truncates all tables and resets primary key sequences, ensuring full isolation
    and zero data leakage between test runs.
    """
    async with async_session() as session:
        await session.execute(text("TRUNCATE TABLE links RESTART IDENTITY CASCADE;"))
        await session.commit()

@pytest.fixture
async def client():
    """Provides an isolated AsyncClient for invoking FastAPI routes in tests."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

@pytest.fixture
async def db_session():
    """Yields a direct async SQLAlchemy session for test-side database assertions and setup."""
    async with async_session() as session:
        yield session
