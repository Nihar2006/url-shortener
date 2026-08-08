from fastapi import FastAPI
from app.routers.links import router as links_router

app = FastAPI(
    title="URL Shortener API",
    description="A high-performance asynchronous URL shortener backend built with FastAPI, SQLAlchemy 2.0, and PostgreSQL.",
    version="1.0.0"
)

# Include endpoint routers
app.include_router(links_router)

@app.get("/health", tags=["health"])
async def health_check():
    return {"status": "ok"}
