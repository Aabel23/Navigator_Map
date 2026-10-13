# Server Code Tree

```text
server/
├── api/
├── ingest/
├── mapdata/
├── roadstate/
├── storage/
└── tests/
```

## Ownership

| Folder | Owns |
|---|---|
| `api/` | External HTTP/API surface and transport translation |
| `ingest/` | Receiving and normalizing external observations |
| `mapdata/` | Static map-data import, build, and publication |
| `roadstate/` | Dynamic road/segment state and its domain rules |
| `storage/` | Persistence implementation and storage adapters |
| `tests/` | Tests that belong to more than one block |

## Rule

If a change has one obvious owner, keep the implementation inside that owner's folder.
Do not spread one responsibility across unrelated folders merely for technical layering.
