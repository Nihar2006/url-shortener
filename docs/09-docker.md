# 09 - Containerization with Docker & Docker Compose

This document explains our Docker setup, including image optimization, startup orchestration with healthchecks, and environment-driven configuration.

---

## 1. The Startup Race Condition: Why `depends_on` Needs a Healthcheck

When spinning up multi-container applications (e.g. an API backend and a database), beginners often use a simple `depends_on`:

```yaml
# ❌ INSUFFICIENT: Only checks container creation, not database readiness
depends_on:
  - db
```

### What Goes Wrong Without a Healthcheck?
1. **Container Started $\neq$ Database Ready**: Docker considers a container "started" the instant its Linux process starts.
2. **PostgreSQL Initialization Delay**: When PostgreSQL starts, it takes several seconds to run initialization scripts (`initdb`), generate SSL certificates, create default users/databases, and open its TCP listening port (`5432`).
3. **The Boot Crash**: The FastAPI container starts in milliseconds. If FastAPI attempts to connect or run Alembic migrations while PostgreSQL is still initializing, you encounter:
   ```text
   asyncpg.exceptions.CannotConnectNowError: the database system is starting up
   ConnectionRefusedError: [Errno 111] Connection refused
   ```
   This causes the application to crash immediately on boot (`CrashLoopBackOff`).

### How `service_healthy` Solves This
We define an active database healthcheck using `pg_isready`:

```yaml
healthcheck:
  test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-postgres} -d ${POSTGRES_DB:-urlshortener}"]
  interval: 5s
  timeout: 5s
  retries: 5
  start_period: 5s
```

And configure the `app` service to wait for the database to become healthy:

```yaml
depends_on:
  db:
    condition: service_healthy
```

Docker Compose holds the `app` container in a waiting state until `pg_isready` returns exit code `0`, guaranteeing PostgreSQL is fully ready to accept connections before FastAPI or Alembic executes.

---

## 2. The Dockerfile Architecture

Our [Dockerfile](../Dockerfile) is designed for speed, security, and minimal image size:

```dockerfile
# 1. Lightweight official Python runtime
FROM python:3.13-slim

# 2. Prevent .pyc bytecode generation and ensure unbuffered real-time stdout logs
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 3. Layer Caching: Copy dependencies first so code changes don't re-trigger pip install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. Copy application source code
COPY . .

EXPOSE 8000

# 5. Automatically apply migrations on boot, then launch Uvicorn
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
```

---

## 3. Docker Compose Orchestration ([docker-compose.yml](../docker-compose.yml))

```yaml
services:
  db:
    image: postgres:16-alpine
    container_name: url_shortener_db
    restart: unless-stopped
    environment:
      POSTGRES_USER: ${POSTGRES_USER:-postgres}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-devpass123}
      POSTGRES_DB: ${POSTGRES_DB:-urlshortener}
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-postgres} -d ${POSTGRES_DB:-urlshortener}"]
      interval: 5s
      timeout: 5s
      retries: 5
      start_period: 5s

  app:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: url_shortener_app
    restart: unless-stopped
    ports:
      - "8000:8000"
    environment:
      DATABASE_URL: postgresql+asyncpg://${POSTGRES_USER:-postgres}:${POSTGRES_PASSWORD:-devpass123}@db:5432/${POSTGRES_DB:-urlshortener}
    depends_on:
      db:
        condition: service_healthy

volumes:
  postgres_data:
```

### Key Highlights
* **Internal Docker Networking**: Within the Docker network, the database is reachable via its service hostname `db` (`@db:5432`).
* **Volume Persistence (`postgres_data`)**: Database records are stored in a dedicated named volume and survive container restarts.
* **Environment-Driven Configuration**: No database passwords or URLs are hardcoded in the codebase.

---

## 4. Useful Docker Commands

```bash
# Build images and start all services in the background
docker compose up -d --build

# View real-time application and migration logs
docker compose logs -f app

# Stop containers while preserving database volume data
docker compose down

# Stop containers and wipe the database volume (clean reset)
docker compose down -v
```
