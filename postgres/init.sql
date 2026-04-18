-- PostgreSQL initialization script
-- This runs ONCE when the postgres container first creates the database.
-- On subsequent starts, the volume already exists and this is skipped.

-- Enable useful extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";  -- UUID generation
CREATE EXTENSION IF NOT EXISTS "pgcrypto";   -- Cryptographic functions

-- Schema objects (tables, indexes) will be managed by Alembic migrations
-- from the backend. This file is only for database-level setup.