from fastapi import FastAPI
from app.routers.links import router as links_router

app = FastAPI(
    title="URL Shortener API",
    description="A high-performance asynchronous URL shortener backend built with FastAPI, SQLAlchemy 2.0, and PostgreSQL.",
    version="1.0.0"
)

# 1. Define static top-level routes (e.g. /health) BEFORE wildcard parameter routes
@app.get("/health", tags=["health"])
async def health_check():
    return {"status": "ok"}

# 2. Include dynamic endpoint routers containing parameter path patterns (e.g. /{short_code})
app.include_router(links_router)
