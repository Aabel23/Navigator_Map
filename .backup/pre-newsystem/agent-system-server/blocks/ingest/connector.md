# ingest — Connector

## Responsibility

Receive and normalize external observations before they enter server domain state.

## Inputs

- external provider feeds
- client probe data
- incident/event reports

## Outputs

- normalized observations for `roadstate`
- persisted raw/normalized records through `storage` when required

## Connectors

### `external → ingest`
Provider-specific input enters through the ingestion boundary.

### `ingest → roadstate`
Exports normalized observations in a provider-independent form.

### `ingest → storage`
Stores ingestion data through the storage interface when persistence is required.

## Boundary rule

`roadstate` must not depend on provider-specific formats or provider-specific transport code.
