# Server System

## Goal

Provide backend data and services for the navigation application. The server
answers one central question — *how should this driver get from here to there,
right now* — and the four subsidiary ones that make the answer useful: what
roads are there, how fast is traffic moving, what is closed, and what has the
outside world told us lately.

## Current server blocks

Ten top-level modules under `server/`.

| Block | Responsibility |
|---|---|
| `api` | the external HTTP surface, and the composition root |
| `routing` | path search over a road graph, under a supplied cost model |
| `mapdata` | the authoritative road network and the routable graph from it |
| `traffic` | what a measured or modelled speed means, and what it costs |
| `roadstate` | closures, flooding, construction, incidents, and their validity |
| `ingest` | the only door outside data comes through |
| `storage` | persistence, behind an interface that makes the engine replaceable |
| `domain` | the geographic vocabulary every block shares |
| `config` | every deployment decision, read once from the environment |
| `observability` | logging and health |

Each block's boundary is stated in its own `connector.md`, which lives beside
its code at `server/<block>/connector.md`. The full description is
`server/ARCHITECTURE.md`; the settled decisions are `server/ARCHITECTURE_LOCK.md`;
the order things actually happen in is `server/FLOW.md`.

## Architecture principles

- One block has one primary responsibility.
- Internal implementation may change without affecting other blocks when its
  connector contract stays stable.
- Blocks communicate through explicit, documented connectors — a
  `typing.Protocol` or a plain mapping, never a shared mutable object.
- A block must not depend on another block's internal implementation details.
- Server-side domain logic must not be hidden inside transport code or storage
  code.
- Avoid creating new blocks unless a new responsibility genuinely cannot belong
  to an existing one.
- Task-specific design belongs in the task prompt, not in this file.

## Dependency direction

```text
                              api
                               │
                    ┌──────────┼──────────┬───────────┐
                    ▼          ▼          ▼           ▼
                mapdata    traffic    roadstate    ingest
                    │          │          │           │
                    └────┬─────┴────┬─────┴─────┬─────┘
                         ▼          ▼           ▼
                     routing     storage   observability
                         │          │           │
                         └──────────┴───────────┘
                                    ▼
                                 domain
```

`routing` sits **below** `mapdata`, `traffic` and `roadstate`, not beside them.
Each of the three builds or feeds something routing consumes — a graph, a cost
multiplier, a constraint — so each may import routing's types, and routing
imports none of them. That is the ordinary direction for an adapter and its
port, and it is what keeps the engine benchmarkable, contract-testable and
replaceable on its own.

This is not a convention. `server/tests/test_dependency_rules.py` reads every
production module with `ast` and fails the build on a violation, a cycle,
`sqlite3` outside `storage/sqlite/`, `flask` outside `api/`, or a block with no
`__all__`.

## Server/client boundary

```text
SERVER OWNS ROUTING
SERVER OWNS TRAFFIC PROCESSING
SERVER OWNS ROAD STATE
SERVER OWNS SERVER-SIDE MAP DATA ACCESS
SERVER OWNS INGEST
SERVER OWNS STORAGE
CLIENT OWNS MAP RENDERING / UI
```

The server provides data and server-side capabilities. The client draws the
map, animates the vehicle and provides the navigation UI; it does not decide
what the route is. A route computed on the device would be computed from
whatever data that device happened to have, and two clients would answer the
same question differently.

The client code in this repository lives at `client/map/` and
`client/location/`, and is **out of scope** for this system: these documents
govern `server/` only.

## Verification

```bash
cd server
python -m pytest              # 796 tests
python main.py --check        # wire everything, run health checks, exit 0 or 1
```
