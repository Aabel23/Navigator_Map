# Server System

## Goal

Provide backend data and services for the navigation application.

## Current server blocks

- `mapdata` — prepares and publishes static map data.
- `ingest` — receives and normalizes external observations.
- `roadstate` — maintains dynamic road/segment state.
- `api` — exposes server capabilities to clients and external consumers.
- `storage` — owns persistence mechanisms and storage adapters.

## Architecture principles

- One block has one primary responsibility.
- Internal implementation may change without affecting other blocks when its connector contract stays stable.
- Blocks communicate through explicit, documented connectors.
- A block must not depend on another block's internal implementation details.
- Server-side domain logic must not be hidden inside transport code or storage code.
- Avoid creating new blocks unless a new responsibility genuinely cannot belong to an existing block.
- Task-specific design belongs in the task prompt, not in this file.

## Server/client boundary

The server provides data and server-side capabilities.
The client remains responsible for latency-sensitive local navigation behavior unless the architecture explicitly moves that responsibility to the server.
