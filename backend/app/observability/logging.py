"""Structured JSON logging + request-scoped correlation IDs.

We use structlog wrapped around Python's stdlib logging. This means:
- Our own `log = structlog.get_logger()` calls produce structured output.
- Third-party libraries (uvicorn, SQLAlchemy, OpenAI SDK) keep working
  and their logs also get formatted as JSON via the stdlib formatter.

Every HTTP request is assigned a `request_id` that gets bound to the
structlog context for the duration of that request. Any log line emitted
while handling the request automatically includes that ID.
"""
import logging
import sys
import uuid
from contextvars import ContextVar
from typing import Any

import structlog
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

# ----------------------------------------------------------------------------
# Context variable — request ID lives here for the duration of a request.
# ContextVar is asyncio-safe: each concurrent request has its own value.
# ----------------------------------------------------------------------------
request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)


def _add_request_id(
    logger: logging.Logger,
    method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """Structlog processor: inject request_id from contextvar into every log."""
    rid = request_id_ctx.get()
    if rid is not None:
        event_dict["request_id"] = rid
    return event_dict


def configure_logging(log_level: str = "INFO", json_output: bool = True) -> None:
    """Configure stdlib logging + structlog.

    Call this once at application startup, before any log calls happen.
    """
    # Choose renderer: JSON for production/containers, pretty for local dev
    renderer: Any = (
        structlog.processors.JSONRenderer()
        if json_output
        else structlog.dev.ConsoleRenderer(colors=True)
    )

    # Shared processors — applied to both structlog and stdlib-origin logs
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _add_request_id,
    ]

    # ------------------------------------------------------------------
    # Configure stdlib logging — uvicorn, SQLAlchemy, etc. go through this
    # ------------------------------------------------------------------
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers = [handler]  # replace any existing handlers
    root_logger.setLevel(log_level.upper())

    # Quiet down overly chatty libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    # ------------------------------------------------------------------
    # Configure structlog — our own `log = structlog.get_logger()` calls
    # ------------------------------------------------------------------
    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping()[log_level.upper()],
        ),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Assign a unique ID to every incoming request.

    - Generates a UUID4 if the client didn't send X-Request-ID
    - Stores it in a contextvar so all logs during the request include it
    - Echoes it in the X-Request-ID response header for client-side tracing
    """

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        incoming = request.headers.get("X-Request-ID")
        rid = incoming or str(uuid.uuid4())

        token = request_id_ctx.set(rid)
        try:
            response: Response = await call_next(request)
        finally:
            request_id_ctx.reset(token)

        response.headers["X-Request-ID"] = rid
        return response


def get_logger(name: str | None = None) -> Any:
    """Convenience wrapper — every module imports from here.

    Usage:
        from app.observability.logging import get_logger
        log = get_logger(__name__)
        log.info("something_happened", user_id=42, action="login")
    """
    return structlog.get_logger(name)