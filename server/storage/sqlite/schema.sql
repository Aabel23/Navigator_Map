-- SQLite schema for the navigation server.
--
-- Two tables, because the server persists two different kinds of thing: facts
-- it was told (documents) and answers it does not want to ask upstream for
-- twice (cache entries).
--
-- The bounding box is four REAL columns rather than a geometry type. SQLite
-- has no spatial type without an extension, and four indexed floats answer
-- "does this row's box intersect that box" exactly. The PostGIS migration
-- replaces these four columns with one GEOMETRY and a GiST index; see
-- ../postgres/MIGRATION.md.

CREATE TABLE IF NOT EXISTS documents (
    collection   TEXT    NOT NULL,
    key          TEXT    NOT NULL,
    west         REAL    NOT NULL,
    south        REAL    NOT NULL,
    east         REAL    NOT NULL,
    north        REAL    NOT NULL,
    recorded_at  TEXT    NOT NULL,   -- ISO-8601, always UTC, always aware
    valid_from   TEXT,
    valid_to     TEXT,
    payload      TEXT    NOT NULL,   -- JSON. Never read by this block.
    PRIMARY KEY (collection, key)
);

-- The two axes every query filters on.
CREATE INDEX IF NOT EXISTS documents_by_time
    ON documents (collection, recorded_at DESC);
CREATE INDEX IF NOT EXISTS documents_by_area
    ON documents (collection, west, east, south, north);

CREATE TABLE IF NOT EXISTS cache_entries (
    key        TEXT PRIMARY KEY,
    stored_at  REAL NOT NULL,        -- unix seconds
    payload    TEXT NOT NULL         -- JSON
);

CREATE INDEX IF NOT EXISTS cache_entries_by_age ON cache_entries (stored_at);
