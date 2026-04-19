"""Alembic migration environment.

Loads the database URL from our app's Settings class (single source of
truth — no duplication of config). Uses async SQLAlchemy engine for
compatibility with the rest of the codebase.
"""
import asyncio
import sys
from logging.config import fileConfig
from pathlib import Path

# Ensure /app is on the Python path so we can import `app.config`, `app.db`
# regardless of where alembic is invoked from. This file lives at
# /app/alembic/env.py, so the parent of the parent is /app.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Import our Settings and Base so Alembic can read config and see all models
from app.config import get_settings
from app.db.base import Base
# Import models package so all model classes register with Base.metadata
from app.db import models  # noqa: F401

# Alembic Config object
config = context.config

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Inject the runtime database URL from our Settings
settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url)

# Target metadata — Alembic compares this against the live DB to autogenerate
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (generates SQL without a live DB)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode against a live async engine."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Entry point for 'online' mode — runs the async migrations."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()