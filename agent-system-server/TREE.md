# Server Code Tree

```text
server/
├── api/              HTTP, serialisation, error mapping, composition root
├── routing/          path search, costs, constraints, manoeuvres. Contract v1.0
├── mapdata/          the road network, and the routable graph built from it
├── traffic/          what a speed means, and what it costs a route
├── roadstate/        closures, flooding, construction, incidents
├── ingest/           the door everything outside comes through
├── storage/          persistence, behind an interface that makes it replaceable
├── domain/           the shared geographic vocabulary. Imports nothing
├── config/           every deployment decision, read once from the environment
├── observability/    logging and health
└── tests/            cross-subsystem, plus the architecture rules
```

`server/` is a **path root, not a package**. There is no `server/__init__.py`,
and adding one would make every block a submodule of one package and break the
property that `import routing` works with nothing but that directory on the
path.

## Ownership

| Folder | Owns | Does not own |
|---|---|---|
| `api/` | HTTP transport, validation, serialisation, error mapping, composition | any computation |
| `routing/` | path search, cost models, constraints, manoeuvres, geometry | where data comes from, what a road costs |
| `mapdata/` | road geometry, its persistence, the routable graph, snapping | how fast anything is moving; rendering |
| `traffic/` | attaching measurements to roads, classifying, holding, pricing | fetching; closures |
| `roadstate/` | closures, flooding, construction, incidents; their validity | fetching; how fast traffic moves |
| `ingest/` | receiving, validating, normalising, and surviving sources | what any of it means |
| `storage/` | how bytes are kept and found again, and which engine does it | what any of those bytes mean |
| `domain/` | the neutral geographic types and the proximity index | anything with a policy in it |
| `config/` | what a deployment may change | any decision those values feed |
| `observability/` | log shape, log destination, what "working" means | what is worth logging |
| `tests/` | tests that belong to more than one block | — |

## Outside `server/`

```text
client/
├── map/              the WebGL2 basemap renderer and its dev server
└── location/         on-device GPS processing and filters

sandbox/
└── map_routing/      an integration harness, not a block

agent-system-server/  this system
.backup/              the pre-migration layout, kept because there is no VCS
```

**The client is not a server block.** `SYSTEM.md` draws the boundary: the
server provides data and server-side capabilities, and the client remains
responsible for latency-sensitive local behaviour and for everything the driver
looks at. "MapData" and "the map the driver looks at" are different things that
share a word — the first is `server/mapdata/`, the second is `client/map/`.

**The sandbox is not a block either.** It owns no domain rule; it wires blocks
together through their published interfaces so the connectors can be exercised
by hand. Nothing in `server/` may import it, and it is excluded from the
single-block rule because working on it is not working on a block.

## Rule

If a change has one obvious owner, keep the implementation inside that owner's
folder. Do not spread one responsibility across unrelated folders merely for
technical layering.

Adding a **new** block is allowed when a genuinely new responsibility appears
that cannot belong to an existing one. Adding one to avoid touching an existing
block is not.
