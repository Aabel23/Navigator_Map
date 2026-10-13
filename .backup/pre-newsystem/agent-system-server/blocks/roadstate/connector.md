# roadstate — Connector

## Responsibility

Maintain the server's dynamic state for road/segment conditions.

## Inputs

- normalized observations from `ingest`
- persisted state/history through `storage` when required

## Outputs

- current road/segment state
- state information consumed by `api`
- state information used by server-side consumers when explicitly connected

## Connectors

### `ingest → roadstate`
Consumes normalized observations.

### `roadstate → api`
Provides queryable dynamic road state to the API layer.

### `roadstate → storage`
Reads/writes persistent state through the storage interface when required.

## Boundary rule

API code must not implement road-state aggregation logic. Storage code must not implement road-state domain policy.
