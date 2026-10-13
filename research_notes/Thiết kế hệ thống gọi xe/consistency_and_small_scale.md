# Data Consistency, Event-Driven Infrastructure & Reliability in Ride-Hailing — plus Small-Team Reference Designs

> Research method note (2026-10-13): The WebFetch tool and direct HTTPS were blocked by the environment's egress policy (uber.com, infoq.com, and dev.to all failed), so every finding below comes from search-engine summaries of the cited pages, not from reading the full pages. Treat numeric details as "per search snippet of the primary source". Where a claim comes from a secondary or interview-prep source, it is labelled.

## A1. Trip state machines, driver-assignment concurrency (locks vs CAS vs single-writer/actor), idempotency, Saga/outbox for payments

### Takeaway
Uber's own history is the clearest case study. Its first-generation fulfillment platform used a single-writer-per-shard design: Ringpop application-level sharding plus an in-memory serial queue per entity, an AP design. Multi-entity writes were done as Sagas with compensations. Uber documented that this produced hot shards, inconsistencies and manual repairs. Around 2021 it rebuilt the platform on a strongly consistent, transactional store, Google Cloud Spanner, with stateless workers. Post-commit side effects go through a transactional "action table" (LATE), which is an outbox-style pattern. For small teams, the common pattern is to make the database trip/driver row the source of truth and guard every state transition with a conditional update (compare-and-set). Redis locks with TTLs are at most an optimization on top.

### Cited Findings
- **Uber's old fulfillment design was single-writer-per-shard.** To get high scale from storage, Uber "relied on Ringpop for application-level sharding with an in-memory serial queue." Ringpop forwards requests for a key to its owning worker only on a best-effort basis, which favours availability over consistency. — [Uber: Fulfillment Platform Re-architecture](https://www.uber.com/en-CA/blog/fulfillment-platform-rearchitecture/)
- **That design was AP and hard to operate.** The Ringpop-based design "gave up consistency for high availability," which made production issues very hard to debug and reason about. Sharding by unique ID looked uniform but created hotspots from highly active jobs and supplies, and new verticals (Uber Eats, Uber Bus) made this worse. — [Uber: Fulfillment Platform Re-architecture](https://www.uber.com/en-CA/blog/fulfillment-platform-rearchitecture/)
- **Sagas for multi-entity writes caused trouble.** Developers had to plan compensating actions for writes that failed due to system faults. A failed Saga could leave entities inconsistent, sometimes needing manual repair. Storage was Cassandra behind a "Marketplace Storage Gateway," and each write went to two distinct Cassandra clusters in the region. — [Uber: Fulfillment Platform Re-architecture](https://www.uber.com/en-CA/blog/fulfillment-platform-rearchitecture/)
- **Store selection.** Uber made consistency a primary criterion alongside resilience and availability, and benchmarked CockroachDB, FoundationDB, sharded MySQL and Cloud Spanner before choosing Spanner. — [Uber: Fulfillment Platform Re-architecture](https://www.uber.com/en-CA/blog/fulfillment-platform-rearchitecture/)
- **Scale and scope (post dated 2021-09-29).** The rebuilt fulfillment platform handles billions of database transactions a day across more than 10,000 cities. Operations include user actions (driver starts trip), system actions (create a trip-to-driver match offer) and periodic location updates. — [Uber: Building Uber's Fulfillment Platform for Planet-Scale using Google Cloud Spanner](https://www.uber.com/en-UA/blog/building-ubers-fulfillment-platform)
- **Spanner workarounds.**
  - Spanner had no transaction-priority API, so Uber split transactions into customer-facing "foreground" and system "background" classes and prioritized foreground work by tuning timeouts and retries.
  - Because read-your-writes forces sequential operations and calls leave on-prem data centres, Uber built a **transaction coalescer** that batches the operations in a transaction into a single RPC.
  - Uber also manages its own Spanner session pool and uses gRPC interceptors for per-RPC observability.
  - Source: [Uber: Building Uber's Fulfillment Platform](https://www.uber.com/en-UA/blog/building-ubers-fulfillment-platform)
- **LATE, an outbox-like component.** Post-commit operations and timers are committed *with* the read-write transaction into a separate action table. Dedicated workers pick these rows up and guarantee at-least-once execution. — [InfoQ: Uber rearchitecture (Aug 2021)](https://www.infoq.com/news/2021/08/uber-rearchitecture)
- **Docstore (Uber's evolution of Schemaless, post dated 2021-02-23).**
  - It is a general-purpose multi-model database with strict serializability per partition, described as CP under CAP.
  - It runs on MySQL. The replication unit is a MySQL transaction, replicated with Raft.
  - Write conflicts are serialized by MySQL row locks.
  - Source: [Uber: Evolving Schemaless into a Distributed SQL Database](https://www.uber.com/blog/schemaless-sql-database/)
- **Redis locks in interview-style designs (secondary).** Interview-style LLD guides recommend acquiring a per-driver Redis lock (`SET NX` with expiry) before sending an offer, so one driver never gets two simultaneous offers. The lock is released on accept, decline or expiry. — [techinterview.org: LLD Ride-Share Matching](https://www.techinterview.org/post/3233472038/lld-rideshare-matching/) (secondary/interview-prep). Another secondary source argues short Redis TTL locks prevent double-booking without DB row-lock overhead. — [OneUptime: Booking lock system with Redis (2026)](https://oneuptime.com/blog/post/2026-03-31-redis-booking-lock-system/markdown)
- **Accept endpoint as the authority (secondary).** One interview design has the accept endpoint return a conflict if the ride is no longer available. That makes the trip state machine, not Redis, the authority, with Redis geo data treated as ephemeral. — [techinterview.org: Ride-Sharing Dispatch](https://www.techinterview.org/post/3233461063/system-design-rideshare-dispatch/) (secondary)
- **Hello Interview's ride acceptance.** The driver accepts or denies with a PATCH on the ride object. On acceptance the system updates ride status and returns pickup coordinates. Only a snippet was available. — [Hello Interview: Design Uber](https://www.hellointerview.com/learn/system-design/problem-breakdowns/uber)
- **Ride state transitions are consistency-critical (secondary).** One guide notes that disputes and double charges come from state mismatches. — [Educative: Lyft System Design](https://www.educative.io/blog/lyft-system-design) (secondary)
- **Temporal Saga guidance.** This came only via third-party summaries of Temporal's blog and docs; the official pages could not be retrieved.
  - Register each compensation *before* executing its step, and on failure run compensations in reverse (LIFO) order.
  - Activities can run more than once, so they and their compensations must be idempotent: use idempotency keys, upserts, and processed-request-ID tables.
  - Source: [Workflow orchestration patterns skill summarizing Temporal docs](https://tessl.io/registry/skills/github/Dicklesworthstone/pi_agent_rust/workflow-orchestration-patterns) (secondary)
- **Idempotency in payments (secondary).** The classic failure is "the write committed, and the response was lost." The fix is one idempotency key per command. The practical target is at-least-once delivery plus idempotent business logic, not exactly-once. Non-idempotent compensations cause double refunds. — [dev.to: Every distributed payment system lies](https://dev.to/dadashi/every-distributed-payment-system-lies-how-we-prevent-money-loss-1i60); [dev.to: Saga under AI agent orchestration / outbox](https://dev.to/pablets/the-saga-pattern-under-an-ai-agent-orchestration-idempotency-and-the-transactional-outbox-4mg8) (secondary)
- **Transactional outbox with Debezium on Postgres (secondary configuration guides).**
  - Write the business row and the event row in the same DB transaction.
  - Debezium reads the Postgres WAL (`wal_level=logical`, `pgoutput` plugin) and the EventRouter SMT routes each row to a Kafka topic by `aggregate_type`.
  - Consumers must be idempotent because duplicates are possible.
  - Sources: [Conduktor: Transactional Outbox](https://conduktor.io/blog/transactional-outbox-pattern-database-kafka); [RisingWave: Debezium outbox guide](https://risingwave.com/blog/debezium-outbox-pattern-guide/) (secondary; official Debezium docs not retrieved)
- **Grab on dual writes.** Grab's Coban team notes that keeping a database and Kafka consistent would require the two writes to be atomic via 2PC or another atomic-commit protocol, "which is non-trivial and impacts availability." This motivated CDC with Kafka Connect. — [Grab Engineering: Kafka Connect](https://engineering.grab.com/kafka-connect)

### Inferences
- The spectrum of approaches:
  - **(1) Distributed lock (Redis SET NX PX):** cheap but unsafe as a sole guard. A lock can expire while the holder still acts, and Redis can lose the lock on failover.
  - **(2) Compare-and-set in the system of record:** `UPDATE drivers SET state='OFFERED', trip_id=$1, version=version+1 WHERE id=$2 AND state='AVAILABLE' AND version=$3`, then check the affected rows. This is simple and correct on one Postgres.
  - **(3) Single-writer/actor per shard (Uber's Ringpop era):** high throughput, but it needs routing, rebalancing and failover. Uber's experience shows that best-effort ownership leaks consistency.
  - **(4) Distributed ACID store (Uber's Spanner era):** what Uber chose at planet scale.
- For a small team, (2) inside a single Postgres transaction gives the same guarantee Uber bought with Spanner. Add a Redis TTL lock only as a fast-path filter to avoid sending two offers.
- Uber's move away from Sagas inside the fulfillment core is a signal: use transactions where entities live in one store. Reserve Sagas or workflows for crossing genuinely separate systems (payment provider, notifications, payouts).
- LATE plus the outbox pattern means "commit state + intent atomically, execute side effects at-least-once, make consumers idempotent." This is the core reliability recipe at any scale.

### Gaps
- Could not read the full Uber re-architecture posts, so the exact Spanner schema, how driver-to-trip match is made atomic, and the post-migration double-dispatch rate are unknown.
- Found no primary Lyft or Grab post on driver-assignment locking or double-booking prevention.
- The official Temporal Saga docs page and the official Debezium docs were not retrieved directly; claims rely on secondary summaries.

## A2. Workflow engines (Cadence/Temporal) and data/stream infrastructure (Schemaless/Docstore, Grab Kafka/DynamoDB/Coban, Kafka+Flink for surge/ETA)

### Takeaway
Cadence, which Uber built and whose creators later forked it into Temporal, is a durable-execution engine for long-running, multi-service flows such as "ride lasts an hour, then bill rider and send receipt." Uber runs it at about 100K workflow updates/sec across about 30 clusters (2024). Grab uses DynamoDB as its strongly consistent OLTP order store and Kafka-based Coban pipelines to fan out to MySQL and analytics. Uber builds real-time demand/supply features for surge and forecasting with Flink.

### Cited Findings
- **Cadence's motivation (Fateev interview, 2020-04-08).** A ride can last an hour and end with the rider being billed and sent a transactional email. Many services and tables are touched, and processing must survive server failures. In asynchronous microservices, code otherwise becomes "a quagmire of callbacks." — [Software Engineering Daily: Cadence with Maxim Fateev](https://softwareengineeringdaily.com/2020/04/08/cadence-ubers-workflow-engine-with-maxim-fateev/)
- **Cadence use cases.** It covers use cases "beyond a simple request," from sign-up flows to order fulfillment to ML pipelines. Uber's blog demo is an 8-step Uber Eats order workflow. — [Uber: Open source orchestration tool Cadence overview](https://www.uber.com/blog/open-source-orchestration-tool-cadence-overview). A driver-rewards case study uses a 30-day timer plus a listener for trip-completion events. — [Slideshare: Cadence, the only workflow platform you'll ever need](https://www.slideshare.net/slideshow/cadence-the-only-workflow-platform-youll-ever-need/148473182)
- **Cadence scale.**
  - July 2024: about 100K workflow updates per second at Uber, about 30 Cadence clusters, several serving hundreds of domains. — [Cadence blog: 2024 yearly roadmap update](https://cadenceworkflow.io/blog/2024/07/11/2024-07-11-yearly-roadmap-update/yearly-roadmap-update)
  - Sept 2024: Cadence is sharded on workflow ID, so one hot workflow can overload a shard, which motivated workflow-ID-based rate limits. — [Cadence blog: Workflow ID-based Rate Limits](https://cadenceworkflow.io/blog/2024/09/05/workflow-specific-rate-limits)
  - Undated announcement post: over 12 billion executions and 270 billion actions per month at Uber. — [Uber: Announcing Cadence](https://www.uber.com/blog/announcing-cadence/)
- **Docstore.** Strict serializability per partition, on MySQL with Raft replication (Feb 2021). See A1. — [Uber: Schemaless to Docstore](https://www.uber.com/blog/schemaless-sql-database/)
- **Grab Coban.** Coban provides lightweight, Golang plugin-based pipelines running in Kubernetes: Kafka consumer pods that process data and materialize results into sinks such as RDBMS or other Kafka topics. — [Grab Engineering: Optimally scaling Kafka consumer applications](https://engineering.grab.com/optimally-scaling-kafka-consumer-applications); [InfoQ: Grab data platform (Oct 2022)](https://www.infoq.com/news/2022/10/grab-data-platform/)
- **Grab order platform (secondary).** DynamoDB is the primary transactional store because strong consistency is needed for transactional queries, with a GSI on user ID for ongoing orders. Kafka asynchronously ingests data into MySQL for analytical queries, where eventual consistency is acceptable. — [Arpit Bhayani: How Grab stores and processes millions of orders](https://arpit.substack.com/p/how-grab-stores-and-processes-millions) (secondary summary of a Grab engineering post)
- **Grab Kafka operations (vendor case study).** After moving to AutoMQ, Grab's partition reassignment time reportedly dropped from more than 6 hours to under a minute. — [AutoMQ: Grab case](https://www.automq.com/blog/how-grab-uses-automq-solve-kafka-challenges) (vendor-authored; treat cautiously)
- **Uber's Flink pipelines (2021).** Uber uses Apache Flink for real-time streaming pipelines, with internal platforms Gairos and AthenaX. ML-based decisions such as forecasting and surge consume near-real-time demand and supply features, and scaling remains a challenge. — [Uber: Building Scalable Streaming Pipelines for Near Real-Time Features](https://eng.uber.com/building-scalable-streaming-pipelines/)
- **Kafka → Flink → Kafka surge loop (secondary).** The loop of GPS events into Kafka, Flink computing supply/demand per zone, and price multipliers written back to Kafka or a cache is widely described in secondary sources. — [Kai Waehner (Nov 2024)](https://www.kai-waehner.de/blog/2024/11/14/a-new-era-in-dynamic-pricing-real-time-data-streaming-with-apache-kafka-and-flink/) (vendor-adjacent, not Uber-confirmed)

### Inferences
- A workflow engine belongs at the edges of the trip lifecycle: payment capture, refunds, driver payouts, incentive timers and multi-day onboarding. It is not the hot path for matching. Uber's matching state lives in the fulfillment DB (Spanner).
- Grab's pattern (strong-consistency OLTP store, then CDC/Kafka, then read-optimized stores) and Uber's LATE action table are the same idea at different scales.
- Surge needs only windowed aggregates per geo-cell (for example H3). Small teams can compute these with a periodic SQL job or Redis counters long before needing Flink.

### Gaps
- No primary Uber source found confirming whether trip billing currently runs on Cadence.
- No primary Lyft source found on its trip-state store or stream stack. Only a 2017 Envoy KubeCon deck shows DynamoDB and MongoDB in Lyft's stack. — [Matt Klein KubeCon 2017 slides](https://raw.githack.com/mm-k8s-ug/kubecon-slides/master/slides/2017-kubecon-na/The%20Mechanics%20of%20Deploying%20Envoy%20at%20Lyft%20-%20Matt%20Klein,%20Lyft.pdf)
- Uber's ETA-specific streaming architecture was not researched within budget.

## A3. Real-time push to apps: WebSocket vs SSE vs MQTT vs gRPC streams; connection-scale numbers

### Takeaway
Uber's RAMEN first used SSE: one long-lived downstream stream with a 4-second heartbeat, plus batched ack RPCs every 30 seconds. It handled about 600K concurrent connections and over 70K push QPS. Uber then moved to gRPC bidirectional streams over QUIC/HTTP3 (via Cronet) so acks travel instantly on the same stream. A later figure is about 1.4M peak concurrent gRPC streams and 22B messages per day. Gojek chose MQTT (VerneMQ broker, open-source "Courier" clients) to replace HTTP polling.

### Cited Findings
- **RAMEN v1 (SSE).** Uber chose SSE over long polling and WebSockets. Clients connect to an SSE endpoint with a heartbeat every 4 seconds, and acks are sent in batches to a separate endpoint every 30 seconds. — [Uber: Real-time push platform](https://www.uber.com/ae/en/blog/real-time-push-platform/)
- **RAMEN v1 scale (secondary).** Over 70,000 QPS of push messages to three app types, with up to 600,000 concurrent streaming connections. — [To The New: RAMEN vs RENO](https://www.tothenew.com/blog/?p=65166) (secondary, attributed to Uber's post)
- **Reasons for moving to gRPC.**
  - Delivery state was unknown for up to 30 seconds after a message was written, which is bad for time-limited driver offers.
  - On HTTP/1.1, bidirectional streaming would need two opposing connections, doubling connection load and creating races.
  - gRPC bidi streaming lets the ack be "sent over the same stream instantly." QUIC/HTTP3 removes head-of-line blocking, and gRPC over Cronet reuses the app's QUIC session.
  - Earlier QUIC experiments gave a 10–30% improvement in tail latencies for HTTPS traffic.
  - Source: [Uber: Next-gen push platform on gRPC](https://eng.uber.com/blog/ubers-next-gen-push-platform-on-grpc/)
- **RAMEN gRPC scale.** Over 22B messages per day and 1.4M peak concurrent gRPC bidirectional connections, per an Uber engineer's LinkedIn post surfaced in search. — [LinkedIn profile/post (search result)](https://kr.linkedin.com/in/suhkjin-hur-537644b) (weak provenance; a dev.to claim of "<100 ms latency, millions of connections" is unverified)
- **Gojek Courier (MQTT).**
  - Built to replace HTTP polling, which had high data and battery use. It uses MQTT over TCP with a VerneMQ broker for its small footprint, QoS levels and built-in acks.
  - It was rolled out first in the merchant app for order updates.
  - Gojek reports reaching 1M long-running persistent connections in a test environment, and has open-sourced Android, iOS and Go clients.
  - Sources: [Gojek: Courier library](https://blog.gojek.io/courier-library-for-gojeks-information-superhighway); [Gojek: Courier is now open source](https://blog.gojek.io/courier-is-now-open-source/); [GitHub: gojek/courier-ios](https://github.com/gojek/courier-ios)
- **Generic gateway pattern (secondary).** A stateful gateway tier owns sockets, a registry maps client to gateway, and a stateless service persists messages before pushing. Per-client cursors allow resume after reconnects. — [OneUptime: Push notifications with WebSockets (2026)](https://oneuptime.com/blog/post/2026-01-23-push-notifications-websockets-nodejs/markdown) (secondary)

### Inferences
- What matters for ride offers is **application-level acks with deadlines**, plus a fallback to OS push (FCM/APNs) and to client polling on reconnect, more than the transport itself. Uber's whole v2 migration was driven by ack latency.
- For a small team, WebSocket (or SSE plus HTTP acks) through a managed service is enough. Persist each outbound message with a sequence number so clients can re-sync after reconnecting. MQTT is attractive for flaky mobile networks and battery but adds a broker to operate.

### Gaps
- No Grab primary source found on its push/gateway platform.
- Exact RAMEN gRPC scale numbers are from a weak-provenance search result, not the Uber post body.

## A4. Multi-region / failover

### Takeaway
Uber runs two regions active-active, with each city pinned to one region at steady state and each region provisioned to absorb the other's full load. That costs about 2x capacity, with utilization around 20% and recent work raising it to about 30%. Kafka consumers are active/active for most services and active/passive for consistency-critical ones such as payments and auditing.

### Cited Findings
- **Uber's region setup (2026 paper).** A 2026 research paper describes Uber's platform as dual-region active-active microservices (regions "DCA" and "PHX"). Each city's traffic routes to exactly one region, and every service is provisioned to take over the other region's load. Each region is provisioned at twice expected peak, which the paper calls costly, and the work cites raising utilization from about 20% to about 30%. — [arXiv 2603.07345](https://arxiv.org/pdf/2603.07345); [NSDI'26 paper PDF](https://www.cs.ubc.ca/~bestchai/papers/nsdi26-ufa2.pdf)
- **Uber multi-region Kafka.** Active/active consumers switch to the other region's stream when both regions hold identical data. Active/passive mode is used by services favouring stronger consistency, such as payment processing and auditing. — [Uber: Disaster Recovery for Multi-Region Kafka](https://eng.uber.com/kafka/)
- **Spanner across Uber's on-prem and cloud regions.** Uber's Spanner migration raised the questions of networking Spanner across on-prem, AWS and GCP regions and of operating a new cloud DB at scale. — [Uber: Fulfillment Platform Re-architecture](https://www.uber.com/en-CA/blog/fulfillment-platform-rearchitecture/)

### Inferences
- "City → home region" pinning is a cell-like partitioning that avoids cross-region write conflicts for trips. A natural small-team analogue is one deployment per market or country.
- Payments get active/passive (single writer) even at Uber. Small teams should not attempt active-active writes for money.

### Gaps
- No primary Uber blog post found specifically on trip-service region failover drills or cell architecture details. Grab and Lyft multi-region approaches were not found within budget.

## B1. Reference architectures from system-design literature and their known simplifications

### Takeaway
Interview-style designs (Hello Interview, techinterview.org, DesignGurus) converge on a common shape:
- a location service with driver positions in Redis GEO, sharded by city
- Kafka for location history
- radius query, then ETA ranking via a road-routing engine
- sequential offers with a timeout of about 5 seconds
- a Redis TTL lock per driver to avoid concurrent offers

The main simplification is treating the Redis lock or Redis geo state as authoritative. Real platforms make a strongly consistent store the source of truth (Uber moved from AP Ringpop/Cassandra to Spanner) and carry side effects via outbox/action tables.

### Cited Findings
- **Location pipeline (secondary).** A Location Service writes to Redis GEO for current positions and to Kafka for history, with Cassandra as the time-series log. Matching uses GEORADIUS within about 2 km, then ETA from a road-network router rather than straight-line distance. Offers go sequentially to the top candidate and pass to the next if there is no response within about 5 seconds. Redis is sharded per metro. — [techinterview.org: Ride-Sharing App](https://www.techinterview.org/post/3233459991/design-ride-sharing-app/); [techinterview.org: Live Location Tracking](https://techinterview.org/system-design-location-tracking/); [DesignGurus: How to design Uber in 45 mins](https://designgurus.substack.com/p/how-to-design-uber-in-45-mins) (secondary)
- **Load estimates vary between sources.** One assumes 3M drivers at 1 update per 4 s, about 750K writes/s; another assumes 1M drivers, about 250K writes/s. These are illustrative only. — [techinterview.org](https://www.techinterview.org/post/3233460483/system-design-ride-sharing-uber-lyft/) (secondary)
- **Redis lock on offer (secondary).** A per-driver Redis `SET NX` lock with TTL before offering, released on accept, decline or expiry. — [techinterview.org LLD](https://www.techinterview.org/post/3233472038/lld-rideshare-matching/)
- **Hello Interview acceptance flow.** Accept is a PATCH on the ride, and status is updated on accept (snippet only). — [Hello Interview: Uber](https://www.hellointerview.com/learn/system-design/problem-breakdowns/uber)
- **Contrast with Uber's production experience.** Uber's production experience shows the AP sharded in-memory approach gave up consistency and needed manual repair of failed Sagas. — [Uber: Fulfillment Platform Re-architecture](https://www.uber.com/en-CA/blog/fulfillment-platform-rearchitecture/)
- **Contrast on push (RAMEN).** Interview designs often say "use WebSockets" for push, but Uber's production evolution was SSE, then gRPC over QUIC, driven by ack semantics. — [Uber: Real-time push platform](https://www.uber.com/ae/en/blog/real-time-push-platform/); [Uber: gRPC push](https://eng.uber.com/blog/ubers-next-gen-push-platform-on-grpc/)

### Inferences (known simplifications and mistakes to flag)
1. **TTL lock as sole guard.** If the TTL is shorter than the offer window plus processing time, a second offer can slip in. If it is longer, or the release fails, the driver is stuck. The TTL should be derived from the offer timeout, and the final accept must be a conditional write in the database. (The TTL values in secondary sources differ: 20 s versus 30 s.)
2. **Redis GEO as truth.** It is fine for candidate search but stale. Availability must be re-checked transactionally.
3. **Payments bolted on synchronously.** Real systems use idempotency keys, plus an outbox or workflow, plus asynchronous capture.
4. **"WebSocket solves push."** It ignores app backgrounding, acks, deadlines and resync after reconnect.
5. **Microservices from day one.** Over-decomposition adds network hops (see B3).

### Gaps
- Could not access the full text of Hello Interview, ByteByteGo, or Alex Xu's *System Design Interview* chapters, so their exact recommended designs and self-declared simplifications are not cited here.

## B2. Open-source stacks/projects and a practical evolution path for a small team

### Takeaway
No mature, widely adopted open-source ride-hailing platform turned up. What exists are clones and proofs of concept: Node + Socket.io + OSRM, a RabbitMQ microservices demo, and an H3 + OSRM dispatch PoC. The pragmatic small-team stack is assembled from components:
- Postgres/PostGIS as the source of truth, with conditional updates
- optional Redis GEO for hot location data
- WebSocket via a managed realtime service or self-hosted
- OSRM for ETAs
- an outbox table for events
- Temporal or Cadence (or simply a job queue) only for payment/payout workflows

The evolution path starts as a modular monolith (Shopify's model).

### Cited Findings
- **tanim-mishkat/uber-clone.** Socket.io for live ride tracking and captain locations, OSRM/OpenStreetMap for routing and geocoding, JWT auth, MongoDB storage. — [ecosyste.ms: uber-clone](https://awesome.ecosyste.ms/projects/github.com%2Ftanim-mishkat%2Fuber-clone)
- **kibeno7/eMotion.** Microservices ride-hailing backend with WebSocket ride notifications, RabbitMQ between services and an Nginx gateway. — [ecosyste.ms: eMotion](https://awesome.ecosyste.ms/projects/github.com%2Fkibeno7%2FeMotion)
- **kevinmichaelchen/api-dispatch.** Dispatch PoC combining H3 hex indexing with a distance-matrix API (Google Maps or OSRM). — [GitHub: api-dispatch](https://github.com/kevinmichaelchen/api-dispatch)
- **Supabase/PostGIS matching tutorial.** Nearest-driver matching with PostGIS `ST_DWithin` plus "atomic status locking" to prevent races, targeting Supabase. — [Rapid Developers: ride-hailing platform](https://rapidevelopers.com/how-to-build-v0/ride-hailing-platform) (agency tutorial, secondary)
- **Supabase Realtime limits** (official docs; values as surfaced in 2026 search):
  - Free: 200 concurrent connections, 100 msgs/s, 100 joins/s, 20 presence msgs/s.
  - Pro: 500 connections, 500 msgs/s.
  - Pro without spend cap, Team and Enterprise: 10,000 connections, 2,500 msgs/s.
  - Exceeding limits causes disconnects, and sustained overages can lead to suspension.
  - Sources: [Supabase: Realtime limits](https://supabase.com/docs/guides/realtime/limits); [Supabase: Project suspended for exceeding quotas](https://supabase.com/docs/guides/troubleshooting/realtime-project-suspended-for-exceeding-quotas)
- **Shopify's modular monolith.** "Componentization" started in 2017: all code in one deployable, with strictly enforced domain boundaries and component interfaces. Microservices were rejected because every network call adds latency and lowers reliability. Shopify advises new products to start as monoliths and to refactor only once past the "design payoff line." — [Shopify Engineering: Deconstructing the Monolith](https://shopify.engineering/deconstructing-monolith-designing-software-maximizes-developer-productivity); [InfoQ: Shopify modular monolith (2019)](https://www.infoq.com/news/2019/07/shopify-modular-monolith). A Praella blog claims Shopify first moved toward microservices, but this conflicts with Shopify's own account. — [Praella](https://praella.com/blogs/shopify-insights/exploring-shopify-microservices-architecture-a-comprehensive-guide)
- **Lyft's Envoy origin.** Envoy grew out of Lyft's monolith-to-microservices move, which "produced a lot of inconsistencies around our ecosystem." This illustrates that the service split creates new infrastructure needs. — [Gremlin podcast: Jose Nino (Lyft)](https://www.gremlin.com/blog/podcast-break-things-on-purpose-jose-nino-staff-software-engineer-at-lyft)

### Inferences (recommended evolution path, synthesized)
- **Stage 0 (MVP, up to about 1–2K concurrent drivers):**
  - One Postgres (+PostGIS) as the system of record for drivers, trips and payments.
  - A trip state machine enforced by `UPDATE ... WHERE state = expected` (CAS) inside transactions.
  - An idempotency-key table on all mutating APIs.
  - A transactional outbox table polled by a worker, for notifications and PSP calls.
  - Driver locations in Postgres or Redis GEO with TTL.
  - WebSocket via a managed realtime service (mind the Supabase connection caps above) or a single Node/Go gateway.
  - A self-hosted OSRM for ETAs, plus FCM/APNs as a fallback.
- **Stage 1:**
  - Extract the location/gateway tier first, because it is stateful, high-write and separately scalable.
  - Add Debezium CDC to Kafka (or Redpanda/managed Kafka) when more than a couple of consumers need trip events.
  - Introduce Temporal for payment capture, refund and payout flows that span PSPs and timers.
- **Stage 2:**
  - Partition by city or market (Uber's city→region pinning).
  - Move surge and ETA features to stream processing (Flink) only when per-cell windowed aggregates outgrow SQL or Redis jobs.
  - Consider distributed SQL (Spanner, CockroachDB) only if one Postgres primary per market is saturated.

### Gaps
- No well-maintained, production-grade open-source ride-hailing backend found. The repos found appear to be learning projects; maintenance status was not verified because GitHub pages were not fetched.
- Supabase dollar pricing and Temporal Cloud pricing were not retrieved.

## B3. Cost and operational-complexity considerations for small teams

### Takeaway
The operational and cost evidence points one way: even Uber pays about 2x capacity for active-active and runs about 30 Cadence clusters. Kafka at Grab needed hours-long partition reassignments before a re-platform. Shopify argues each service boundary adds latency and failure modes. A small team should buy managed Postgres and managed realtime, avoid self-hosting Kafka, Flink and Cadence early, and use outbox plus idempotency to get most of the reliability benefits.

### Cited Findings
- **Active-active cost at Uber.** Each region is provisioned at 2x peak, with utilization around 20–30%. — [arXiv 2603.07345](https://arxiv.org/pdf/2603.07345)
- **Cadence fleet at Uber.** About 30 Cadence clusters, multitenant with hundreds of domains each, and noisy-neighbour hot-shard issues requiring workflow-ID rate limits. — [Cadence 2024 roadmap](https://cadenceworkflow.io/blog/2024/07/11/2024-07-11-yearly-roadmap-update/yearly-roadmap-update); [Cadence rate limits post](https://cadenceworkflow.io/blog/2024/09/05/workflow-specific-rate-limits)
- **Kafka operations at Grab.** Partition reassignment took more than 6 hours before migrating to AutoMQ (vendor claim). — [AutoMQ](https://www.automq.com/blog/how-grab-uses-automq-solve-kafka-challenges)
- **Cost of decomposition.** Microservice decomposition adds network latency and reduces reliability with every call. — [Shopify Engineering](https://shopify.engineering/deconstructing-monolith-designing-software-maximizes-developer-productivity)
- **Managed realtime caps.** Managed realtime has hard per-plan connection and message caps, for example 10K connections and 2,500 msgs/s at Supabase's top self-serve tiers. — [Supabase Realtime limits](https://supabase.com/docs/guides/realtime/limits)
- **Polling cost.** Polling is data- and battery-expensive on mobile, which is why Gojek moved to persistent MQTT. — [Gojek: Courier](https://blog.gojek.io/courier-library-for-gojeks-information-superhighway)

### Inferences
- As a rough sizing check, location writes at 1 update per 4 s per driver mean 1,000 online drivers produce about 250 writes/s. That is comfortably within a single Postgres or Redis instance and a single gateway, and within managed-realtime tiers. Kafka/Flink-scale infrastructure is unjustified until tens of thousands of concurrent drivers.
- The biggest correctness risks for a small app are cheap to fix: double-assignment (fix with CAS), duplicate charges (idempotency keys at the PSP and API), and lost side effects (outbox). Fix these before any scaling work.

### Gaps
- No quantitative TCO comparison (managed vs self-hosted Kafka, Temporal Cloud vs self-hosted) was found within the tool budget.
