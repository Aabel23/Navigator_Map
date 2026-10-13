-- PostgreSQL / PostGIS schema for the navigation server.
--
-- STATUS: this DDL is the migration target. No Python adapter is written for
-- it yet, because nothing in the project currently requires one -- see
-- MIGRATION.md for what writing it involves and what it would change.
--
-- It is the same two tables as ../sqlite/schema.sql, with three engine
-- differences and nothing else:
--
--   1. The four REAL bbox columns become one GEOMETRY(POLYGON, 4326) with a
--      GiST index, so intersection is an index lookup rather than four
--      range comparisons.
--   2. Timestamps become TIMESTAMPTZ, so the database enforces what the
--      SQLite backend can only enforce in Python.
--   3. Payloads become JSONB, so a future query may reach inside one without
--      a schema change -- though no domain block may rely on that, because
--      the storage interface deliberately does not expose it.
--
-- The document interface does not change. That is the whole point.

CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE IF NOT EXISTS documents (
    collection   TEXT                     NOT NULL,
    key          TEXT                     NOT NULL,
    area         GEOMETRY(POLYGON, 4326)  NOT NULL,
    recorded_at  TIMESTAMPTZ              NOT NULL,
    valid_from   TIMESTAMPTZ,
    valid_to     TIMESTAMPTZ,
    payload      JSONB                    NOT NULL,
    PRIMARY KEY (collection, key)
);

CREATE INDEX IF NOT EXISTS documents_by_time
    ON documents (collection, recorded_at DESC);
CREATE INDEX IF NOT EXISTS documents_by_area
    ON documents USING GIST (area);

-- The validity-window filter the DocumentStore.find(at=...) argument becomes.
CREATE INDEX IF NOT EXISTS documents_by_validity
    ON documents (collection, valid_from, valid_to);

CREATE TABLE IF NOT EXISTS cache_entries (
    key        TEXT PRIMARY KEY,
    stored_at  TIMESTAMPTZ NOT NULL,
    payload    JSONB       NOT NULL
);

CREATE INDEX IF NOT EXISTS cache_entries_by_age ON cache_entries (stored_at);
