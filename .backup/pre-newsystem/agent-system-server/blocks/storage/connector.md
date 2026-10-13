# storage — Connector

## Responsibility

Own persistence mechanisms and storage adapters.

## Inputs

- data explicitly owned by consuming blocks
- storage configuration

## Outputs

- persistence operations
- reads/writes through documented storage interfaces

## Connectors

### `ingest → storage`
Persistence for ingestion-owned data when required.

### `roadstate → storage`
Persistence for roadstate-owned data when required.

### `mapdata → storage`
Persistence/publication support for mapdata artifacts.

### `api → storage`
Persistence only for data explicitly owned by the API layer.

## Boundary rule

Storage must not contain road, traffic, flooding, map, routing, or API domain policy. It provides persistence capabilities, not domain decisions.
