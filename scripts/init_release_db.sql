-- Deployment initialization only. Application tables remain Alembic-owned.
CREATE DATABASE temporal;
CREATE DATABASE temporal_visibility;

\connect xhs_food_agent
CREATE EXTENSION IF NOT EXISTS vector;
