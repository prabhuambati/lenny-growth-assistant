-- Runs only on first Postgres volume init (docker-entrypoint-initdb.d).
CREATE EXTENSION IF NOT EXISTS vector;
