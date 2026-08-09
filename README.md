# ⚡ FastLink — Asynchronous URL Shortener & Analytics Backend

A high-performance, concurrency-safe URL shortener and real-time analytics backend built with **FastAPI**, **PostgreSQL**, and **SQLAlchemy 2.0 (Async)**.

---

## 🚀 Overview & Key Highlights

* **High-Throughput Asynchronous Architecture**: Built on Python's async ecosystem (`asyncio`, `asyncpg`, `FastAPI`, `SQLAlchemy 2.0`) to handle high concurrent I/O with minimal latency.
* **Concurrency-Safe Collision Handling**: Employs an optimistic retry strategy backed by PostgreSQL unique indexes and SQL **Savepoints** (`begin_nested()`) to eliminate Time-of-Check to Time-of-Use (TOCTOU) race conditions.
* **Dual-Tier Analytics Engine**: Combines an $\mathcal{O}(1)$ **Counter Cache** for instantaneous dashboard metrics with an immutable **Event Log** (`ClickEvent`) for granular time-series and IP/device forensics.
* **Analytics Preservation via 302 Redirects**: Uses `302 Found` semantics to prevent client-side browser caching, ensuring 100% of click traffic is recorded.
* **Containerized & Production-Ready**: Fully orchestrated with Docker Compose, featuring automated database healthchecks and startup migration workflows.
* **100% Test Coverage**: Full suite of unit, integration, and end-to-end lifecycle tests with deterministic database fixture isolation.

---

## 🛠️ Tech Stack

| Layer | Technology | Purpose |
|---|---|---|
| **Web Framework** | [FastAPI](https://fastapi.tiangolo.com/) | High-speed ASGI REST API routing, auto-generated OpenAPI documentation |
| **Data Validation** | [Pydantic v2](https://docs.pydantic.dev/) | Strict URL validation, request body schemas, and response serialization |
| **Database** | [PostgreSQL 16](https://www.postgresql.org/) | ACID-compliant relational data storage, unique indexing, and event logging |
| **ORM & Driver** | [SQLAlchemy 2.0](https://www.sqlalchemy.org/) + [asyncpg](https://github.com/MagicStack/asyncpg) | Fully asynchronous database queries, unit-of-work sessions, and connection pooling |
| **Schema Migrations**| [Alembic](https://alembic.sqlalchemy.org/) | Version-controlled, declarative database schema migrations |
| **Testing** | [pytest](https://pytest.org/) + [httpx](https://www.python-httpx.org/) | Async integration test suite with fixture-based database truncation |
| **Containerization** | [Docker](https://www.docker.com/) & [Docker Compose](https://docs.docker.com/compose/) | Isolated multi-container deployment with active healthcheck orchestration |

---

## 📐 System Architecture

```
                                      ┌─────────────────────────────────────────┐
                                      │             FastAPI Backend             │
                                      └────────────────────┬────────────────────┘
                                                           │
                    ┌──────────────────────────────────────┼──────────────────────────────────────┐
                    │                                      │                                      │
                    ▼                                      ▼                                      ▼
           [POST /shorten]                         [GET /{short_code}]                 [GET /{short_code}/stats]
                    │                                      │                                      │
        ┌───────────┴───────────┐                          │                                      │
        │ Generate Base62 Code  │                          │                                      │
        └───────────┬───────────┘                          │                                      │
                    │                                      │                                      │
        ┌───────────┴───────────┐              ┌───────────┴───────────┐              ┌───────────┴───────────┐
        │ Open SQL Savepoint    │              │ 1. Increment Counter  │              │ 1. Read `click_count` │
        │ (db.begin_nested())   │              │ 2. Insert ClickEvent  │              │ 2. COUNT(DISTINCT IP) │
        └───────────┬───────────┘              │ 3. Return 302 Found   │              │ 3. GROUP BY DATE(...) │
                    │                          └───────────┬───────────┘              └───────────┬───────────┘
          Collision Detected?                              │                                      │
          /                 \                              │                                      │
    [Yes: Retry]        [No: Commit]                       │                                      │
        │                    │                             │                                      │
        └────────────────────┴─────────────────────────────┴──────────────────────────────────────┘
                                                           │
                                                           ▼
                                      ┌─────────────────────────────────────────┐
                                      │           PostgreSQL Database           │
                                      │  - links (id, short_code, click_count)  │
                                      │  - click_events (link_id, ip, ua, time) │
                                      └─────────────────────────────────────────┘
```

---

## 📡 API Endpoints

| Method | Path | Status | Description |
|---|---|---|---|
| `POST` | `/shorten` | `201 Created` | Accepts `{ "url": "https://..." }`, generates a unique short code, and saves the link. |
| `GET` | `/{short_code}` | `302 Found` | Increments `click_count`, logs a `ClickEvent` (IP + User-Agent), and redirects to `original_url`. Returns `404` if not found. |
| `GET` | `/{short_code}/stats` | `200 OK` | Returns total clicks, distinct visitor IP count, and a 7-day daily breakdown using `GROUP BY`. |
| `GET` | `/health` | `200 OK` | Liveness healthcheck endpoint (`{ "status": "ok" }`). |

### Example Payloads

#### 1. Shorten a URL (`POST /shorten`)
```bash
curl -X POST http://localhost:8000/shorten \
  -H "Content-Type: application/json" \
  -d '{"url": "https://fastapi.tiangolo.com/tutorial/"}'
```
**Response (`201 Created`)**:
```json
{
  "short_code": "k9xL2p"
}
```

#### 2. Resolve & Redirect (`GET /{short_code}`)
```bash
curl -I http://localhost:8000/k9xL2p
```
**Response (`302 Found`)**:
```http
HTTP/1.1 302 Found
Location: https://fastapi.tiangolo.com/tutorial/
```

#### 3. View Analytics (`GET /{short_code}/stats`)
```bash
curl http://localhost:8000/k9xL2p/stats
```
**Response (`200 OK`)**:
```json
{
  "short_code": "k9xL2p",
  "original_url": "https://fastapi.tiangolo.com/tutorial/",
  "total_clicks": 142,
  "unique_ips": 89,
  "clicks_per_day": [
    { "date": "2026-08-08", "clicks": 45 },
    { "date": "2026-08-09", "clicks": 97 }
  ]
}
```

---

## 🧠 Key Design Decisions

### 1. Dual-Tier Analytics: `click_count` Counter Cache + `ClickEvent` Log
* **The Problem**: A single counter only tells you *how many* clicks occurred (no time-series, no visitor details). Conversely, calculating total clicks solely via `SELECT COUNT(*) FROM click_events` causes expensive table scans on popular links.
* **Our Solution**:
  * **`click_count` on `links`**: Provides $\mathcal{O}(1)$ instant reads for dashboard overviews and stats endpoints without database aggregation overhead.
  * **`ClickEvent` table**: Stores append-only timestamped records (`clicked_at`, `ip_address`, `user_agent`) to enable daily velocity charts, geographic analytics, and bot filtering.

### 2. HTTP 302 Found vs. 301 Moved Permanently
* **The Problem**: Browsers and CDNs aggressively cache `301 Moved Permanently` redirects indefinitely. If a user clicks a shortened link a second time, their browser navigates directly to the destination from local cache *without contacting our backend*.
* **Our Solution**: We use **`302 Found`** (Temporary Redirect). This forces the browser to query our server on *every single click*, guaranteeing 100% accurate click metrics and real-time redirection updates.

### 3. Concurrency-Safe Short Code Generation & Collision Recovery
* **Base62 Entropy**: We use `[a-zA-Z0-9]` with 6 characters ($62^6 \approx 56.8\text{ billion}$ permutations), generated via Python's cryptographically secure `secrets.choice`.
* **The Concurrency Problem**: "Check-then-insert" (`SELECT` then `INSERT`) suffers from Time-of-Check to Time-of-Use (TOCTOU) race conditions under high concurrent traffic.
* **Our Solution**:
  1. PostgreSQL enforces uniqueness at the storage engine level (`UNIQUE INDEX` on `short_code`).
  2. The application opens a SQL **Savepoint** (`async with db.begin_nested():`) prior to insert.
  3. If a collision occurs, PostgreSQL raises an `IntegrityError`. The savepoint rolls back *only that specific attempt* without invalidating the active database session.
  4. The handler catches the error, generates a fresh code, and retries immediately (up to 5 attempts).

---

## ⚙️ Setup & Installation

### Option 1: Run with Docker Compose (Recommended)

1. Clone the repository:
   ```bash
   git clone https://github.com/Nihar2006/url-shortener.git
   cd url-shortener
   ```

2. Build images and start services:
   ```bash
   docker compose up --build
   ```
   * PostgreSQL initializes with active healthchecks (`pg_isready`).
   * FastAPI waits for the database to become healthy, automatically runs `alembic upgrade head`, and starts Uvicorn on `http://localhost:8000`.

---

### Option 2: Local Python Setup

1. **Create and activate a virtual environment**:
   ```bash
   python -m venv venv
   # On Windows:
   venv\Scripts\activate
   # On macOS/Linux:
   source venv/bin/activate
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure environment variables**:
   Create a `.env` file in the project root (see [.env.example](.env.example)):
   ```env
   DATABASE_URL=postgresql+asyncpg://postgres:devpass123@localhost:5432/urlshortener
   ```

4. **Run database migrations**:
   ```bash
   alembic upgrade head
   ```

5. **Start the development server**:
   ```bash
   uvicorn app.main:app --reload --port 8000
   ```
   Access interactive API documentation at: `http://localhost:8000/docs`.

---

## 🧪 Running Automated Tests

The test suite runs against an isolated PostgreSQL instance using `pytest` and `httpx.AsyncClient`. It includes an automated `autouse` fixture that executes `TRUNCATE TABLE links RESTART IDENTITY CASCADE;` before every test, guaranteeing zero data leakage and 100% test independence.

Run the test suite:
```bash
python -m pytest -v
```

---

## 📚 Architectural Documentation

In-depth technical guides for each layer of the application:
* [04 - Shorten Endpoint & Collision Strategy](docs/04-shorten-endpoint.md)
* [05 - Redirect Endpoint & 302 HTTP Semantics](docs/05-redirect-endpoint.md)
* [06 - Click Logging & Counter Cache Architecture](docs/06-click-logging.md)
* [07 - Stats Endpoint & SQL Group By](docs/07-stats-endpoint.md)
* [08 - Automated Testing & Database Isolation](docs/08-testing.md)
* [09 - Containerization & Docker Healthchecks](docs/09-docker.md)
