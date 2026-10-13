# Traffic Block

Dynamic traffic state: how fast the network is actually moving, what is
blocking it, and what that should cost a route.

**Status: partially built.** The core, two providers and one road source are
written and verified against the live upstream. The contract documents, the
tests, the routing cost adapter and the map sandbox are not written yet — see
[What is left](#what-is-left).

---

## The free-data question, and its honest answer

The session brief was to find a *free* traffic API. Here is what the survey
found, because the answer shapes the whole block.

### There is no free live traffic API that covers the world

Every commercial provider (TomTom, HERE, Google Routes, Mapbox) is paid or
freemium-with-a-paid-tier. Every genuinely free live source is a **national or
regional road authority publishing its own sensors**. That means coverage is a
patchwork of countries, and it means a provider has to be able to declare
which box it can answer for — which is why `TrafficProvider.coverage()` exists.

### Free sources worth knowing about

| Source | Area | Data | Key needed | Format |
|---|---|---|---|---|
| **[Digitraffic](https://www.digitraffic.fi/en/road-traffic/)** (Fintraffic) | Finland | live speeds, flow, incidents, roadworks | **no** | JSON + GeoJSON |
| [NDW](https://docs.ndw.nu/en/) | Netherlands | speeds, incidents, roadworks | no | DATEX II + custom |
| [data.gouv / national network](https://github.com/graphhopper/open-traffic-collection) | France | live traffic + events | no | DATEX II |
| [511 SF Bay](https://511.org/open-data/traffic) | SF Bay Area | events, work zones (WZDx) | free token | JSON |
| [National Highways](https://developer.data.nationalhighways.co.uk/) | England | journey times, closures | free registration | DATEX II |
| [Traffic Scotland](https://www.traffic.gov.scot/traffic-scotland-developer-hub) | Scotland | incidents, roadworks | free registration | DATEX II |
| Norway / Sweden / Slovenia / Czechia / Estonia NAPs | per country | mixed | free registration | DATEX II |
| [Overpass API](https://overpass-api.de/) (OpenStreetMap) | worldwide | road geometry, `maxspeed`, closures | no | JSON |

The [graphhopper/open-traffic-collection](https://github.com/graphhopper/open-traffic-collection)
catalogue is the best index of these and is worth re-reading before adding a
country.

### Why Digitraffic is the reference provider

It is the only source found that is open on *every* axis at once: no API key,
no registration, no quota, no paid tier behind the free one, JSON rather than
DATEX II XML, and **measurements rather than estimates**. Roughly 490 roadside
stations publish a five-minute rolling average speed per direction, refreshed
every minute — and the station metadata publishes a **free-flow reference
speed for the same direction**, so the congestion ratio comes from one source
that measured both halves of it instead of a measured speed divided by a legal
speed limit.

Two upstream quirks that are easy to lose:

- `Accept-Encoding: gzip` is **mandatory**. Without it the API answers
  `406 Not Acceptable`. Handled in `traffic/http.py`.
- Free-flow speeds are only on the **per-station** document
  (`/api/tms/v1/stations/{id}`), not the station list. Fetched lazily for the
  stations actually inside the requested box, then kept.

### And for Ho Chi Minh City

There is no free live traffic API for Vietnam. The city runs a camera-based
traffic portal (`giaothong.hochiminhcity.gov.vn`) but publishes no open API
behind it. So the map's home city has no measured feed, and the block covers
that gap with `SimulatedTrafficProvider` — a deterministic model over free OSM
geometry, labelled `simulated` on every record so nothing downstream and no
driver can mistake it for a measurement.

---

## What is built

```text
traffic/
└── traffic/                      production, stdlib-only
    ├── __init__.py               the public interface — import from here
    ├── models.py                 BBox, RoadSegment, TrafficObservation,
    │                             TrafficSegment, TrafficIncident, TrafficSnapshot
    ├── levels.py                 speed ratio -> level, colours, level_payload()
    ├── geo.py                    haversine, polyline length, bearing
    ├── provider.py               TrafficProvider ABC + RoadSource protocol
    ├── store.py                  TrafficStore: coverage routing, TTL cache, failure isolation
    ├── http.py                   the one place this block touches the network
    ├── errors.py
    ├── providers/
    │   ├── digitraffic.py        free, keyless, live — Finland
    │   └── simulated.py          deterministic model, anywhere
    └── sources/
        └── overpass.py           free OSM road geometry (a RoadSource)
```

Three record kinds, because open traffic data really does come in three
shapes: an **observation** is a measurement at a point (what sensors give), a
**segment** is a stretch of road carrying a level (what a driver sees coloured
on a map), and an **incident** is an event with a validity window.

`TrafficStore` is the single entry point. It routes a box to the providers
that cover it, prefers measured data over modelled, caches on a quantised box,
and never lets one provider's failure take out the rest — a route without
traffic is worse than one with it, but a route that never computes is worse
than both.

### Verified working

Run against the live API on 2026-09-12, Helsinki box `24.6,60.10,25.20,60.35`:

```text
sources: ['digitraffic']   simulated: False   failures: []
counts: {'segments': 0, 'observations': 123, 'incidents': 40}
  digitraffic:23117:1   MODERATE   41.0 / 80.0 kph   Road 1 Helsinki Munkkiniemi
  digitraffic:20013:1   LIGHT      89.0 / 105.0 kph  Road 1 Espoo, Sinimäki 2
  INCIDENT roadworks medium blocking=False pts=218  Tie 101, eli Kehä I, Helsinki. Tietyö.
```

Overpass was verified separately: 820 drivable ways over central District 1,
Ho Chi Minh City, in 2.5 s / 119 kB.

---

## What is left

In the order it should be picked up again:

1. **`traffic/cost.py`** — turn a snapshot into `{edge_id: multiplier}` for
   `routing.costs.DynamicCostProvider`. A plain dict, so this block never
   imports the routing block. Blocking incidents produce an infinite cost.
2. **Contract documents** — `context.md`, `contract.md`, `ports.md`, following
   `agent-system/templates/`. The map block's are the model to copy.
3. **Tests** — `traffic/tests/`, pytest, no network: recorded Digitraffic and
   Overpass responses as fixtures, a fake `HttpClient`, and determinism tests
   for the simulated provider.
4. **The map sandbox** — `traffic/sandbox/`, the original goal of the session:
   a Flask app serving the map block's page plus a 2D canvas overlay that
   draws the snapshot in level colours. Design already settled:
   - the map block declares `camera_state` as an output port in its contract
     but never publishes it; the overlay needs exactly that one value, so
     `map/ui/static/app.js` gains a one-line publication of the live camera
     object and `map/ports.md` records it. **Not yet done.**
   - the overlay imports `lonLatToWorldZ0` from the map's own
     `/static/tile_math.js`, so both agree on projection by construction.
   - the sandbox serves the map's static directory unchanged and adds its own
     `/api/traffic?bbox=` endpoint over `TrafficStore.snapshot().to_geojson()`.
   - two regions to switch between: Helsinki (real, measured) and Ho Chi Minh
     City (simulated over Overpass roads).

## Running it

No dependencies for the core — stdlib only.

```bash
python -c "
import sys; sys.path.insert(0, '.')
from traffic import BBox, TrafficStore
from traffic.providers.digitraffic import DigitrafficProvider
print(TrafficStore([DigitrafficProvider()]).snapshot(BBox(24.6, 60.1, 25.2, 60.35)).meta())
"
```

## Attribution

Digitraffic data is published by Fintraffic under CC BY 4.0. OSM geometry is
© OpenStreetMap contributors under ODbL. Both must be credited wherever this
block's output is displayed.
