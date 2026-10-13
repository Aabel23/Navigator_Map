# Server Connections

## Main data flow

```text
External sources
      ↓
   ingest
      ↓
  roadstate
      ↓
     api
      ↓
   client
```

## Static map-data flow

```text
Map sources
    ↓
 mapdata
    ↓
 storage
    ↓
 api / published artifacts
```

## Persistence connections

```text
ingest    → storage
roadstate → storage
mapdata   → storage
api       → storage   (only where API-owned persistence is required)
```

## Direction rules

- `api` may consume documented outputs from `roadstate` and `mapdata`.
- `roadstate` may consume documented inputs from `ingest`.
- `ingest`, `roadstate`, and `mapdata` may use documented storage interfaces.
- `storage` must not depend on domain blocks.
- No circular block dependency is allowed.
- External providers must not be called directly from domain blocks when the responsibility belongs to `ingest` or another boundary block.

## Connector rule

Every cross-block connection must be represented by the relevant blocks' `connector.md` files.
The connection document describes the system-level relationship; each block's connector file describes the block-local interface.
