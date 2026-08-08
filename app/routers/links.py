from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select, func, cast, Date
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.database import get_db
from app.models import Link, ClickEvent
from app.schemas import URLShortenRequest, URLShortenResponse, LinkStatsResponse, DailyClicks
from app.utils import generate_short_code

router = APIRouter(tags=["links"])

MAX_COLLISION_RETRIES = 5

@router.post(
    "/shorten",
    response_model=URLShortenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Shorten a URL",
    description="Accepts an original URL, generates a unique short code, and saves the link in the database."
)
async def shorten_url(
    payload: URLShortenRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Creates a new shortened link record.
    
    Handles collisions using an optimistic retry strategy backed by
    PostgreSQL's unique constraint on `short_code` with nested savepoints.
    """
    for attempt in range(MAX_COLLISION_RETRIES):
        code = generate_short_code(length=6)
        link = Link(
            short_code=code,
            original_url=str(payload.url)
        )
        
        try:
            # Use a savepoint so that an integrity error can be safely rolled back
            # without invalidating the entire database transaction/session.
            async with db.begin_nested():
                db.add(link)
                await db.flush()
            
            await db.commit()
            await db.refresh(link)
            return URLShortenResponse(short_code=link.short_code)
        except IntegrityError:
            # A collision occurred (short_code already exists).
            # The nested savepoint rolled back cleanly; proceed to next attempt.
            continue

    # If all retry attempts collided, return a 500 error
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Could not generate a unique short code after multiple attempts. Please try again."
    )


@router.get(
    "/{short_code}/stats",
    response_model=LinkStatsResponse,
    status_code=status.HTTP_200_OK,
    summary="Get link analytics and statistics",
    description="Returns aggregate click metrics, distinct IP counts, and a daily breakdown for the last 7 days using GROUP BY."
)
async def get_link_stats(
    short_code: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieves analytics metrics for a given short code.
    
    1. Fetches link metadata and fast counter cache (`click_count`).
    2. Runs an aggregation for count of unique IP addresses.
    3. Runs a GROUP BY query on ClickEvent to calculate daily clicks over the last 7 days.
    """
    # 1. Fetch link record
    link_stmt = select(Link).where(Link.short_code == short_code)
    link_res = await db.execute(link_stmt)
    link = link_res.scalar_one_or_none()

    if link is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Short code not found"
        )

    # 2. Count distinct non-null IP addresses
    unique_ips_stmt = (
        select(func.count(func.distinct(ClickEvent.ip_address)))
        .where(
            ClickEvent.link_id == link.id,
            ClickEvent.ip_address.is_not(None)
        )
    )
    unique_ips = (await db.execute(unique_ips_stmt)).scalar() or 0

    # 3. Aggregate clicks per day for the last 7 days using GROUP BY
    seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
    
    daily_stmt = (
        select(
            cast(ClickEvent.clicked_at, Date).label("click_date"),
            func.count(ClickEvent.id).label("clicks")
        )
        .where(
            ClickEvent.link_id == link.id,
            ClickEvent.clicked_at >= seven_days_ago
        )
        .group_by(cast(ClickEvent.clicked_at, Date))
        .order_by(cast(ClickEvent.clicked_at, Date).asc())
    )
    daily_res = await db.execute(daily_stmt)
    daily_rows = daily_res.all()

    clicks_per_day = [
        DailyClicks(date=row.click_date, clicks=row.clicks)
        for row in daily_rows
    ]

    return LinkStatsResponse(
        short_code=link.short_code,
        original_url=link.original_url,
        total_clicks=link.click_count,
        unique_ips=unique_ips,
        clicks_per_day=clicks_per_day
    )


@router.get(
    "/{short_code}",
    response_class=RedirectResponse,
    status_code=status.HTTP_302_FOUND,
    summary="Redirect to original URL",
    description="Looks up a short code in the database, records a ClickEvent, increments click_count, and redirects the client."
)
async def redirect_to_url(
    short_code: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Resolves a short code to its original URL.
    
    1. Queries the database using the indexed `short_code` column.
    2. Raises 404 if the short code does not exist.
    3. Records a detailed ClickEvent (IP address and User-Agent).
    4. Atomically increments `click_count` and commits the transaction.
    5. Returns a 302 Temporary Redirect to the original URL.
    """
    stmt = select(Link).where(Link.short_code == short_code)
    result = await db.execute(stmt)
    link = result.scalar_one_or_none()

    if link is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Short code not found"
        )

    # Extract client IP (handling X-Forwarded-For if behind a reverse proxy)
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        client_ip = forwarded_for.split(",")[0].strip()
    elif request.client:
        client_ip = request.client.host
    else:
        client_ip = None

    user_agent = request.headers.get("user-agent")

    # Record the detailed click event
    click_event = ClickEvent(
        link_id=link.id,
        ip_address=client_ip,
        user_agent=user_agent
    )
    db.add(click_event)

    # Increment counter cache
    link.click_count += 1
    await db.commit()

    return RedirectResponse(
        url=link.original_url,
        status_code=status.HTTP_302_FOUND
    )
