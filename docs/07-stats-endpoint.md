# 07 - GET /{short_code}/stats Analytics Endpoint & SQL Group By

This document explains the query design, SQL aggregation mechanics, and implementation of the `GET /{short_code}/stats` analytics endpoint in our URL shortener backend.

---

## 1. What Problem Does This Solve?

A URL shortener is only half as useful if you cannot measure link engagement. The `GET /{short_code}/stats` endpoint provides a comprehensive analytics breakdown for any short code, answering:
1. **Total Reach**: How many total clicks did this link receive?
2. **Audience Diversity**: How many distinct/unique IP addresses accessed the link?
3. **Recent Velocity / Trend**: How many clicks occurred per day over the rolling 7-day window?

---

## 2. API Contract

### Request
* **HTTP Method**: `GET`
* **Path**: `/{short_code}/stats`

### Response (`200 OK`)
```json
{
  "short_code": "stat01",
  "original_url": "https://docs.python.org/3/",
  "total_clicks": 5,
  "unique_ips": 3,
  "clicks_per_day": [
    {
      "date": "2026-08-07",
      "clicks": 2
    },
    {
      "date": "2026-08-08",
      "clicks": 2
    }
  ]
}
```

### Not Found Error (`404 Not Found`)
If the short code does not exist in PostgreSQL:
```json
{
  "detail": "Short code not found"
}
```

---

## 3. The SQL & SQLAlchemy Queries

The stats endpoint utilizes two distinct aggregation queries alongside the parent link lookup.

### 1. Daily Breakdown Query (`GROUP BY`)

#### The Raw SQL
```sql
SELECT 
    DATE(clicked_at) AS click_date, 
    COUNT(id) AS clicks
FROM click_events
WHERE link_id = :link_id
  AND clicked_at >= :seven_days_ago
GROUP BY DATE(clicked_at)
ORDER BY click_date ASC;
```

#### In SQLAlchemy 2.0
```python
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
```

#### What is it Grouping By?
* `ClickEvent.clicked_at` is stored as a microsecond-precision timestamp with timezone (e.g. `2026-08-08 18:25:31.492015+00`).
* If you executed `GROUP BY clicked_at`, almost every single row would create its own isolated bucket because sub-second timestamps are unique.
* `cast(ClickEvent.clicked_at, Date)` (or SQL `DATE(clicked_at)`) strips the hours, minutes, seconds, and microseconds, leaving only the calendar date (`2026-08-08`).
* `GROUP BY` instructs PostgreSQL to bucket all click events that occurred on the same calendar day into a single group, while `func.count(ClickEvent.id)` computes the total number of events inside each daily bucket.

---

### 2. Unique IP Address Aggregation

#### The Raw SQL
```sql
SELECT COUNT(DISTINCT ip_address) 
FROM click_events 
WHERE link_id = :link_id 
  AND ip_address IS NOT NULL;
```

#### In SQLAlchemy 2.0
```python
unique_ips_stmt = (
    select(func.count(func.distinct(ClickEvent.ip_address)))
    .where(
        ClickEvent.link_id == link.id,
        ClickEvent.ip_address.is_not(None)
    )
)
unique_ips = (await db.execute(unique_ips_stmt)).scalar() or 0
```

* `func.distinct(ClickEvent.ip_address)` filters out duplicate IP entries (e.g. if the same user clicked the link 10 times).
* `ClickEvent.ip_address.is_not(None)` ensures anonymous or missing IP records do not count toward unique visitors.

---

## 4. Request Lifecycle Walkthrough

```
[Client GET /{short_code}/stats]
                 │
                 ▼
     [Lookup Link in PostgreSQL]
                 │
          Link exists?
          /          \
       [No]          [Yes]
        │              │
        ▼              ▼
┌──────────────┐  ┌─────────────────────────────────────────────────┐
│ Return 404   │  │ 1. Read fast counter: link.click_count           │
│ Not Found    │  │ 2. Query COUNT(DISTINCT ip_address)              │
└──────────────┘  │ 3. Query GROUP BY DATE(clicked_at) (last 7 days)│
                  └────────────────────────┬────────────────────────┘
                                           │
                                           ▼
                            ┌───────────────────────────────┐
                            │ Return 200 OK                 │
                            │ Structured JSON Stats Payload │
                            └───────────────────────────────┘
```

---

## 5. Summary of Created & Updated Files

* **[app/schemas.py](file:///c:/Users/nihar/url-shortener/app/schemas.py)**: Added `DailyClicks` and `LinkStatsResponse` schemas.
* **[app/routers/links.py](file:///c:/Users/nihar/url-shortener/app/routers/links.py)**: Added `GET /{short_code}/stats` route with `GROUP BY` and `COUNT(DISTINCT)` queries.
* **[tests/test_stats.py](file:///c:/Users/nihar/url-shortener/tests/test_stats.py)**: Added integration tests covering date grouping, 7-day cutoff window, unique IP deduplication, empty stats, and 404 responses.
