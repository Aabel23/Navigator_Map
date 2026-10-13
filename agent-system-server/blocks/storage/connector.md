# storage — Connector

## Responsibility

Own how bytes are kept and found again, and which engine does it. Provide
persistence capabilities; make no domain decisions.

## Inputs

- `StoredDocument` values from the blocks that own them
- an area and an instant to query on
- a cache key and a JSON payload
- a backend choice, made once in the composition root from configuration

## Outputs

| Name | Type | Meaning |
|---|---|---|
| `StorageBackend` | protocol | `.documents` → `DocumentStore`, `.cache` → `Cache` |
| `DocumentStore` | protocol | put, query by collection + area + instant, delete |
| `Cache` | protocol | get/put a JSON payload by key; every failure is a miss |
| `StoredDocument` | frozen dataclass | one row: collection, key, bounds, payload, three timestamps |
| `Collection` | enum | `roads`, `observations`, `road_conditions` |
| `SqliteStorage`, `InMemoryStorage` | classes | the two engines shipped |
| `JsonFileCache`, `cache_key` | class, function | a file cache for source responses |
| `StorageError` | exception | the only failure that escapes |

## Connectors

### `mapdata → storage`, `roadstate → storage`

Persist and read back their own documents. Each converts its own types to and
from a payload, next to the type it converts — storage never looks inside.

### `mapdata (sources) → storage.Cache`

Overpass responses are cached so a shared volunteer service is not asked the
same question twice.

### `api → storage`

Only to choose and open the backend, and to run the migration at startup.

## Stable guarantees consumers may rely on

- **One row shape.** An opaque payload plus the two axes everything queries
  on: which piece of the world it covers and when it was true. Those are
  indexable; a JSON blob is not.
- Timestamps are always UTC and always aware, enforced at the `StoredDocument`
  boundary, because SQLite has no instant type.
- A `Cache` failure is always a miss, never an exception. The caller has
  another way to get its answer and nothing useful to do with a disk error.
- The `DocumentStore` interface is what makes the SQLite-today /
  PostGIS-tomorrow migration a change to this block **alone**. See
  `postgres/MIGRATION.md`.
- `storage/tests/test_conformance.py` runs one suite against three backend
  configurations, which is what makes "replaceable" a demonstrated property
  rather than a design intention.

## Forbidden internal details

- `storage.sqlite.backend`, `storage.memory.backend` and
  `storage.interface.*` as import paths — import from `storage`.
- the SQLite schema, the table names, the column types, the connection
  handling.
- **`sqlite3` must not be imported outside `storage/sqlite/`.**
  `tests/test_dependency_rules.py` fails the build if it is.

Storage must not contain road, traffic, flooding, map, routing or API policy.
A `road_class` column would be map-data policy living in the database layer,
and the next change to that dataclass would become a schema migration.

## Inside the block

```text
storage/
├── __init__.py           the public surface
├── files.py              JsonFileCache, cache_key -- a JSON file cache with a TTL
├── interface/
│   ├── records.py        StoredDocument, Collection, utcnow -- the row shape
│   └── store.py          DocumentStore, Cache, StorageBackend, StorageError
├── memory/backend.py     InMemoryStorage: dictionaries
├── sqlite/
│   ├── backend.py        SqliteStorage -- the only module importing sqlite3
│   └── schema.sql        the DDL, applied by migrate()
└── postgres/
    ├── schema.sql        the target DDL. No adapter is written
    └── MIGRATION.md      the plan
```

**How they work together.** `interface/records.py` defines what a row *is* and
normalises its timestamps; `interface/store.py` defines what a backend must be
able to *do* with one. Neither knows an engine exists. `memory/backend.py` and
`sqlite/backend.py` each satisfy both protocols — the in-memory one for tests
and for `MAP_STORAGE_BACKEND=memory`, the SQLite one for everything else,
applying `schema.sql` on `migrate()` and holding one connection behind a lock
because a Flask dev server serves on several threads.

`files.py` is separate from all of that on purpose: it is not a
`StorageBackend`, it is a plain keyed file cache used by map-data sources, and
it has no rows, no collections and no instants.

`postgres/` holds the target DDL and the plan and **no code**. What differs
there: four indexed `REAL` columns become one `GEOMETRY(POLYGON, 4326)` with a
GiST index, ISO text becomes `TIMESTAMPTZ`, JSON text becomes `JSONB`, the
locked connection becomes a pool. What does not differ: the `DocumentStore`
interface, and therefore every line of routing, traffic, road-state, map-data
and API code.
