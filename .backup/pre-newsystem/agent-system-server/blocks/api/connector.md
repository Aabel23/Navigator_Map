# api — Connector

## Responsibility

Own the external server interface and transport-level translation.

## Inputs

- client requests
- consumer requests
- documented outputs from server blocks

## Outputs

- API responses
- published server-facing protocol responses

## Connectors

### `api → roadstate`
Requests dynamic road-state information through the documented roadstate interface.

### `api → mapdata`
Requests published map-data artifacts/metadata through the documented mapdata interface.

### `api → storage`
Uses storage only for data that is explicitly owned by the API layer.

### `api → client`
Exposes the public server API.

## Boundary rule

`api` translates transport data; it must not become the owner of routing, road-state aggregation, map building, or storage policy.
