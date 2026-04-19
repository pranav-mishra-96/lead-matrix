"""FastAPI application entry point."""
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from app.api import health
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
    log.info(
        "app_starting",
        environment=settings.environment,
        model=settings.openai_model,
        log_level=settings.log_level,
    )
    yield
    log.info("app_shutdown")


app = FastAPI(
    title="Strategic Lead Matrix API",
    description="AI-driven commercial energy lead qualification",
    version="0.1.0",
    debug=not settings.is_production,
    lifespan=lifespan,
)

app.add_middleware(RequestIDMiddleware)

# Routers
app.include_router(health.router)


@app.get("/")
async def root() -> dict[str, str]:
    """Root endpoint — confirms the API is running."""
    log.info("root_endpoint_hit")
    return {
        "message": "Strategic Lead Matrix API is running",
        "environment": settings.environment,
        "model": settings.openai_model,
    }