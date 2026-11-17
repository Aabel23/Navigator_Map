# Geospatial indexing, real-time driver location ingestion, and geographic sharding in ride-hailing

> Method note (2026-10-13): The sandbox egress proxy blocked direct fetches of uber.com, highscalability.com, slideshare.net, theburningmonk.com, infoq.com, and h3geo.org (CONNECT 403 / DNS failure). Findings below come from web-search result content and snippets of the cited pages, not from full-page reads. Where the cited source is secondary (newsletters, blogs), that is flagged. Primary sources: Uber Engineering (H3, routing, DeepETA, fulfillment re-architecture), Ringpop docs, Redis docs, Grab, a Lyft talk (Daniel Hochman), and DiDi papers. Treat exact figures from secondary sources as needing verification.

## 1. Geohash vs S2 vs H3 vs quadtree/R-tree: edge effects, neighbors, uniform area, why Uber built H3, what Grab/Lyft/DiDi use

### Takeaway
All three grid systems (Geohash, S2, H3) turn a 2D position into a 1D cell ID that can be used as a hash or shard key. Geohash and S2 use squares and nest exactly: S2 cells have 4 children and map onto a Hilbert curve, which keeps nearby cells close in key space. H3 uses hexagons with aperture 7. Every neighbor is the same distance away, but parent/child nesting is only approximate, and each resolution has 12 pentagons. Uber built H3 because hexagons minimize quantization error as users move through a city, which matters for analysis like surge pricing. In production, Grab publicly describes geohash, Lyft describes geohash in Redis, and Uber's original dispatch system (DISCO) used S2 before Uber built H3.

### Cited Findings
**H3 (Uber)**
- Uber's H3 post (c. 2018) gives the core rationale for hexagons: they minimize the quantization error introduced when users move through a city. It also says a global grid needs both a map projection and a grid laid over it, and H3 pairs a hexagonal global grid with hierarchical indexing. — [Uber Engineering: H3](https://www.uber.com/us/en/blog/h3/) (date inferred from search metadata, page not fetched)
- An H3 hexagon has exactly 6 neighbors. All share an edge and all sit the same distance from the center. Square grids have edge and diagonal (corner) neighbors at different distances, which biases movement and spread analysis. — [Tamoco: H3, Geohash and S2](https://www.tamoco.com/blog/choosing-a-spatial-index-h3-geohash-s2); [Felt: What is H3](https://felt.com/blog/what-is-h3)
- Triangles have 12 kinds of neighbors and squares have 2 (edge and corner). Hexagons are the only one of the three with a single neighbor distance. — [Felt: What is H3](https://felt.com/blog/what-is-h3) (secondary)
- H3 is built on an icosahedron. Every resolution contains exactly 12 pentagons with 5 neighbors each, mostly located in oceans. — [cellandshape H3 viewer](https://cellandshape.com/h3-viewer); [Wherobots: H3](https://wherobots.com/discover/h3/)
- H3 has 16 resolutions (0–15) and aperture 7: each step produces 7 children, which do *not* exactly tile the parent, so containment is approximate. — [Wherobots](https://wherobots.com/discover/h3/); [cellandshape comparison](https://cellandshape.com/h3-vs-s2-vs-geohash)

**S2 (Google)**
- S2 has 31 levels (0–30). It projects onto the faces of a cube, and each cell splits into exactly 4 children, so nesting is exact. — [cellandshape comparison](https://cellandshape.com/h3-vs-s2-vs-geohash); [ky-gis: H3 vs Geohash vs S2](https://ky-gis.com/en/blog/h3-vs-geohash-vs-s2)
- S2 cell IDs follow a Hilbert curve, a space-filling curve that preserves locality. Tinder uses this to group geographically adjacent cells into the same shard. — [Tinder Engineering: Geosharded Recommendations Part 1](https://medium.com/tinder/geosharded-recommendations-part-1-sharding-approach-d5d54e0ec77a)
- Sources disagree on the S2 neighbor count: some say 8 (edge plus vertex neighbors), others say 4 edge neighbors with distortion at the cube-face seams. — [systemoverflow trade-offs](https://www.systemoverflow.com/learn/geospatial/geohashing/trade-offs-geohash-vs-h3-vs-s2-in-production) vs [ky-gis](https://ky-gis.com/en/blog/h3-vs-geohash-vs-s2) (conflict noted)

**Geohash**
- Precision is set by string length, with about 1–12 characters usable. Cells are rectangles in lat/lng space that shrink in east–west width toward the poles. A string prefix identifies a containing cell, but two points close in space can fall into cells with very different prefixes at a boundary (the edge effect). — [cellandshape comparison](https://cellandshape.com/h3-vs-s2-vs-geohash); [Grab: geohashing](https://www.grab.com/inside-grab/stories/grab-geohashing-location-grid/)
- The standard way to handle edge effects is to query the target cell plus its 8 neighbors, then filter by exact distance. Redis GEOSEARCH does this internally (see §4). — [Redis GEOSEARCH docs](https://redis.io/docs/latest/commands/geosearch/); [matthewswong: geohash vs quadtree](https://www.matthewswong.com/en/blog/geohash-quadtree-nearby-search-design/) (secondary)
- Area uniformity is less different than often claimed. One measurement found H3 res-5 cell area varies about 1.98×, versus about 2× for S2 level 7 and about 2× for 5-character geohash. — [cellandshape comparison](https://cellandshape.com/h3-vs-s2-vs-geohash) (secondary, single measurement)

**Quadtree / R-tree**
- A quadtree adapts to density by splitting a cell when it exceeds K points. An R-tree indexes bounding rectangles of arbitrary shapes, as PostGIS GiST indexes do. Both are in-memory or on-disk tree structures, not fixed global cell IDs, so they are less natural as shard keys. — [Medium: R-Tree, Geohash, S2, H3 explained](https://medium.com/@sylvain.tiset/breaking-down-location-based-algorithms-r-tree-geohash-s2-and-h3-explained-a65cd10bd3a9); [matthewswong](https://www.matthewswong.com/en/blog/geohash-quadtree-nearby-search-design/) (secondary)

**Who uses what**
- **Uber (DISCO, 2015):** Uber divided the earth into cells with Google S2 and used the cell ID as the sharding key for supply updates. To match demand, DISCO finds supply in the cells covering the area around the rider. — [QCon London 2015 takeaways (theburningmonk)](https://theburningmonk.com/2015/03/qcon-london-2015takeaways-from-scaling-ubers-realtime-market-platform/); [HighScalability: How Uber Scales Their Real-time Market Platform (2015-09-14)](http://highscalability.com/blog/2015/9/14/how-uber-scales-their-real-time-market-platform.html)
- **Grab:** Grab's consumer-facing article says it divides regions into geohash-labelled zones and uses them to locate points of interest and compute rider-to-driver distances. It also says a passenger checking fares can be mapped to available drivers in the vicinity. — [Grab: geohashing location grid](https://www.grab.com/inside-grab/stories/grab-geohashing-location-grid/)
- **Lyft:** Lyft's geospatial index used geohash-keyed Redis sorted sets (see §2/§3). A secondary newsletter says Lyft uses Google S2 and defaults to "geohash level 5 (~1 km²)", which conflates the two systems. — [Hochman talk, SlideShare](https://www.slideshare.net/slideshow/geospatial-indexing-at-scale-the-15-million-qps-redis-architecture-powering-lyft/76662828); [System Design Newsletter: Lyft](https://newsletter.systemdesign.one/p/lyft-engineering) (secondary; conflict noted)
- **DiDi:** DiDi's published dispatch research models the city as grids, with one MARL agent per grid balancing supply and demand (KDD 2021 value-function paper; CoopRide KDD 2025). The DiDi/INFORMS Interfaces paper cites Uber H3, but whether DiDi uses hexagonal cells in production is not confirmed. — [Mean-field MARL dispatch (arXiv 1901.11454)](https://arxiv.org/pdf/1901.11454); [DiDi RL dispatch, INFORMS Interfaces 2020](https://pubsonline.informs.org/doi/references/10.1287/inte.2020.1047); [Value Function is All You Need (KDD'21) review](https://liner.com/review/value-function-is-all-you-need-unified-learning-framework-for)

### Inferences
- S2 or geohash with exact nesting suits sharding and prefix or range scans, because the Hilbert/Z-order gives contiguous key ranges. H3 suits aggregation and analytics (surge, supply/demand heatmaps, ML features, k-ring smoothing), where equal neighbor distance matters. Uber's history fits this split: S2 for DISCO sharding in 2015, then H3 for marketplace analytics and pricing.
- For nearby-driver search, every grid scheme needs a "cell plus neighbors, then exact-distance filter" step. The real ranking should use road-network ETA, not straight-line distance (see §5).

### Gaps
- Could not fetch the full Uber H3 post or h3geo.org comparison pages to verify the exact original wording and publication date (Uber H3 was open-sourced around 2018; the date is inferred).
- Found no primary Grab engineering post naming the index (geohash, S2, or H3) used inside Grab's driver-search service. Only a consumer article confirms geohash.
- No primary confirmation of the S2 level Uber DISCO used, or of the cell area.
- Whether Lyft moved from geohash to S2 or H3 after 2017 is not confirmed.

## 2. Driver location ingestion and storage at scale: Uber DISCO/Ringpop, Grab, Lyft, Kafka/Flink

### Takeaway
Uber's 2015 DISCO design used a stateful, in-memory geo index partitioned by S2 cell. Ringpop distributed that index over Node.js workers: a consistent-hash ring with SWIM gossip membership and request forwarding. Ringpop has since been archived. Uber's fulfillment re-architecture cites the peer-to-peer protocol's physical limits and moved to centralized shard management with Apache Helix and ZooKeeper. Lyft stored driver positions in geohash-bucketed Redis sorted sets, with timestamp scores used to expire stale drivers, reaching about 15M QPS.

### Cited Findings
**Uber DISCO + Ringpop (2015)**
- Vehicle movement is sent as location updates to "geo by supply". To match riders to drivers or show cars on the map, DISCO queries "geo by supply". The S2 cell ID is the sharding key for supply updates. — [HighScalability (2015-09-14)](http://highscalability.com/blog/2015/9/14/how-uber-scales-their-real-time-market-platform.html); [theburningmonk QCon London 2015](https://theburningmonk.com/2015/03/qcon-london-2015takeaways-from-scaling-ubers-realtime-market-platform/)
- A 2015 talk summary notes a drawback: S2 cells have a fixed size, so update activity may not be evenly spread across the key space (hotspot risk). — [theburningmonk QCon London 2015](https://theburningmonk.com/2015/03/qcon-london-2015takeaways-from-scaling-ubers-realtime-market-platform/)
- The often-cited figure that drivers send location every 4 seconds appears only in a low-reliability secondary write-up, which also claims the index lived in a Ringpop cluster without persistence. — [archon-eight: How Uber built their dispatch system](https://archon-eight.vercel.app/company-architecture/uber-dispatch) (UNVERIFIED)
- Ringpop's membership uses a SWIM variant. Unlike standard SWIM, it keeps "down" members in the list so that split-brain clusters can be merged later. It builds a consistent-hash ring from member addresses, using FarmHash, to minimize the keys that must be rebalanced when the cluster is resized. — [Ringpop docs: Architecture, Design, and Implementation](https://ringpop.readthedocs.io/en/latest/architecture_design.html)
- Around early 2015, Ringpop was paired with Riak for high availability. Stackshare calls Ringpop Uber's "now deprecated tool for application-layer sharding". — [Stackshare: Uber tech stack timeline](https://stackshare.io/stack-history-timeline-uber-tech-stack-evolution); [Riak: Uber's Ringpop and Riak](https://riak.com/posts/technical/ubers-ringpop-and-riak)
- The ringpop-node repository is archived and no longer actively developed. — [GitHub uber-node/ringpop-node](https://github.com/uber-node/ringpop-node)
- **Why Uber moved away from Ringpop:** Uber's fulfillment platform re-architecture says Ringpop "suffered from physical limits given the peer-to-peer nature of the protocol". This capped how far a pod could scale once a city's concurrent trips passed a threshold. The new design uses Apache Helix and ZooKeeper for centralized shard management. — [Uber Engineering: Fulfillment Platform Re-architecture](https://www.uber.com/ke/en/blog/fulfillment-platform-rearchitecture/) (via search snippet; the post is c. 2021)

**Lyft**
- Daniel Hochman's talk "Geospatial Indexing at Scale: The 15 Million QPS Redis Architecture Powering Lyft" (c. 2017) says region is a poor hash key because it creates hot shards, and that bulk expiration could block Redis longer than expected. It also notes Redis GEO shipped stable in Redis 3.2.0 (May 2016) and uses geohash with a sorted set internally. — [SlideShare: Hochman, Lyft](https://www.slideshare.net/slideshow/geospatial-indexing-at-scale-the-15-million-qps-redis-architecture-powering-lyft/76662828)
- Secondary accounts of the same talk say each geohash cell is a Redis sorted set, with the update timestamp as the score. Stale drivers (about 30 s without an update) are removed with ZREMRANGEBYSCORE, and the cell size is about 1 km² (geohash level 5), so each shard holds few cars. — [System Design Newsletter: Lyft Engineering](https://newsletter.systemdesign.one/p/lyft-engineering); [The Excited Engineer: 5-second queries to 15M QPS](https://theexcitedengineer.substack.com/p/scaling-from-5second-queries-to-15) (secondary; both derive from the talk)

**Grab**
- Grab's real-time ingestion stack synchronizes MySQL, Aurora, and DynamoDB to Kafka. A stream processor reads from Kafka and writes to S3 every minute. This describes CDC and analytics ingestion, not driver GPS pings. — [Grab Engineering: Real-time data ingestion](https://engineering.grab.com/real-time-data-ingestion)
- A secondary write-up says Grab's Kafka platform (Coban team) processes more than 300 billion events per week. — [Factor House: How Grab uses Kafka](https://factorhouse.io/articles/grab-kafka-architecture/) (secondary)
- GrabShare's matching algorithm weighs trip angle, ETA, detour, and efficiency. — [Grab Engineering: Data and Science behind GrabShare Part I](https://engineering.grab.com/the-data-and-science-behind-grabshare-part-i)

**Generic pattern (non-company)**
- A common reference architecture: driver app → gateway → Kafka topic keyed by driver or cell → stream processor → in-memory geo index (Redis GEO or H3-cell sets) plus a cold store or trajectory log. — [Kulkul Technology: real-time geospatial driver matching](https://www.kulkul.tech/blog/architecting-for-scale-how-to-build-a-real-time-geospatial-driver-matching-system/) (non-primary architectural reference)

### Inferences
- The latest location is ephemeral, high-churn state, so every company covered keeps it in memory: Uber's Ringpop workers, Lyft's Redis. Durability comes from replays of the update stream (a new ping arrives within seconds) or from a separate log such as Kafka, not from the index itself.
- Uber's move from gossip-based self-sharding (Ringpop/SWIM) to centralized shard placement (Helix/ZooKeeper) is the main architectural lesson. Peer-to-peer membership is simple to bootstrap, but convergence and fan-out costs cap cluster size, while a centralized controller enables deliberate rebalancing.

### Gaps
- No primary Uber source found for the exact ping interval (commonly "4 s") or for update volume in QPS.
- No primary Grab engineering post found on its driver-location or driver-state service, or on how GPS pings flow to matching.
- No primary source found for a Flink-based driver-location pipeline at Uber, Lyft, or Grab. Uber's broader use of Kafka and Flink is known, but it was not verified here for location ingestion.
- Could not determine whether Ringpop was replaced Uber-wide or only in the fulfillment platform. The cited post covers fulfillment only.

## 3. Geographic sharding: by city, by cell, by S2 cell ID; hotspots and cross-boundary queries

### Takeaway
Sharding by city or region is simple but creates hot shards, because big cities dominate. Lyft explicitly calls region a poor hash key. Sharding by fine-grained cell ID (S2 or geohash) spreads load, and with S2's Hilbert ordering, ranges of adjacent cells can be grouped so one shard serves a contiguous area. Hotspots such as airports and events remain a risk, since cells are fixed-size. A radius query that crosses cell or shard boundaries is handled by covering the query circle with a set of cells and fanning out to the shards that own them.

### Cited Findings
- Uber DISCO used the S2 cell ID as the sharding key, and the fixed cell size could leave update activity unevenly spread (hotspots). — [theburningmonk QCon 2015](https://theburningmonk.com/2015/03/qcon-london-2015takeaways-from-scaling-ubers-realtime-market-platform/)
- Lyft: "region is a poor hash key (hot shards)". The fix was small geohash cells as keys. — [Hochman, SlideShare](https://www.slideshare.net/slideshow/geospatial-indexing-at-scale-the-15-million-qps-redis-architecture-powering-lyft/76662828); [System Design Newsletter](https://newsletter.systemdesign.one/p/lyft-engineering) (secondary)
- Tinder shards by S2 cells. Because S2 follows a Hilbert curve, cells grouped into a shard are geographically together, and shards are sized to balance load across dense and sparse areas. — [Tinder: Geosharded Recommendations Part 1](https://medium.com/tinder/geosharded-recommendations-part-1-sharding-approach-d5d54e0ec77a) (non-ride-hailing but directly analogous)
- Uber's fulfillment re-architecture points to per-city scaling limits: Ringpop pods capped the scale of a city once concurrent trips passed a threshold, which motivated centralized shard management. — [Uber: Fulfillment Platform Re-architecture](https://www.uber.com/ke/en/blog/fulfillment-platform-rearchitecture/)

### Inferences
- A practical design is a hybrid: route by region for data residency and failover (city or region cells), then shard within the region by S2 or H3 cell ranges, sized by load rather than by area. Hot cells such as an airport lot or a stadium after an event can be split to a finer level or replicated for reads.
- Cross-boundary radius queries: compute a cell covering (S2 RegionCoverer or H3 k-ring), group the cells by owning shard, scatter-gather, merge, and re-rank by ETA. Larger cells reduce fan-out but increase false positives.

### Gaps
- No primary source found describing airport or event hotspot handling (dynamic cell splitting, queueing lots) at Uber, Grab, or Lyft.
- No primary data on shard counts or per-shard QPS for current (2024–2026) production systems.

## 4. In-memory stores (Redis GEO, Tile38, custom) vs DB (PostGIS); persistence; throughput

### Takeaway
Redis GEO is a sorted set scored by a 52-bit interleaved geohash. GEOSEARCH is O(N + log M) and scans about 9 geohash ranges. It is fast and simple but has no per-member TTL, so stale drivers must be removed manually. Tile38 is a purpose-built in-memory geo database with geofencing, but its throughput numbers are anecdotal (about 100K+ ops/s on 4 cores, per its author). PostGIS (R-tree over GiST) suits durable, complex-geometry queries and is not the hot path for high-frequency location pings. Lyft's Redis setup reached about 15M QPS through sharding.

### Cited Findings
- GEOADD stores members in a sorted set whose score is a 52-bit geohash, built by interleaving latitude and longitude bits. A double score holds 52-bit integers without loss of precision. — [Redis GEOADD docs](https://redis.io/docs/latest/commands/geoadd/)
- GEOSEARCH, available since Redis 6.2.0, replaces the deprecated GEORADIUS and GEORADIUSBYMEMBER. Complexity is O(N+log(M)): N is the number of elements in the grid-aligned bounding box around the shape, M the number of items inside the shape. Without `ANY`, results are sorted, so a large area with a small COUNT is slow. With `ANY`, the search stops early but results may not be the nearest. The search checks about 9 geohash ranges (cover plus 8 neighbors) and uses Haversine distance. — [Redis GEOSEARCH docs](https://redis.io/docs/latest/commands/geosearch/)
- Redis has no per-member expiry inside a GEO set, so stale drivers must be removed separately, for example by keeping a timestamp sorted set alongside the geo set. — [oneuptime: Redis geo queries (2026-01-27)](https://oneuptime.com/blog/post/2026-01-27-redis-geo-queries/view) (secondary)
- Lyft scaled a Redis geospatial index to about 15M QPS. Bulk expiration could block Redis longer than expected. — [Hochman, SlideShare](https://www.slideshare.net/slideshow/geospatial-indexing-at-scale-the-15-million-qps-redis-architecture-powering-lyft/76662828)
- Tile38 is an open-source in-memory geospatial database with geofencing and its own `tile38-benchmark` tool. — [GitHub tidwall/tile38](https://github.com/tidwall/tile38)
- On Hacker News, Tile38's author Josh Baker estimated in-memory throughput at 100K+ ops/s on a 4-core, 8 GB server and called simple point operations "sub microsecond fast in many cases". He added he had no exact numbers and that results depend on object complexity and density. — [HN thread on Tile38 (c. 2017)](https://news.ycombinator.com/item?id=13284741) (anecdotal)
- Open questions from users about Tile38 at scale, such as 10K inserts/s with 100K geofences, appear in GitHub issues without published answers. — [tile38 issue #274](https://github.com/tidwall/tile38/issues/274); [issue #250](https://github.com/tidwall/tile38/issues/250)

### Inferences
- The hot path should be a sharded in-memory index (Redis GEO, cell→set maps keyed by H3 or S2, or a custom in-process index), with the location stream in Kafka as the durability or replay source. PostGIS belongs to cold or analytical paths: trip history, geofence and zone definitions, offline analysis.
- Redis persistence (AOF/RDB) is mostly unnecessary for live locations, which self-heal within one ping interval. Replication matters more than persistence.

### Gaps
- No reliable published head-to-head benchmark found for Redis GEOSEARCH vs Tile38 vs PostGIS on the same hardware.
- No primary data on PostGIS throughput for high-frequency point updates.

## 5. Map matching and ETA/routing engines (OSRM, Valhalla, GraphHopper, Gurafu, contraction hierarchies) as they affect dispatch

### Takeaway
Dispatch ranks candidates by road-network ETA, not straight-line distance. Uber started on OSRM, which is built on contraction hierarchies (CH). Because full CH rebuilds were too slow for live traffic, Uber kept node ordering fixed and updated only the edges that changed, about 10 minutes for the world graph with 10% of edges changing. It later built its in-house engine (Gurafu) and the DeepETA model, which learns a residual on top of the routing-engine ETA. Grab's matching likewise uses ETA, not just distance.

### Cited Findings
- Uber initially used OSRM, which is built on contraction hierarchies. A full CH rebuild after each traffic change was slow, so Uber moved to dynamic updates that keep node ordering and touch only changed edges. A dynamic update of the world graph takes about 10 minutes even with 10% of road segments changing speed. — [Uber Engineering: ETA Phone Home – routing engine (c. 2015)](https://www.uber.com/us/en/blog/engineering-routing-engine/)
- DeepETA is a hybrid. A routing engine (the physical model) computes ETA as the sum of segment traversal times along the best path using map data and real-time traffic, and a deep model predicts the residual against observed outcomes ("ETA post-processing"). — [Uber Engineering: DeepETA](https://www.uber.com/tr/en/blog/deepeta-how-uber-predicts-arrival-times/)
- A secondary summary says Uber computes ETA at about 500K requests per second. — [System Design Newsletter: Uber ETA](https://newsletter.systemdesign.one/p/uber-eta) (secondary)
- Gurafu: secondary sources say Uber tried A* for real-time edge-weight updates on short routes, then adopted CH. The "<5 ms" query figure appears only in a non-Uber GitHub issue. — [newsletter.systemdesign.one](https://newsletter.systemdesign.one/p/uber-eta); [GitHub issue (non-Uber)](https://github.com/YeamimHossainSajid/uber-doma-architecture/issues/7) (UNVERIFIED)
- Map matching: a secondary explainer says Uber uses a Kalman filter plus HMM/Viterbi map matching. The underlying academic approach is HMM-based multi-track map matching. — [dev.to: How Uber computes ETA](https://dev.to/ayeshaiftikhar/how-uber-computes-estimated-time-of-arrival-eta-7eh) (secondary); [arXiv 1209.2759: Multi-track Map Matching](https://arxiv.org/pdf/1209.2759)
- Grab notes that the nearest driver by straight line may have a worse route and ETA, so cell distance is used to shortlist and ETA to rerank. GrabShare matching uses ETA and detour. — [Grab Engineering: GrabShare Part I](https://engineering.grab.com/the-data-and-science-behind-grabshare-part-i)

### Inferences
- In practice dispatch runs in two stages: the geo index produces about K candidates (cell plus neighbors), then a batched ETA service (CH-based routing plus an ML correction) reranks them. The cost of the ETA call, not the geo lookup, usually dominates dispatch latency, which is why CH or customizable routing with fast traffic updates is essential.
- OSRM (CH, fast queries, slow to customize), Valhalla (tiled, dynamic costing), and GraphHopper (CH plus landmarks/ALT, flexible mode) trade query speed against how quickly live traffic can be applied.

### Gaps
- No primary Uber source on Gurafu internals or query latency.
- No primary comparison of OSRM vs Valhalla vs GraphHopper performance found in this research. The characterization in the inferences comes from general knowledge, not citations.
- No primary source on Grab's or Lyft's routing engines (both are often said to have used OSRM-derived or in-house engines; not verified).
