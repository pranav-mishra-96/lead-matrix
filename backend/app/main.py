"""FastAPI application entry point."""

from fastapi.middleware.cors import CORSMiddleware

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from app.api import chat, debug, health
from app.config import get_settings
from app.observability.logging import (
    RequestIDMiddleware,
    configure_logging,
    get_logger,
)

settings = get_settings()

configure_logging(
    log_level=settings.log_level,
    json_output=settings.is_production,
)

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Run startup and shutdown hooks."""
    from app.db.session import dispose_engine

    log.info(
        "app_starting",
        environment=settings.environment,
        model=settings.openai_model,
        log_level=settings.log_level,
    )
    yield
    await dispose_engine()
    log.info("app_shutdown")


app = FastAPI(
    title="Strategic Lead Matrix API",
    description="AI-driven commercial energy lead qualification",
    version="0.1.0",
    debug=not settings.is_production,
    lifespan=lifespan,
)

# CORS must come first so OPTIONS preflight responses are handled cleanly
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)

# Install request ID middleware
app.add_middleware(RequestIDMiddleware)


# Routers
app.include_router(health.router)
app.include_router(debug.router)
app.include_router(chat.router)


@app.get("/")
async def root() -> dict[str, str]:
    """Root endpoint — confirms the API is running."""
    log.info("root_endpoint_hit")
    return {
        "message": "Strategic Lead Matrix API is running",
        "environment": settings.environment,
        "model": settings.openai_model,
    }