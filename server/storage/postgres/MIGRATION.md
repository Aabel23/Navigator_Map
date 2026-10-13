# SQLite → PostgreSQL/PostGIS

**Status: planned, not built.** `schema.sql` in this directory is the target
DDL. There is no `PostgresStorage` class yet, and this document does not
pretend otherwise — the server runs on SQLite today and nothing in the project
currently requires more. This file exists so that when something does, the
work is bounded and already understood.

## Why the migration is small

Every subsystem above `storage/` holds a `StorageBackend`, obtained once from
`config.Settings.build_storage()` in the composition root. None of them
imports `sqlite3`, names a table, or writes SQL — `tests/test_dependency_rules.py`
fails the build if one starts to. So the migration has exactly one deliverable:

```
storage/postgres/backend.py   →   class PostgresStorage(StorageBackend)
```

satisfying `DocumentStore` and `Cache`, and passing `storage/tests/test_conformance.py`
unchanged. That suite is written against the interface and parameterised over
backends; adding PostgreSQL means adding one entry to its fixture list.

Nothing in `routing/`, `traffic/`, `roadstate/`, `mapdata/`, `ingest/` or
`api/` changes. That is the property the abstraction was built for, and it is
checked rather than assumed.

## What actually differs

| Concern | SQLite today | PostgreSQL/PostGIS |
|---|---|---|
| Area | four indexed `REAL` columns | one `GEOMETRY(POLYGON, 4326)` + GiST |
| Intersection | four range comparisons | `ST_Intersects(area, ST_MakeEnvelope(...))` |
| Instants | ISO-8601 text, UTC enforced in Python | `TIMESTAMPTZ`, enforced by the engine |
| Payload | `TEXT` holding JSON | `JSONB` |
| Upsert | `ON CONFLICT ... DO UPDATE` | identical |
| Concurrency | one connection behind a lock | a real pool; drop the lock |
| Driver | `sqlite3`, stdlib | `psycopg` (LGPL, free) |

The upsert spelling is already the PostgreSQL one — SQLite adopted it — so the
write path transfers almost verbatim.

## The steps

1. Write `storage/postgres/backend.py`. Model it on `storage/sqlite/backend.py`;
   the two stores are structurally the same file with a different `_Connection`.
   Replace the bbox columns with `ST_MakeEnvelope(west, south, east, north, 4326)`
   on write and `ST_Intersects` on read.
2. Replace the single locked connection with a connection pool. The lock in the
   SQLite backend is an engine workaround, not part of the contract, and it must
   not be carried over.
3. Add the backend to the parameter list in `storage/tests/test_conformance.py`,
   skipped when no server is reachable so the suite still runs on a laptop.
4. Add `postgres` as a value of `MAP_STORAGE_BACKEND` in `config/settings.py`
   and a `MAP_DATABASE_URL` setting. Nothing else in configuration changes.
5. Migrate existing rows if any matter. For this server they generally do not:
   `roads` is rebuildable from Overpass, `observations` is a rolling window that
   is pruned anyway, and only `road_conditions` holds anything a human entered.
   A one-off script reading `DocumentStore.find()` from one backend and calling
   `put()` on the other is sufficient, and needs no SQL at all.

## What PostGIS buys, and when to bother

Nothing, until the server holds more than one city. The SQLite backend answers
a bbox query by comparing four indexed floats, which at city scale is not the
bottleneck — building the routing graph from the returned roads is.

The reasons to move are, in the order they will actually arrive:

- **Concurrent writers.** Several ingest workers writing while the API reads.
  SQLite serialises this; PostgreSQL does not.
- **More than one process.** A background ingest worker separate from the API
  process. A shared SQLite file across processes is possible and unpleasant.
- **Data larger than one machine's page cache**, where a GiST index over real
  geometries starts to matter.

Until one of those is true, moving would be adding infrastructure without a
requirement — which the architecture lock forbids.
