"""SQLAlchemy declarative base + constraint naming conventions.

The naming_convention dict is critical for Alembic — it lets migration
scripts refer to indexes and constraints by deterministic names instead
of auto-generated ones like "ix_8f2a...". This makes migrations
reviewable and reversible.
"""
from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# Naming conventions for indexes, constraints, foreign keys.
# Alembic uses these to generate stable, readable names.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Shared base class for all ORM models."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)