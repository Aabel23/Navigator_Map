# Block connectors live with their code

This directory used to hold five skeleton `connector.md` files for blocks that
did not exist yet. They have been removed rather than updated, because a
second copy of a block's interface is a second thing to keep in sync and a
guarantee that somebody eventually reads the wrong one.

**Every block's `connector.md` lives here, one directory per block.** One place
to read the boundaries, one place to change them. `server/ARCHITECTURE_LOCK.md`
rule 12 -- "its `connector.md` is the interface; its internals are not" -- means
the file below.

| Block | Connector |
|---|---|
| `api` | [`api/connector.md`](api/connector.md) |
| `routing` | [`routing/connector.md`](routing/connector.md) |
| `mapdata` | [`mapdata/connector.md`](mapdata/connector.md) |
| `traffic` | [`traffic/connector.md`](traffic/connector.md) |
| `roadstate` | [`roadstate/connector.md`](roadstate/connector.md) |
| `ingest` | [`ingest/connector.md`](ingest/connector.md) |
| `storage` | [`storage/connector.md`](storage/connector.md) |
| `domain` | [`domain/connector.md`](domain/connector.md) |
| `config` | [`config/connector.md`](config/connector.md) |
| `observability` | [`observability/connector.md`](observability/connector.md) |

Each one states the block's responsibility, its inputs and outputs, the named
connectors that cross its boundary, the guarantees consumers may rely on, the
internals they may not touch, and — under **Inside the block** — what each file
in it does and how they work together.

`routing` additionally carries `contract.md`, the precise statement of its v1.0
guarantees, enforced by `server/routing/tests/contract/test_v1.py`.
