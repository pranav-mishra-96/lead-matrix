"""Health check endpoints.

Two separate endpoints following the Kubernetes liveness/readiness pattern:

  GET /health/live  — am I alive? (cheap, no dependencies)
  GET /health/ready — can I serve traffic? (checks DB + Redis)

Also keeps GET /health as an alias for /health/live for backward compatibility
with our existing Dockerfile healthcheck.
"""
import asyncio
import time
from typing import Literal

import asyncpg
import redis.asyncio as redis_async
from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.config import Settings, get_settings
from app.observability.logging import get_logger

log = get_logger(__name__)
router = APIRouter(prefix="/health", tags=["health"])


# ----------------------------------------------------------------------------
# Response schemas — typed so FastAPI auto-generates OpenAPI docs
# ----------------------------------------------------------------------------
class ComponentHealth(BaseModel):
    """Health of a single dependency."""

    status: Literal["ok", "error"]
    latency_ms: float
    error: str | None = None


class ReadinessResponse(BaseModel):
    """Overall readiness plus per-component detail."""

    status: Literal["ok", "error"]
    checks: dict[str, ComponentHealth]


# ----------------------------------------------------------------------------
# Individual dependency checks — each returns a ComponentHealth
# ----------------------------------------------------------------------------
async def _check_postgres(settings: Settings) -> ComponentHealth:
    """Open a short-lived asyncpg connection and run SELECT 1."""
    start = time.perf_counter()
    try:
        conn = await asyncpg.connect(
            host=settings.postgres_host,
            port=settings.postgres_port,
            user=settings.postgres_user,
            password=settings.postgres_password.get_secret_value(),
            database=settings.postgres_db,
            timeout=2.0,
        )
        try:
            await conn.fetchval("SELECT 1")
        finally:
            await conn.close()
        elapsed_ms = (time.perf_counter() - start) * 1000
        return ComponentHealth(status="ok", latency_ms=round(elapsed_ms, 2))
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - start) * 1000
        log.warning("postgres_health_check_failed", error=str(exc))
        return ComponentHealth(
            status="error",
            latency_ms=round(elapsed_ms, 2),
            error=str(exc),
        )


async def _check_redis(settings: Settings) -> ComponentHealth:
    """Open a short-lived Redis connection and run PING."""
    start = time.perf_counter()
    client: redis_async.Redis | None = None
    try:
        client = redis_async.Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            socket_connect_timeout=2.0,
            socket_timeout=2.0,
        )
        await client.ping()
        elapsed_ms = (time.perf_counter() - start) * 1000
        return ComponentHealth(status="ok", latency_ms=round(elapsed_ms, 2))
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - start) * 1000
        log.warning("redis_health_check_failed", error=str(exc))
        return ComponentHealth(
            status="error",
            latency_ms=round(elapsed_ms, 2),
            error=str(exc),
        )
    finally:
        if client is not None:
            await client.aclose()


# ----------------------------------------------------------------------------
# Endpoints
# ----------------------------------------------------------------------------
@router.get("/live", summary="Liveness probe")
async def liveness() -> dict[str, str]:
    """Liveness probe — is the process alive?

    Deliberately does NOT check dependencies. If this fails, the orchestrator
    (Docker / Kubernetes) should restart the container. Restart-on-deps-failure
    would cause cascading restarts when a dependency has a transient blip.
    """
    return {"status": "ok"}


@router.get("/ready", summary="Readiness probe", response_model=ReadinessResponse)
async def readiness() -> JSONResponse:
    """Readiness probe — can I serve traffic right now?

    Checks Postgres and Redis IN PARALLEL so the total latency is
    max(postgres, redis) rather than postgres + redis. Returns HTTP 503
    with detail if any dependency is down, so load balancers can route
    traffic away until things recover.
    """
    settings = get_settings()

    postgres_health, redis_health = await asyncio.gather(
        _check_postgres(settings),
        _check_redis(settings),
    )

    checks = {"postgres": postgres_health, "redis": redis_health}
    overall_ok = all(c.status == "ok" for c in checks.values())

    response = ReadinessResponse(
        status="ok" if overall_ok else "error",
        checks=checks,
    )

    http_status = (
        status.HTTP_200_OK if overall_ok else status.HTTP_503_SERVICE_UNAVAILABLE
    )

    if not overall_ok:
        log.warning(
            "readiness_check_failed",
            postgres_status=postgres_health.status,
            redis_status=redis_health.status,
        )

    return JSONResponse(
        status_code=http_status,
        content=response.model_dump(),
    )


# Backward-compatible alias — Dockerfile HEALTHCHECK hits /health
@router.get("", summary="Liveness alias")
async def health_alias() -> dict[str, str]:
    """Alias for /health/live — kept for compatibility with existing tooling."""
    return {"status": "ok"}