# Server Agent System

The lightweight architecture guide for server-side development. It is
deliberately small: read it, identify the one block you are changing, read that
block's connector, and stop.

## Read order

1. `SYSTEM.md` — the blocks, the dependency direction, the server/client line
2. `TREE.md` — where code belongs, and what is not a block
3. `CONNECTIONS.md` — every cross-block contract, in one table
4. `CLAUDE.md` — the code rules, the change flow, and the single-block rule
5. `server/<block>/connector.md` — the block being changed

Nothing beyond that unless the task genuinely requires architecture-level
investigation.

## The longer documents, and when to open one

These live with the code, not here, because they describe the server rather
than the way of working on it.

| Document | Open it when |
|---|---|
| `server/README.md` | you want to run it, or call the API |
| `server/ARCHITECTURE.md` | you need the full picture of a block and why it is shaped that way |
| `server/ARCHITECTURE_LOCK.md` | you are about to change something structural — this is the list of settled decisions and the 17 rules a later agent must not undo |
| `server/FLOW.md` | you need to know *where a change lands*: what happens, in order, through named files, for each kind of request |
| `server/<block>/connector.md` | you are changing that block, or consuming it |

## Purpose

This system describes where server code belongs, how blocks connect, and the
minimum rules agents must preserve.

Task-specific implementation details belong in the task prompt and the actual
codebase, not here.

## Scope

`server/` only. `client/map/` and `client/location/` are the client and are out
of scope. `sandbox/map_routing/` is an integration harness, not a block, and is
excluded from the single-block rule.
