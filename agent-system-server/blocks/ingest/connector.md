# ingest — Connector

## Responsibility

Be the only door outside data comes through. Receive, validate, normalise,
timestamp, attribute a source, and survive a feed that is down.

Make **no judgement about meaning**. Records carry no traffic level; reports
carry no condition kind. What leaves is what the source *said* — a speed, a
free-flow reference, a title, a window. The interpretation happens one block
downstream, in one place, for every provider at once. That is what lets a
second provider be added without a second opinion arriving with it.

## Inputs

| Name | Type | Source |
|---|---|---|
| area | `domain.BBox` | whoever is asking |
| provider feeds | JSON over HTTP | Digitraffic (Finland, free, keyless) |
| a reference road network | `RoadNetwork` protocol | `mapdata`, handed in |
| GPS probes | raw mappings | clients, via `POST /api/v1/ingest/probes` |
| incident reports | raw mappings | operators and clients, via `POST /api/v1/ingest/reports` |

## Outputs

| Name | Type | Meaning |
|---|---|---|
| `Observations` | frozen dataclass | one provider's batch: bbox, source, instant, segments/observations/incidents |
| `TrafficObservation` | frozen dataclass | a speed measured at a *point*, with `.ratio` |
| `TrafficSegment` | frozen dataclass | a speed on a *stretch*, with `.ratio`, `.road_id` |
| `TrafficIncident` | frozen dataclass | an event with a validity window and a `blocking` flag |
| `Collection` | dataclass | what a collect produced, plus the failures, by provider name |
| `GpsProbe`, `parse_probe`, `probes_to_observations` | types and functions | validated client positions |
| `normalize_report`, `normalize_reports`, `report_of_incident` | functions | a report reduced to shape, with provenance |
| `IngestError`, `ProviderUnavailable`, `OutsideCoverage`, `BadResponse` | exceptions | the whole failure surface |

## Connectors

### `external → ingest`

Provider-specific transport and schema enter here and go no further.

### `ingest → traffic`

`Observations` batches. Provider-independent, and **level-free**: a speed, a
free-flow reference, and the ratio between them. What that ratio *means* is
`traffic`'s decision.

### `ingest → roadstate`

A normalized report — a plain mapping with id, geometry, kind hint, severity,
window and provenance. `roadstate.classify` decides what it actually is.

### `mapdata → ingest` — `RoadNetwork`

A structural `typing.Protocol`. The modelled provider needs geometry to attach
numbers to; neither block imports the other, and whoever composes the server
hands one in.

### `api → ingest`

`POST /api/v1/ingest/probes`, `/reports`, `/refresh`.

## Stable guarantees consumers may rely on

- **Coverage routing.** A provider declaring a region is only asked about
  boxes inside it. A Finnish sensor network asked about Ho Chi Minh City says
  "not mine" rather than returning an empty result that reads like a
  free-flowing city.
- **Measured before modelled.** The fallback is consulted only where no
  measuring provider produced anything. The simulated provider never competes
  with a sensor.
- **A failure is not fatal, and it is named.** A provider that raises is
  dropped from that refresh and recorded *by name*, and the failures are
  returned rather than logged and forgotten. A map that quietly shows an empty
  city because a feed timed out is worse than one that says so.
- **Modelled data always says so.** Records from `SimulatedTrafficProvider`
  carry `source: "simulated"` — the exact string `SIMULATED_SOURCE` — and the
  API reports it. Nothing downstream and no driver can mistake a model for a
  measurement.
- **Probes are refused loudly.** Rejections are counted and returned with
  reasons: a client whose submissions silently vanish has no way to discover
  its field names are wrong.
- Every record is timestamped aware-UTC and carries its source.

## Forbidden internal details

- `ingest.http`, `ingest.external_sources.*` as import paths for anything but
  constructing a provider; everything else comes from `ingest`.
- the Digitraffic endpoint set, its cache TTLs, its Finnish keyword list.
- the congestion curve inside the simulated provider.
- **No traffic level, cost, multiplier or condition kind may be computed
  here.** That is the boundary.

## Inside the block

```text
ingest/
├── __init__.py                    the public surface
├── models.py                      the record types + the Observations batch
├── provider.py                    TrafficProvider (ABC), RoadNetwork, RoadLike
├── errors.py                      the four failures
├── http.py                        the one place this block touches the network
├── traffic/collector.py           TrafficCollector: the three policies
├── gps/probes.py                  parse_probe, probes_to_observations
├── incidents/reports.py           normalize_report, report_of_incident
└── external_sources/
    ├── digitraffic.py             measured: Finland, free, keyless
    └── simulated.py               modelled: deterministic, anywhere
```

**The three flows in, side by side.**

```text
  external feed              GPS probe                incident report
  (digitraffic.py,           (client)                 (operator, client)
   simulated.py)                 │                           │
       │  http.py                │                           │
       ▼                         ▼                           ▼
  traffic/collector.py      gps/probes.py            incidents/reports.py
   coverage routing          strict validation        shape validation
   measured > modelled       implausible dropped      provenance stamped
   failures isolated         stationary excluded
       │                         │                           │
       └────────────┬────────────┘                           │
                    ▼                                        ▼
               Observations                        normalized report (mapping)
                    │                                        │
                    ▼                                        ▼
            traffic.attach / TrafficState            roadstate.classify
```

**File by file.** `models.py` defines what a normalized record *is* and
deliberately gives none of them a level — that absence is the block boundary
showing up in the type system. `provider.py` defines the seam: `TrafficProvider`
is an ABC with `fetch(area)` and `coverage()`, and `RoadNetwork`/`RoadLike` are
structural protocols so a modelled provider can be handed geometry without
importing `mapdata`.

`external_sources/digitraffic.py` is the reference adapter: four upstream
endpoints at three different refresh rates, each cached separately, gzip
mandatory because the API answers 406 without it, and free-flow references read
from the per-station document because they are not on the station list.
`external_sources/simulated.py` fills the gap where no free feed exists — a
deterministic model over the road network it is handed, hashed rather than
random so two workers agree about the same street.

`traffic/collector.py` is what turns a list of providers into one answer, and
it carries the three policies above. `gps/probes.py` and `incidents/reports.py`
are the two doors that do not involve a provider at all: a client posting where
it is, and a human reporting that a street is under water.
