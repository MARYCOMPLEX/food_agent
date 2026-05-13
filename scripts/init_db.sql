-- Initial DDL run once on first Postgres container start
-- (mounted at /docker-entrypoint-initdb.d/init.sql by docker-compose).
-- Application code creates its own tables; we only need the vector
-- extension to be available before they reference it.

CREATE EXTENSION IF NOT EXISTS vector;
