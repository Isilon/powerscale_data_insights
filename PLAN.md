# PowerScale Data Insights - Project Plan

## Overview

**PowerScale Data Insights** is the successor to the Isilon Data Insights Connector.
It consolidates the Go-based statistics collectors (gostats, goppstats), the
Partitioned Performance dashboard generator (dashgen), and modernized Grafana
dashboards into a single, well-documented project.

**Repository:** `github.com/Isilon/powerscale_data_insights`

> **Note on casing:** The GitHub organization is canonically `Isilon`
> (capital I). However, Go module paths are case-sensitive and Go convention
> is all-lowercase. All `go.mod` module paths should use lowercase:
> `github.com/isilon/powerscale_data_insights/...`. GitHub resolves
> lowercase URLs correctly, and the Go toolchain lowercases paths for
> module storage regardless.

### What's New in v2

- **Python code dropped entirely** — Go collectors only
- **OneFS 9.x+ minimum** — simplifies codebase, enables PP datasets and summary stats
- **Shared library** — common code extracted from gostats/goppstats into internal packages
- **Modernized dashboards** — all dashboards rewritten to Grafana v2beta1 (Grafana 12.x)
- **InfluxQL dashboards** — work against both InfluxDB v1 and v2
- **dashgen included** — automatic Partitioned Performance dashboard generation
- **Container images** — published to GitHub Container Registry
- **Docker Compose** — full evaluation stack (collectors + InfluxDB + Grafana)
- **Comprehensive documentation** — architecture, getting started, configuration, deployment

### What's Carried Forward

- gostats collector (all backends: InfluxDB v1/v2, Prometheus)
- goppstats collector (all backends)
- dashgen for PP dashboard generation
- Cross-platform binary releases via GoReleaser

### What's Dropped

- Python collector and all Python dependencies
- OneFS 7.2/8.0 SDK support
- Derived stats system (composite, equation, percent change)
- HDFS-specific dashboards
- Kapacitor integration

---

## Decisions Log

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Project name | `powerscale_data_insights` | Forward-looking PowerScale branding, avoids confusion with old `isilon_data_insights_connector` |
| Repository | New repo under `github.com/Isilon/` | Clean break from legacy repo |
| Project structure | Monorepo with shared library | Eliminates code duplication between gostats/goppstats |
| Minimum OneFS | 9.x+ | Required for PP datasets (PAPI v10), summary stats; simplifies code |
| Dashboard format | Grafana v2beta1 (Grafana 12.x) | Modern schema, matches dashgen output |
| Dashboard queries | InfluxQL | Works against both InfluxDB v1 and v2; Flux is deprecated |
| Primary TSDB | InfluxDB (v1/v2 via InfluxQL) | Prometheus dashboards are backlog |
| Derived stats | Dropped | Grafana can do aggregation/math at query time |
| Deployment | Binaries + container images + Docker Compose | Three tiers: bare metal, containers, evaluation stack |

---

## Repository Structure

```
powerscale_data_insights/
├── README.md                          # Overview, architecture, quickstart
├── LICENSE                            # MIT
├── AGENTS.md                          # AI assistant / contributor guidance
├── go.work                            # Go workspace
├── go.work.sum
├── Makefile                           # Top-level: build all, test all, lint
├── .goreleaser.yaml                   # Multi-binary release config
├── .github/
│   └── workflows/
│       ├── ci.yml                     # Build + test on push/PR
│       └── release.yml                # GoReleaser + Docker build/push on tag
│
├── cmd/
│   ├── gostats/                       # Statistics collector
│   │   ├── go.mod
│   │   ├── main.go
│   │   └── ...                        # Collector-specific logic
│   ├── goppstats/                     # Partitioned Performance collector
│   │   ├── go.mod
│   │   ├── main.go
│   │   └── ...                        # PP-specific logic
│   └── dashgen/                       # Dashboard generator
│       ├── go.mod
│       ├── main.go
│       └── ...
│
├── internal/                          # Shared internal packages
│   ├── api/                           # OneFS PAPI client
│   │   ├── client.go                  # HTTP client, TLS, retry
│   │   ├── auth.go                    # Session + basic-auth
│   │   └── cluster.go                 # Cluster info, version detection
│   ├── backend/                       # TSDB backend implementations
│   │   ├── backend.go                 # Common types (Point, tags, fields)
│   │   ├── influxdb.go               # InfluxDB v1
│   │   ├── influxdbv2.go             # InfluxDB v2
│   │   ├── prometheus.go             # Prometheus
│   │   └── discard.go                # No-op (testing)
│   ├── config/                        # Configuration
│   │   ├── config.go                  # TOML parsing, env var substitution
│   │   └── watcher.go                # File watcher + SIGHUP reload
│   ├── logging/                       # Logging
│   │   └── logging.go                # slog setup, custom levels
│   └── platform/                      # Platform-specific
│       ├── signal_unix.go
│       ├── signal_windows.go
│       ├── control_unix.go
│       └── control_windows.go
│
├── dashboards/                        # Pre-built Grafana dashboards
│   └── influxdb/                      # InfluxQL (works with v1 and v2)
│       ├── cluster_list.json          # Multi-cluster overview
│       ├── cluster_detail.json        # Single cluster deep dive
│       ├── cluster_capacity.json      # Storage utilization
│       ├── cluster_protocol.json      # Per-protocol stats
│       ├── drive_stats.json           # Drive statistics (from interim work)
│       └── ...                        # Additional interim dashboards (3-5 total)
│
├── configs/                           # Example configuration files
│   ├── gostats.example.toml
│   └── goppstats.example.toml
│
├── docker/
│   ├── Dockerfile.gostats             # Multi-stage build (~15-20MB image)
│   ├── Dockerfile.goppstats           # Multi-stage build
│   ├── docker-compose.yml             # Full stack for evaluation
│   └── grafana/
│       └── provisioning/
│           ├── datasources/
│           │   └── influxdb.yml       # Auto-configured datasource
│           └── dashboards/
│               └── dashboards.yml     # Auto-provisioned dashboards
│
├── docs/
│   ├── architecture.md                # Component diagram, data flow
│   ├── getting-started.md             # End-to-end setup guide
│   ├── configuration.md               # Complete TOML reference
│   ├── dashboards.md                  # Dashboard guide + using dashgen
│   ├── deployment.md                  # Binary, Docker, Kubernetes
│   ├── onefs-setup.md                 # OneFS user creation, privileges
│   └── migrating-from-v1.md          # Migration guide from Python connector
│
└── papi/                              # PAPI schema reference
    └── 9.11/
```

---

## Phases

### Phase 1: Repository Scaffolding & Code Migration — COMPLETE

**Goal:** Establish the monorepo, move existing code in, verify everything
builds and tests pass. Zero logic changes.

**Tasks:**

1. Create the directory structure above
2. Copy gostats source into `cmd/gostats/` (package main, as-is)
3. Copy goppstats source into `cmd/goppstats/` (package main, as-is)
4. Copy dashgen source into `cmd/dashgen/` (package main, as-is)
5. Create `go.work` workspace pointing to all three modules
6. Create top-level `Makefile` with targets: `build`, `test`, `lint`, `clean`
7. Copy PAPI schema docs into `papi/`
8. Copy example config files into `configs/`
9. Verify: all three binaries build, all tests pass
10. Set up GitHub Actions CI (build + test for all three modules)
11. Initial `README.md` with project overview
12. Initial `AGENTS.md` with build/test commands and architecture notes

**Exit criteria:** `make build && make test` succeeds. Three binaries produced.

---

### Phase 2: Shared Library Extraction — COMPLETE

**Goal:** Extract duplicated code from gostats/goppstats into `internal/`
packages. Eliminate copy-paste maintenance burden.

**Extraction order** (least to most complex):

1. **`internal/logging`** — slog setup, custom levels (TRACE through FATAL),
   multi-handler fanout. Nearly identical between both collectors.

2. **`internal/platform`** — Signal handling (SIGHUP), socket options
   (SO_REUSEADDR/SO_REUSEPORT). Identical between both collectors.

3. **`internal/config`** — TOML parsing primitives, `secretFromEnv()` for
   `$env:VAR` substitution, config file watcher with debounce. The top-level
   config structs differ between collectors but the machinery is shared.

4. **`internal/api`** — OneFS PAPI HTTP client: session auth, basic auth, TLS
   config, retry with exponential backoff, cluster info fetching. Both
   collectors use the same auth flow and HTTP patterns but call different
   endpoints. Extract the client/auth layer; collectors provide their own
   endpoint-specific methods.

5. **`internal/backend`** — Unified backend with shared Point abstraction:
   - Shared types: `Point` (exported), `Fields` (map[string]any), `Tags` (map[string]string)
   - Shared `DBWriter` interface: `WritePoints(ctx, []Point) error`
   - Shared implementations: InfluxDB v1, InfluxDB v2, Discard — constructor
     functions (`NewInfluxDB`, `NewInfluxDBv2`, `NewDiscard`) that return `DBWriter`
   - Prometheus backends stay per-collector (different metric modeling strategies)
     but implement the shared `DBWriter` interface
   - **goppstats architectural fix:** refactor to convert `PPStatResult` → `Point`
     before calling the backend (matching gostats's existing clean separation
     of OneFS-specific data → generic Point → backend). The `WritePPStats`
     and `UpdateDatasets` methods are removed from the common interface;
     `UpdateDatasets` moves to a Prometheus-specific concern.

6. **Update dashgen** — Refactor dashgen's PAPI client to use `internal/api`

**For each extraction:**
- Extract package with tests
- Update one collector to use it
- Verify tests pass
- Update the other collector
- Verify tests pass
- Remove duplicated code

**Exit criteria:** No duplicated files between `cmd/gostats/` and
`cmd/goppstats/`. Shared code lives in `internal/`. All tests pass.

---

### Phase 3: Dashboard Modernization

**Goal:** Rewrite all dashboards using the Grafana legacy JSON format with
modern panel types and InfluxQL queries. Update dashgen to produce the
same format. Incorporate interim dashboards from existing work.

**Dashboard format decision:** Use the **Grafana legacy format** (flat JSON
with `schemaVersion`, `panels[]` array, `templating.list[]`) rather than
the Grafana 12 v2beta1 Kubernetes-style format. Rationale:
- Universal compatibility (Grafana 10, 11, 12+)
- Stable, battle-tested, actively maintained with auto-migration
- v2beta1 is explicitly experimental and may change
- Ecosystem tooling (Grafonnet, provisioning, marketplace) assumes legacy

#### Static Dashboards (rewrite from old connector format)

All dashboards use:
- Grafana legacy JSON format with current schemaVersion
- Modern panel types (timeseries instead of graph, stat instead of singlestat)
- Template variables: datasource picker, cluster selector
- InfluxQL queries (compatible with InfluxDB v1 and v2)
- Tags: `["powerscale", "gostats"]`
- Consistent styling, units, and naming conventions

**Core dashboards:**

1. **Cluster List** — Multi-cluster overview
   - Health status, node count per cluster
   - CPU utilization (sys/user), network throughput, storage summary
   - Click-through links to cluster detail
   - Source: `grafana_cluster_list_dashboard.json`

2. **Cluster Detail** — Single cluster deep dive
   - CPU breakdown (sys/user/idle/intr)
   - Network I/O (internal/external, bytes in/out)
   - Filesystem I/O rates
   - Disk I/O rates and latency
   - Per-node breakdowns
   - Source: `grafana_cluster_detail_dashboard.json`

3. **Cluster Capacity** — Storage utilization
   - Total/used/free/available capacity
   - Percent utilization over time
   - Source: `grafana_cluster_capacity_utilization_dashboard.json`

4. **Cluster Protocol** — Per-protocol performance
   - Operation counts per protocol (NFS, SMB2, HDFS, etc.)
   - Throughput (bytes in/out) per protocol
   - Latency per protocol
   - Client connection counts
   - Source: `grafana_cluster_protocol_dashboard.json`

#### Interim Dashboards (incorporate from existing work)

5-8. **Drive statistics and others** (3-5 dashboards)
   - To be provided; modernize if needed or include directly
   - Likely cover: drive I/O, drive latency, summary stats views

#### dashgen Updates

9. **Rewrite dashgen output to use Grafana legacy format** — replace the
   v2beta1 Kubernetes-style output with standard Grafana JSON (panels array,
   gridPos layout, templating.list variables). This aligns dashgen output
   with the static dashboards and ensures compatibility with Grafana 10+.
10. Remove the InfluxDB v2/Flux stub restriction (InfluxQL works for both)
11. Ensure consistent variable naming and tag conventions with static dashboards

**Exit criteria:** All dashboards importable into Grafana 10+, rendering
correctly against InfluxDB with gostats/goppstats data.

---

### Phase 4: Containerization & Deployment

**Goal:** Container images for collectors, Docker Compose evaluation stack,
unified GoReleaser config.

**Tasks:**

1. **GoReleaser** — Single `.goreleaser.yaml` building three binaries:
   - `gostats` (Linux/Windows/macOS, amd64/arm64)
   - `goppstats` (Linux/Windows/macOS, amd64/arm64)
   - `dashgen` (Linux/Windows/macOS, amd64/arm64)

2. **Dockerfiles** — Multi-stage builds:
   ```dockerfile
   FROM golang:1.24-alpine AS builder
   WORKDIR /src
   COPY . .
   RUN go build -o /gostats ./cmd/gostats/

   FROM alpine:3.21
   RUN apk add --no-cache ca-certificates
   COPY --from=builder /gostats /usr/local/bin/
   ENTRYPOINT ["gostats"]
   ```
   - `Dockerfile.gostats` → `ghcr.io/isilon/pdi-gostats`
   - `Dockerfile.goppstats` → `ghcr.io/isilon/pdi-goppstats`

3. **Docker Compose** — `docker/docker-compose.yml`:
   - `influxdb:1.8` with pre-created `isi_data_insights` database
   - `grafana:latest` with provisioned datasource + dashboards
   - `gostats` with example config (cluster hostname as env var)
   - `goppstats` with example config
   - User runs: `CLUSTER=mycluster.example.com docker compose up`

4. **Grafana provisioning:**
   - `docker/grafana/provisioning/datasources/influxdb.yml` — auto-configured
   - `docker/grafana/provisioning/dashboards/dashboards.yml` — loads from volume
   - Dashboard JSONs mounted from `dashboards/influxdb/`

5. **GitHub Actions release workflow:**
   - Trigger: tag push (`v*`)
   - Steps: GoReleaser (binaries + GitHub release) → Docker build/push to GHCR

**Exit criteria:** `docker compose up` brings up full working stack.
`goreleaser release` produces binaries + container images.

---

### Phase 5: Documentation

**Goal:** Comprehensive docs making the project self-service.

**Can proceed incrementally alongside other phases.** Skeleton created in
Phase 1, fleshed out as features land.

| Document | Contents |
|----------|----------|
| `README.md` | Architecture overview, quickstart (3 paths: binary, Docker, compose), feature summary, links to docs |
| `docs/architecture.md` | Data flow diagram, component descriptions, how collectors/TSDB/Grafana interact |
| `docs/getting-started.md` | End-to-end: create OneFS user → configure collector → set up InfluxDB → import dashboards → see data |
| `docs/onefs-setup.md` | OneFS user creation, required privileges (ISI_PRIV_STATISTICS, ISI_PRIV_PERFORMANCE, ISI_PRIV_NFS), role setup |
| `docs/configuration.md` | Complete TOML reference for gostats and goppstats, all options with defaults and examples |
| `docs/dashboards.md` | Dashboard descriptions, screenshots, customization guide, using dashgen for PP dashboards |
| `docs/deployment.md` | Binary deployment (systemd service files), Docker standalone, Docker Compose, Kubernetes guidance |
| `docs/migrating-from-v1.md` | For Python connector users: what changed, config format migration, dashboard import, feature parity notes |

**Exit criteria:** A new user can go from zero to seeing data in Grafana
by following the getting-started guide.

---

### Phase 6: Release

**v2.0 Release checklist:**

- [ ] All three binaries build and pass tests
- [ ] Shared library extraction complete, no duplicated code
- [ ] 8-9 Grafana v2beta1 dashboards (4 core + interim + PP via dashgen)
- [ ] Docker Compose stack working end-to-end
- [ ] Container images published to GHCR
- [ ] Cross-platform binaries via GoReleaser
- [ ] Documentation complete
- [ ] README with architecture overview and quickstart
- [ ] LICENSE (MIT)
- [ ] Migration guide for v1 users
- [ ] Old repos (tenortim/gostats, tenortim/goppstats) archived with pointer to new project

---

## Backlog (Post v2.0)

| Item | Priority | Notes |
|------|----------|-------|
| Prometheus dashboards (PromQL) | High | Full dashboard parity for Prometheus users |
| Concurrency dashboard | Medium | Rework using Grafana transformations (no derived stats) |
| Summary stats dashboards via dashgen | Medium | Extend dashgen for protocol/drive/client summary views |
| InfluxDB v3 support | Medium | Investigate when v3 stabilizes |
| Helm chart | Low | Kubernetes-native deployment |
| Alerting templates | Low | Successor to Kapacitor TICK scripts |
| dashgen test suite | Medium | dashgen currently has no tests; add unit tests for query generation, panel building, and PAPI response parsing |

---

## Execution Timeline

Phases are partially parallelizable:

```
Phase 1 (Scaffolding)
    │
    ├──→ Phase 2 (Shared Lib Extraction) ──→─┐
    │                                         │
    ├──→ Phase 3 (Dashboards) ─────────────→──┤
    │                                         │
    └──→ Phase 5 (Docs skeleton) ──→──────────┤
                                              │
                                    Phase 4 (Containers)
                                              │
                                    Phase 5 (Docs final)
                                              │
                                    Phase 6 (Release)
```

Phase 1 is the prerequisite for everything.
Phases 2, 3, and 5 (skeleton) can proceed in parallel after Phase 1.
Phase 4 depends on Phase 1 structure but not on Phase 2 completion.
Phase 6 requires all prior phases complete.
