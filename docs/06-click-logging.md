# 06 - Click Event Logging & Counter Cache Architecture

This document explains the schema design, trade-offs, and implementation behind tracking both aggregate click counts and detailed click events in our URL shortener.

---

## 1. Why Keep Both `click_count` AND a Separate `ClickEvent` Table?

When designing analytics for high-throughput systems, engineers frequently face a choice between **Counter Caches** (scalar integer) and **Event Streams** (granular logs). In our backend, we use a **hybrid pattern**:

```
┌─────────────────────────────────────────────────────────────┐
│                       Incoming Click                        │
└──────────────────────────────┬──────────────────────────────┘
                               │
               ┌───────────────┴───────────────┐
               ▼                               ▼
   ┌───────────────────────┐       ┌───────────────────────┐
   │ Update `click_count`  │       │  Insert `ClickEvent`  │
   │  (Instant Counter)    │       │   (Detailed Event)    │
   └───────────┬───────────┘       └───────────┬───────────┘
               │                               │
               ▼                               ▼
   ⚡ Fast Dashboard Queries        📊 Rich Time-Series &
     O(1) Single-Row Reads            Forensic Analytics
```

### 1. The Fast Path: `click_count` (Counter Cache)
* **What it is**: An integer column directly on the `links` table.
* **Why it's essential**:
  * Querying link totals (e.g. `GET /stats/{short_code}` or rendering a dashboard listing 50 links) takes a simple $\mathcal{O}(1)$ lookup on the `links` row.
  * Without this column, calculating total clicks requires:
    ```sql
    SELECT COUNT(*) FROM click_events WHERE link_id = 42;
    ```
  * On links with millions of clicks, `COUNT(*)` forces PostgreSQL to scan and aggregate millions of index entries, causing CPU spikes, cache thrashing, and high latency.

### 2. The Detailed Log: `ClickEvent` (Event Stream)
* **What it is**: An append-only table storing an immutable record for every visit.
* **Why it's essential**:
  * `click_count` only answers *"how many"*. It cannot answer *"when"*, *"where"*, or *"who"*.
  * `ClickEvent` captures:
    * **`clicked_at`**: Exact timestamps for time-series charts (e.g., clicks per hour, viral spike detection).
    * **`ip_address`**: Geographic origin estimation and unique visitor deduplication.
    * **`user_agent`**: Device and platform breakdown (Mobile vs. Desktop, Safari vs. Chrome, bot detection).

---

## 2. Database Schema & Migration

### The `click_events` Table Definition
In [app/models.py](../app/models.py):

```python
class ClickEvent(Base):
    __tablename__ = "click_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    link_id: Mapped[int] = mapped_column(ForeignKey("links.id", ondelete="CASCADE"), index=True, nullable=False)
    clicked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    link: Mapped["Link"] = relationship("Link", back_populates="click_events")
```

### Key Schema Decisions
1. **`ondelete="CASCADE"`**: If a parent `Link` is deleted, PostgreSQL automatically removes all associated `click_events` to maintain referential integrity without orphan records.
2. **`index=True` on `link_id`**: Enables fast index lookups and `JOIN`s when filtering events for a specific link.
3. **`String(45)` for `ip_address`**: Supports both standard IPv4 addresses (up to 15 chars, e.g. `192.168.1.1`) and full IPv6 addresses (up to 45 chars, e.g. `2001:0db8:85a3:0000:0000:8a2e:0370:7334`).
4. **`server_default=func.now()`**: Ensures the database server assigns the exact timestamp at insertion time, guaranteeing monotonic time consistency.

---

## 3. The Alembic Migration File

The migration file generated under [alembic/versions/6dbe6efd9d5d_create_click_events_table.py](../alembic/versions/6dbe6efd9d5d_create_click_events_table.py):

```python
"""create click_events table

Revision ID: 6dbe6efd9d5d
Revises: 05de702ccd3e
Create Date: 2026-08-08 18:18:16.954222
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '6dbe6efd9d5d'
down_revision: Union[str, Sequence[str], None] = '05de702ccd3e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.create_table(
        'click_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('link_id', sa.Integer(), nullable=False),
        sa.Column('clicked_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('ip_address', sa.String(length=45), nullable=True),
        sa.Column('user_agent', sa.String(length=512), nullable=True),
        sa.ForeignKeyConstraint(['link_id'], ['links.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_click_events_link_id'), 'click_events', ['link_id'], unique=False)

def downgrade() -> None:
    op.drop_index(op.f('ix_click_events_link_id'), table_name='click_events')
    op.drop_table('click_events')
```

---

## 4. Endpoint Implementation: Atomic Dual-Write

In [app/routers/links.py](../app/routers/links.py), both updates happen within a single ACID transaction:

```python
# 1. Extract client IP (checking X-Forwarded-For header in case of reverse proxy)
forwarded_for = request.headers.get("x-forwarded-for")
client_ip = forwarded_for.split(",")[0].strip() if forwarded_for else (request.client.host if request.client else None)
user_agent = request.headers.get("user-agent")

# 2. Add detailed log row
click_event = ClickEvent(
    link_id=link.id,
    ip_address=client_ip,
    user_agent=user_agent
)
db.add(click_event)

# 3. Increment instant counter cache
link.click_count += 1

# 4. Atomic commit: either both succeed or neither persists
await db.commit()
```

---

## 5. Summary of Created & Updated Files

* **[app/models.py](../app/models.py)**: Added `ClickEvent` model with foreign key relationship to `Link`.
* **[alembic/versions/6dbe6efd9d5d_create_click_events_table.py](../alembic/versions/6dbe6efd9d5d_create_click_events_table.py)**: Generated and applied migration creating the `click_events` table and index.
* **[app/routers/links.py](../app/routers/links.py)**: Updated `GET /{short_code}` to log IP, User-Agent, and increment `click_count`.
* **[tests/test_redirect.py](../tests/test_redirect.py)**: Added integration tests asserting `ClickEvent` records are inserted with correct IP, User-Agent, and timestamp.
