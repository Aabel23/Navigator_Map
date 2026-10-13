# mapdata — Connector

## Responsibility

Own static map-data preparation and publication.

## Inputs

- map-source data
- build configuration

## Outputs

- published map-data artifacts
- graph/build metadata needed by consumers

## Connectors

### `mapdata → storage`
Persists or publishes build artifacts through the storage interface.

### `mapdata → api`
Provides published artifacts/metadata for client-facing access.

## Boundary rule

Consumers must not depend on mapdata's parser, build pipeline, temporary files, or internal storage layout.
