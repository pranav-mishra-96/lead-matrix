"""Async database session management.

Exposes:
  - `engine` — the shared async engine (connection pool + dialect)
  - `AsyncSessionLocal` — session factory; each call returns a new session
  - `get_db_session` — FastAPI dependency that provides a request-scoped
    session with automatic commit on success, rollback on exception

The engine is created at module load and disposed on app shutdown.
Connection pool parameters are tuned for a typical API workload; see
inline comments for rationale.
"""
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings
from app.observability.logging import get_logger

log = get_logger(__name__)

settings = get_settings()

# ----------------------------------------------------------------------------
# Engine — the connection pool lives here
# ----------------------------------------------------------------------------
# pool_size: connections kept open in the pool. Higher = less handshake
#   overhead, more idle DB resources. 10 is comfortable for a PoC.
# max_overflow: extra connections beyond pool_size under load. These are
#   discarded when returned. Acts as a burst buffer.
# pool_pre_ping: issue a cheap SELECT 1 before handing out a connection
#   to detect stale/dead connections after network blips or Postgres
#   restarts. Small latency cost for big reliability win.
# pool_recycle: force reconnection after N seconds. Avoids cloud load
#   balancers silently killing idle connections.
# echo: log every SQL statement. Useful for dev, noisy for production.
# ----------------------------------------------------------------------------
engine = create_async_engine(
    settings.database_url,
    pool_size=10,
    max_overflow=5,
    pool_pre_ping=True,
    pool_recycle=1800,  # 30 minutes
    echo=False,
    future=True,
)

# Session factory. `expire_on_commit=False` keeps ORM attributes usable
# after commit — otherwise accessing `obj.id` after session.commit() would
# trigger a fresh SELECT. Cleaner for request-scoped sessions.
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency that yields a request-scoped session.

    Transaction semantics:
      - Begin implicit transaction on first query
      - Commit if the route returns normally
      - Rollback if the route raises
      - Always close the session (return connection to pool)

    Usage:
        from fastapi import Depends
        from app.db.session import get_db_session

        @router.get("/conversations")
        async def list_convos(session: AsyncSession = Depends(get_db_session)):
            return await repositories.list_conversations(session)
    """
    session = AsyncSessionLocal()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        log.exception("db_session_rollback")
        raise
    finally:
        await session.close()


async def dispose_engine() -> None:
    """Close all pool connections. Call during app shutdown."""
    await engine.dispose()
    log.info("db_engine_disposed")