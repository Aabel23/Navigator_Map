# Architecture Styles in Ride-Hailing Backends (Uber, Grab, Lyft, Gojek, DiDi, Bolt): Evolution, Trade-offs, 2024-2026 Trends

> Method note: research done 2026-10-13. Direct page fetching (WebFetch/curl) was blocked in this environment (DNS/proxy 403 for uber.com, infoq.com, engineering.grab.com), so findings come from search-engine extracts of the cited pages, not full reads. Figures are quoted as surfaced in those extracts. Where only a secondary source was available, that is flagged.

## 1. How did Uber evolve (monolith -> thousands of microservices -> DOMA -> Up/cloud, zonal/failover)?

### Takeaway
Uber went from a monolith to a Node.js-based, application-sharded real-time dispatch system (Ringpop + Google S2, ~2015), then to thousands of microservices (~2,200 "critical" ones by 2020), which it re-organized (not consolidated) into ~70 domains under DOMA (2020). Later changes were mostly at the platform and data layer: the Fulfillment Platform rewrite onto Google Cloud Spanner (2021), the Up multi-cloud deployment platform (4,500 stateless services, about 2M cores, 2023), Mesos -> Kubernetes, and resilience work at the zone and region level (zonal isolation, a tiered failover architecture published 2026). I found no public Uber post that calls its design "cell-based".

### Cited Findings
**Early dispatch / real-time platform (2015)**
- At QCon London 2015, Matt Ranney ("Scaling Uber's Real-time Market Platform") covered dispatch, the geospatial index, datacenter failure handling and the "distributed traveling salesman" problem — [InfoQ presentation](https://www.infoq.com/presentations/uber-market-platform/); [InfoQ news 2015](https://www.infoq.com/news/2015/03/uber-realtime-market-platform)
- Dispatch was built on Node.js. To scale a *stateful* service, Uber used Ringpop, a consistent hash ring with gossip (SWIM) membership that shards at the application layer. This is effectively an actor/sharded-state model built without an actor framework — [High Scalability](https://highscalability.com/how-uber-scales-their-real-time-market-platform/); [Ringpop slides](https://speakerdeck.com/basho/ringpop-by-uber)
- Location data was sharded with Google S2 cells. S2 lets you choose cell resolution and find the cells that cover an area, and matching uses that coverage around the rider's location to find candidate drivers — [InfoQ news 2015](https://www.infoq.com/news/2015/03/uber-realtime-market-platform)
- The supply service tracked every state of all supply and ran on "hundreds of processes". The dispatch system was called "DISCO" (dispatch optimization), per the secondary High Scalability writeup — [High Scalability](https://highscalability.com/how-uber-scales-their-real-time-market-platform/)

**DOMA (July 2020)**
- "Introducing Domain-Oriented Microservice Architecture", by Adam Gluck, July 23, 2020: "As Uber has grown to around 2,200 critical microservices, we experienced these tradeoffs first hand" — [Uber Blog](https://www.uber.com/us/en/blog/microservice-architecture/); [Uber Eng tweet](https://x.com/ubereng/status/1286330797876641792)
- DOMA's goal is to "reduce overall system complexity while keeping the flexibility that microservices offer". It does this through a systematic architecture, domain gateways and predefined extension points, organized as reusable layered components — [Uber Blog](https://www.uber.com/us/en/blog/microservice-architecture/)
- Core concepts:
  - **Domain**: one or more microservices that make up a logical grouping of functionality. The post gives no rule for domain size.
  - **Layers**: the domain's layer sets which dependencies it may take.
  - **Gateways**: a single point of entry into a domain.
  - **Extensions**: let other teams add logic without changing the core domain.
  — [Uber Blog](https://www.uber.com/us/en/blog/microservice-architecture/); [Shaun Abram summary](https://www.shaunabram.com/blog-post-summary-domain-oriented-microservice-architecture-at-uber/)
- Results: 2,200 microservices were classified into 70 domains, and about 50% of those domains had been implemented at the time of writing. Platforms cut the onboarding time for a new feature or line of business by 25-50% by reducing touchpoints. Most adopting teams were motivated by how expensive it had become to support new lines of business — [Uber Blog](https://www.uber.com/us/en/blog/microservice-architecture/)
- (Secondary, unverified) claims that Uber's microservices had a "1.5-year half-life" and that one feature needed 60+ engineers come from a personal blog, not Uber — [sujeet.pro](https://sujeet.pro/articles/uber-microservices-journey)

**Fulfillment Platform rewrite (2021)**
- Uber rebuilt its Fulfillment Platform from the ground up for its "Go/Get" strategy. It chose Google Cloud Spanner (multi-region "nam3") as primary storage after benchmarking NewSQL options. The old design favored availability and latency with best-effort consistency, and Cassandra's last-write-wins could lose concurrent writes during split-brain events such as deploys and region failovers. Uber also built "LATE", a transactional outbox-style component for post-commit actions with at-least-once execution. The post is dated Sep 29, 2021 — [Uber Blog: Fulfillment rearchitecture](https://www.uber.com/kw/en/blog/fulfillment-platform-rearchitecture/); [Uber Blog: Building Fulfillment on Spanner](https://www.uber.com/us/en/blog/building-ubers-fulfillment-platform/); [InfoQ 2021](https://www.infoq.com/news/2021/08/uber-rearchitecture)
- InfoQ reports the system handles more than 2 million transactions per second. That is a database transaction rate, not trips — [InfoQ article](https://www.infoq.com/articles/uber-migration-hybrid-cloud/)

**Up platform / cloud (2018-2023+)**
- Up was started in 2018 as a multi-cloud, multi-tenant federation control plane. It automates service placement into availability zones, including re-placement as new zones come online, and infrastructure migrations, with no action needed from service owners — [Uber Blog: Up](https://www.uber.com/us/en/blog/up-portable-microservices-ready-for-the-cloud/); [InfoQ 2023](https://www.infoq.com/news/2023/10/uber-up-cloud-microservices/)
- About 4,500 stateless services and about 2,000,000 compute cores moved from µDeploy to Up, ahead of moving a large share of compute to the cloud. Uber announced Oracle and Google Cloud partnerships on Feb 13, 2023 — [The Stack](https://www.thestack.technology/uber-migrates-to-new-multi-cloud-platform/); [InfoQ 2023](https://www.infoq.com/news/2023/10/uber-up-cloud-microservices/)
- Mesos was deprecated at Uber in 2021, and Up's clusters were migrated to Kubernetes — [Uber Blog: K8s migration](https://www.uber.com/en-TR/blog/migrating-ubers-compute-platform-to-kubernetes-a-technical-journey/)
- In 2025 InfoQ covered Uber's adoption of Arm in the cloud — [InfoQ 2025](https://www.infoq.com/news/2025/02/uber-arm-cloud)

**Zone/region resilience (2023-2026)**
- Uber long ran dual-region active-active, with each region able to absorb 100% of global traffic. That roughly doubled steady-state capacity. A 2026 paper (NSDI '26 / arXiv 2603.07345) describes a tiered failover architecture: critical dependencies are strictly isolated, and non-critical work is shed automatically and can use failover buffers in steady state. The reported provisioning drop from 2x to 1.3x (about a quarter of compute saved) comes from a third-party summary of the paper — [USENIX NSDI'26 PDF](https://www.usenix.org/system/files/nsdi26-bansal.pdf); [arXiv](https://arxiv.org/html/2603.07345v2)
- Zonal isolation for Cadence aimed to survive the loss of one zone without a cross-region failover. It launched in July 2023, and the rollout was paused in 2024 because of traffic skew between zones — [Cadence blog](https://cadenceworkflow.io/blog/zonal-isolation-v1/zonal-isolation-v1)
- The compute platform runs active-active data centers across regions and fails traffic over to another region during outages — [Uber Blog: compute platform](https://www.uber.com/np/en/blog/evolving-ubers-compute-platform/). Multi-region Kafka uses active/active and active/passive consumer modes for disaster recovery (about 2020) — [Uber Blog: Kafka DR](https://www.uber.com/us/en/blog/kafka/)

### Inferences
- DOMA is a governance and organization layer on top of microservices, not a consolidation. Service count stayed in the thousands (about 2,200 critical services in 2020, about 4,500 stateless services in 2023). What it reduced is *coupling* and *touchpoints*.
- The strongest pressure at Uber since 2021 is on the data and resilience layers, not on service style: strong consistency (Spanner), cost-efficient failover (going from 2x toward about 1.3x capacity), and zone-level isolation. In effect this is "cell-like" bulkheading at zone and region granularity, even though Uber does not use the word "cell".
- Real-time dispatch at Uber has always relied on sharded in-memory state (Ringpop + S2). This is the same idea behind actor models (Orleans/Akka): route by key to the node that owns the state.

### Gaps
- I could not read the full DOMA post to extract exact layer names. Commonly cited: Infrastructure, Business, Product, Presentation, Edge.
- No primary 2024-2026 Uber post explicitly describing a "cell-based architecture" for city or geo partitions was found.
- Current (2025-2026) total microservice count at Uber was not found. The latest figure is about 4,500 stateless services (2023).

## 2. How did Grab, Gojek, Lyft, DiDi and Bolt evolve?

### Takeaway
Grab moved from Rails + Node.js to Go services, using a zero-downtime proxy migration. It then standardized on Grab-Kit (Go-Kit plus code generation) and today keeps most services in a Go monorepo, with selective Rust rewrites. Lyft broke up a PHP monolith (top company priority in 2018), reached 300+ services, and invented Envoy, which became the service-mesh standard. Its later problems were developer productivity and testing (Onebox did not scale), not re-consolidation. Gojek went to microservices early. Bolt says it runs a microservice architecture handling hundreds of thousands of requests per second. DiDi has no accessible English primary sources.

### Cited Findings
**Grab**
- Grab moved from a Rails + NodeJS stack to "a full Golang Service Oriented Architecture". Passenger-app APIs were migrated with zero downtime, using a thin Go proxy in front of the Rails clone. The post is roughly 10 years old (about 2015-2016) — [Grab Eng: zero-downtime migration](https://engineering.grab.com/zero-downtime-migration)
- Grab-Kit was built by the Developer Experience team as Grab moved "from a single monolithic application to a microservices-based architecture". It is based on Go-Kit but auto-generates server and client boilerplate from .proto files. It standardizes library initialization, context propagation, inter-service communication, dashboards and alarms, and DAOs — [Grab Eng: Introducing Grab-Kit](https://engineering.grab.com/introducing-grab-kit)
- (Secondary) After the split, every team built services differently, with inconsistent log formats and missing alerts. Grab-Kit made the standard setup automatic — [migration case summary](https://migrations.sepurisaikrishna.com/migrations/grab-monolith-to-grab-kit-microservices/)
- In 2025 Grab said it is "predominantly based on a microservice architecture, with the vast majority of microservices being hosted in a monorepo and written in Golang". Grab rewrote its high-QPS Counter Service from Go to Rust and reported about 70% infrastructure savings. At 1,000 QPS, Go used about 20 cores versus about 4.5 for Rust — [Grab Eng: Counter Service in Rust](https://engineering.grab.com/counter-service-how-we-rewrote-it-in-rust); [ByteByteGo](https://blog.bytebytego.com/p/how-grabs-migration-from-go-to-rust)
- Grab also built a shared Quotas (rate-limiting) microservice as part of a company-wide initiative on common microservice problems. Its consumer superapp started as a mobile monolith and was later modularized (client-side) — [Grab Eng: app modularisation](https://engineering.grab.com/app-modularisation-at-scale); [Grab Eng: DDD in Golang](https://engineering.grab.com/domain-driven-development-in-golang)

**Lyft**
- When Matt Klein joined in May 2015, Lyft was already moving from a monolith to microservices, with 30+ services. Developers were unwilling to move critical functionality out of the monolith because the new infrastructure seemed unstable and failures were hard to debug. Envoy started as an edge proxy replacing load balancers and HAProxy, for observability, load balancing and access logs. Klein calls this the start of Lyft's service mesh. Envoy became CNCF's 11th hosted project — [Lyft Eng: Envoy joins CNCF](https://eng.lyft.com/envoy-joins-the-cncf-dc18baefbc22); [Gravitee recap of Klein talk](https://www.gravitee.io/blog/mechanics-deploying-envoy-lyft-matt-klein); [QCon NY 2018](https://archive.qconnewyork.com/node/49926)
- A 2019 Velocity talk covered the move from a legacy monolith to more than 300 microservices — [O'Reilly Velocity 2019](https://conferences.oreilly.com/velocity/vl-ca/public/schedule/detail/75057)
- In 2018, "the number one company priority was the decomposition of the PHP monolith to microservices", described as the largest refactoring in Lyft's 10-year history. Lyft had 2000+ repositories, i.e., polyrepo — [Sourcegraph case study](https://sourcegraph.com/case-studies/lyft-monolith-to-microservices)
- The "Scaling productivity on microservices at Lyft" series (Part 1 late 2021, Part 4 2022) reports that an "explosion in the number of services and engineers" made the Onebox per-developer environments slow and eventually unscalable. Lyft responded with shared-staging request isolation ("staging overrides", 100+ services onboarded in the first few months) and moved from per-service integration tests to a small centralized set of acceptance tests — [Lyft Eng Part 4](https://eng.lyft.com/scaling-productivity-on-microservices-at-lyft-part-4-gating-deploys-with-automated-acceptance-4417e0ebc274); [InfoQ 2022](https://www.infoq.com/news/2022/03/scaling-testing-acceptance-lyft/); [Lyft Eng: control plane for shared dev env](https://eng.lyft.com/building-a-control-plane-for-lyfts-shared-development-environment-6a40266fcf5e)
- LyftLearn Serving generates fully independent microservices per team, each with its own repo, pipeline and runtime config. The direction is still toward more services, not fewer — [ZenML summary](https://www.zenml.io/mlops-database/lyft-lyftlearn-lyftlearn-serving-decentralized-microservice-model-serving-for-hundreds-of-millions-of-real-time-predicti)

**Gojek**
- Gojek adopted microservices early and evaluated Ruby, Java and Golang for them — [Gojek Eng: Ruby? Java? Golang?](https://medium.com/gojekengineering/ruby-java-golang-59713bdd9fc4)
- Gojek enforces service-to-service communication restrictions that are verified on every call — [Gojek blog: microservices communication at scale](https://www.gojek.io/blog/how-go-jek-handles-microservices-communication-at-scale)
- (Secondary, unverified) Gojek started as monoliths, drew service boundaries by access frequency rather than function, and ran on GCP with PostgreSQL, Kafka and edge proxies — [SpectreDev](https://www.spectredev.xyz/engineering/digital-transformation/how-indonesian-unicorns-scaled-architecture)

**Bolt**
- Bolt's backend APIs "service hundreds of thousands of requests per second", and "our microservice architecture and clever routing helps us scale". The post (about 2020-2021) describes supporting 50M+ customers across ride-hailing, rentals and food — [Bolt Labs](https://medium.com/bolt-labs/supporting-50-million-customers-hello-from-the-bolt-engineering-team-695f8bc3dfab)

**DiDi**
- No DiDi-authored English architecture source was found. General results were patents and academic papers not attributable to DiDi.

### Inferences
- A common pattern: a Rails, PHP or Node monolith, then a language shift (Go at Grab, Go and Java at Gojek), then a proliferation of microservices, then a second wave of investment in *standardization*. That second wave took the form of Grab-Kit (frameworks and codegen), Envoy (service mesh), DOMA (domains and gateways) and test and staging isolation at Lyft. The "regret" these companies faced was operational inconsistency and productivity loss, which they solved with platforms rather than by going back to a monolith.
- Grab pairs a monorepo with microservices, which shows that repository topology and deployment topology are separate decisions.

### Gaps
- Grab cell/zone architecture or a dispatch-platform architecture writeup: not found in search, and the Grab blog could not be fetched directly.
- Grab, Gojek and Bolt microservice counts: not found.
- DiDi: no accessible primary sources (likely Chinese-language only). Ola: not researched or nothing found.
- No evidence was found that Lyft publicly consolidated services in 2023-2025.

## 3. Cell-based architecture: definition, who uses it, fit for geo-partitioned ride-hailing

### Takeaway
A cell is a full, independent copy of a workload's stack: compute, storage and supporting services. Traffic is routed to a cell by a partition key through a thin router, so a failure only affects that cell's share of traffic. AWS, Slack and DoorDash document it publicly. Ride-hailing's natural "grain" is the city or geo region, which makes it an intuitive fit. However, I found no primary source showing Uber or Grab use cells by city. Uber's public work is at zone and region granularity instead.

### Cited Findings
- AWS Well-Architected whitepaper "Reducing the Scope of Impact with Cell-Based Architecture":
  - Partition keys must "match the grain of the service" (e.g., customer ID or resource ID) and should be easily available in most API calls. Very large tenants need plans to split across cells.
  - Cross-cell (scatter-gather) calls should be rare and should go back through the cell router rather than cell-to-cell.
  - The router is shared, so it must stay simple, horizontally scalable and free of business logic. Hashing plus modular arithmetic is suggested for mapping keys to cells.
  - Mapping state must be distributed, and keys must be migrated when cells are added or removed.
  — [AWS whitepaper PDF](https://docs.aws.amazon.com/pdfs/wellarchitected/latest/reducing-scope-of-impact-with-cell-based-architecture/reducing-scope-of-impact-with-cell-based-architecture.pdf); [Cell partition](https://docs.aws.amazon.com/wellarchitected/latest/reducing-scope-of-impact-with-cell-based-architecture/cell-partition.html); [Cell routing](https://docs.aws.amazon.com/wellarchitected/latest/reducing-scope-of-impact-with-cell-based-architecture/cell-routing.html); [REL10-BP03 bulkheads](https://docs.aws.amazon.com/wellarchitected/latest/reliability-pillar/rel_fault_isolation_use_bulkhead.html)
- DoorDash (Jan 2024) adopted cells to cut cross-AZ data-transfer costs as microservices multiplied. Each cell is several Kubernetes clusters, with each service deployed to exactly one cluster per cell, plus zone-aware routing in an Envoy-based mesh to keep traffic within one AZ — [InfoQ: DoorDash service mesh](https://infoq.com/news/2024/01/doordash-service-mesh)
- Slack moved most user-critical services to cells after AWS networking failures degraded service across AZs, and uses cells to mitigate "grey failures" (secondary summary) — [Mad Devs summary](https://maddevs.io/blog/cell-based-architecture-vs-microservices)
- Limits: shared dependencies such as global DBs, external APIs and cross-cell caches still correlate failures across cells — [Mayank Raj blog](https://mayankraj.com/blog/cell-based-architecture-blast-radius-containment/)
- Uber's closest equivalents are Up placing services into AZs, zonal isolation for Cadence (paused 2024 due to zone traffic skew) and tiered region failover — see Section 1 — [Uber Blog: Up](https://www.uber.com/us/en/blog/up-portable-microservices-ready-for-the-cloud/); [Cadence blog](https://cadenceworkflow.io/blog/zonal-isolation-v1/zonal-isolation-v1); [NSDI'26](https://www.usenix.org/system/files/nsdi26-bansal.pdf)

### Inferences
- Pros for ride-hailing:
  - Matching, pricing and trip state are mostly local to a city or geo-region, so few cross-cell calls are needed.
  - A bad deploy or overload stays within one market or zone.
  - Deploys can roll out cell by cell.
  - Data residency is easier to meet.
- Cons:
  - Cross-city or global functions (accounts, payments, airports or borders, global ML) cut across cells.
  - Very unequal cell sizes (megacities vs small towns) mirror the AWS "large customer" problem.
  - Cells duplicate capacity and add router and migration complexity.
  - Uber's Cadence experience shows that traffic skew between partitions can stall isolation rollouts.
- Cells are orthogonal to microservices. Each cell can contain many microservices, so cells add a deployment and blast-radius dimension on top of service decomposition.

### Gaps
- No primary evidence was found of city-level cells at Uber, Grab, Lyft, Gojek or Bolt. The Slack primary post was not fetched.

## 4. Microservice consolidation / "regret": evidence and lessons

### Takeaway
High-profile consolidations exist: Prime Video's monitoring component cut cost by more than 90%, and Segment went from 140+ services to one, Centrifuge. In both cases a narrow, data-heavy pipeline was paying a high per-hop cost. Ride-hailing leaders did not go back to monoliths. They responded to microservice sprawl with domain grouping (DOMA), standard frameworks (Grab-Kit) and mesh and test infrastructure (Envoy, Lyft staging overrides).

### Cited Findings
- Prime Video's Video Quality Analysis team (2023) moved its monitoring service to a monolith and reported infrastructure cost cut by more than 90%. The cost drivers were AWS Step Functions orchestration and passing video frames between services through S3. The new design keeps data in memory, and the rest of Prime Video still uses microservices — [The Stack](https://www.thestack.technology/amazon-prime-video-microservices-monolith/); [ByteByteGo guide](https://bytebytego.com/guides/amazon-prime-video-monitoring-service/)
- Segment split event routing into 140+ per-destination services, then consolidated them into a single service, "Centrifuge". This is from a secondary source. The original "Goodbye Microservices" post (believed 2018) was not verified here — [byteiota](https://byteiota.com/microservices-regret-amazon-saved-90-segment-went-from-140-to-1/)
- Commentary: neither case condemns microservices in general. Some authors propose rough thresholds for when microservices pay off (e.g., 50+ developers), but these are opinion — [byteiota 2025](https://byteiota.com/monolith-vs-microservices-2025-when-amazon-cuts-costs-90/); [Java Code Geeks 2026](https://www.javacodegeeks.com/2026/02/the-death-of-microservices-hype-when-modular-monoliths-win.html)
- Ride-hailing counter-evidence (no consolidation): Uber kept thousands of services and grouped them into 70 domains, reporting 25-50% faster onboarding — [Uber Blog DOMA](https://www.uber.com/us/en/blog/microservice-architecture/). Lyft fixed testing and staging rather than service count — [InfoQ 2022](https://www.infoq.com/news/2022/03/scaling-testing-acceptance-lyft/). Grab standardized with Grab-Kit and kept a Go monorepo — [Grab Eng](https://engineering.grab.com/introducing-grab-kit)

### Inferences
- Lessons for a ride-hailing design:
  1. Hot data paths such as location ingest, matching and pricing suffer from per-hop serialization, as Prime Video did. Keep tightly coupled hot loops in one process or one sharded stateful service, as Uber did with Ringpop.
  2. Organizational scale (hundreds of teams, several lines of business) is the real reason for microservices, and it brings a need for domain boundaries and platform standardization.
  3. A modular monolith is a reasonable starting point for a new or small-scale ride-hailing system. Most leaders started from monoliths and split under team and scale pressure.

### Gaps
- Primary texts for Prime Video (2023) and Segment (2018) were not fetched.
- The Martin Fowler ("MonolithFirst") and Sam Newman modular-monolith sources were not retrieved within the tool budget, so they cannot be cited from this research.

## 5. Quantitative data summary (services, request rates, team sizes, latency)

### Takeaway
The hard numbers available are mostly Uber's. Grab, Bolt and Lyft give only rough magnitudes. No primary latency budgets were found.

### Cited Findings
| Company | Metric | Value | Date | Source |
|---|---|---|---|---|
| Uber | Critical microservices | ~2,200, grouped into 70 domains (~50% implemented) | Jul 2020 | [Uber Blog DOMA](https://www.uber.com/us/en/blog/microservice-architecture/) |
| Uber | Onboarding-time reduction from DOMA | 25-50% | 2020 | [Uber Blog DOMA](https://www.uber.com/us/en/blog/microservice-architecture/) |
| Uber | Stateless services migrated to Up | ~4,500; ~2M cores | 2023 | [The Stack](https://www.thestack.technology/uber-migrates-to-new-multi-cloud-platform/); [InfoQ](https://www.infoq.com/news/2023/10/uber-up-cloud-microservices/) |
| Uber | Fulfillment DB transactions | >2M TPS (InfoQ); "billions of transactions/day" | 2021+ | [InfoQ](https://www.infoq.com/articles/uber-migration-hybrid-cloud/); [Uber Blog](https://www.uber.com/us/en/blog/building-ubers-fulfillment-platform/) |
| Uber | Failover capacity overhead | 2x (dual active-active) -> ~1.3x (secondary summary) | 2026 paper | [NSDI'26](https://www.usenix.org/system/files/nsdi26-bansal.pdf) |
| Lyft | Services | 30+ (2015) -> 300+ (2019) | 2015-2019 | [Gravitee/Klein](https://www.gravitee.io/blog/mechanics-deploying-envoy-lyft-matt-klein); [O'Reilly](https://conferences.oreilly.com/velocity/vl-ca/public/schedule/detail/75057) |
| Lyft | Repositories | 2000+ | ~2018+ | [Sourcegraph](https://sourcegraph.com/case-studies/lyft-monolith-to-microservices) |
| Bolt | Backend API load | hundreds of thousands req/s; 50M+ customers | ~2020-21 | [Bolt Labs](https://medium.com/bolt-labs/supporting-50-million-customers-hello-from-the-bolt-engineering-team-695f8bc3dfab) |
| Grab | Counter Service Go vs Rust at 1k QPS | ~20 vs ~4.5 cores; ~70% infra saving | 2025 | [Grab Eng](https://engineering.grab.com/counter-service-how-we-rewrote-it-in-rust) |

### Inferences
- Service count grows with organization size: tens of services in early years, hundreds at Lyft, thousands at Uber. This suggests architecture style follows team topology (Conway's law) more than traffic.

### Gaps
- Latency budgets for dispatch and matching were not found from primary sources.
- Team sizes and engineer counts per company were not found.
- No primary source was found for the actor model (Orleans/Akka) in ride-hailing beyond Uber's Ringpop sharded-state approach.
- No primary source was found for edge computing in ride-hailing backends.
