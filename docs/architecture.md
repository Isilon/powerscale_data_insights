# Architecture

PowerScale Data Insights collects performance and capacity data from one or
more Dell PowerScale (OneFS) clusters and stores it in a time-series database
for visualization in Grafana.

## System Overview

```
┌──────────────────┐     ┌──────────────────┐
│  OneFS Cluster 1 │     │  OneFS Cluster N │
│       (PAPI)     │     │       (PAPI)     │
└────────┬─────────┘     └────────┬─────────┘
         │  HTTPS (8080)          │
    ┌────┴────────────────────────┴────┐
    │                                  │
    ▼                                  ▼
┌──────────┐                    ┌────────────┐
│ gostats  │                    │ goppstats  │
│          │                    │            │
│ Cluster  │                    │ PP dataset │
│ stats    │                    │ stats      │
└────┬─────┘                    └─────┬──────┘
     │                                │
     │  generic Points                │
     └───────────┬────────────────────┘
                 │
        ┌────────┴────────┐
        ▼                 ▼
 ┌─────────────┐   ┌────────────┐
 │  InfluxDB   │   │ Prometheus │
 │  (v1 or v2) │   │  (scrape)  │
 └──────┬──────┘   └─────┬──────┘
        │                 │
        └────────┬────────┘
                 ▼
          ┌─────────────┐        ┌──────────┐
          │   Grafana    │◀───────│ dashgen  │
          │ (dashboards) │        │ (gen PP  │
          └─────────────┘        │  boards) │
                                 └──────────┘
```

## Components

### gostats — Statistics Collector

Collects OneFS platform statistics via the PAPI (Platform API). Runs a
per-cluster goroutine that queries stats on a configurable interval using
a priority-queue scheduler to batch requests by update frequency.

**Data collected:** CPU utilization, network throughput, filesystem I/O,
disk performance, per-protocol operations and latency, client connections,
cache hit ratios, filesystem heat, storage capacity, cluster health and
node status.

**Key files:**
- `cmd/gostats/main.go` — entry point, per-cluster goroutines, priority queue scheduling
- `cmd/gostats/isilon_api.go` — stat-specific PAPI queries
- `cmd/gostats/backend.go` — OneFS stat to Point conversion
- `cmd/gostats/prometheus.go` — gostats-specific Prometheus metrics
- `cmd/gostats/config.go` — stat groups, summary stats configuration

### goppstats — Partitioned Performance Collector

Collects OneFS Partitioned Performance (PP) data via PAPI v10. PP datasets
provide per-export, per-protocol, per-user breakdowns of I/O metrics. The
collector polls every 30 seconds, automatically discovering dataset definition
changes (additions, removals, schema changes) without restart.

**Data collected:** Per-partition CPU, operations, read/write ops, bytes
in/out, disk latency (read/write/other), L2/L3 cache hit rates. Each
data point is tagged with the dataset's partition attributes (export ID,
protocol, username, etc.).

**Key files:**
- `cmd/goppstats/main.go` — entry point, per-cluster goroutines, 30s poll loop
- `cmd/goppstats/isilon_api.go` — PP-specific PAPI queries (datasets, workloads)
- `cmd/goppstats/backend.go` — PPStatResult to Point conversion
- `cmd/goppstats/prometheus.go` — goppstats-specific Prometheus metrics
- `cmd/goppstats/config.go` — PP-specific configuration (export lookup, etc.)

### dashgen — Dashboard Generator

Generates Grafana dashboard JSON for a specific Partitioned Performance
dataset. Connects to a OneFS cluster via PAPI to discover the dataset
definition (partition attributes, workload types, filters), then produces
a dashboard with one timeseries panel per metric, correctly grouped by the
dataset's partition attributes.

**Key files:**
- `cmd/dashgen/main.go` — single-file tool (~950 lines)

### Shared Library (`internal/`)

Duplicated code between gostats and goppstats has been extracted into five
internal packages:

| Package | Purpose |
|---------|---------|
| `internal/api` | OneFS PAPI HTTP client — session and basic auth, exponential backoff retry, automatic re-authentication on 401 and session timeout, TLS configuration, CSRF token handling |
| `internal/backend` | Generic data model (`Point` with name, timestamp, fields, tags) and `DBWriter` interface — InfluxDB v1, InfluxDB v2, and Discard implementations |
| `internal/config` | Shared configuration primitives — `SecretFromEnv()` for `$env:VAR` credential substitution, config structs for backends and clusters, default constants |
| `internal/logging` | Structured logging via slog — custom levels (TRACE through FATAL), configurable handlers (text/JSON, stdout, file) |
| `internal/platform` | OS utilities — fsnotify-based config file watcher with debounce, SIGHUP signal handling, SO_REUSEADDR/SO_REUSEPORT socket options, external IP discovery |

## Data Flow

### Collection

1. Each collector reads its TOML config file and starts a goroutine per
   configured cluster.
2. The goroutine authenticates to the cluster's PAPI endpoint (session or
   basic auth) with automatic retry and re-authentication.
3. **gostats** queries `/platform/3/statistics/current` for each stat group
   on a schedule driven by each stat's native update interval.
   **goppstats** queries `/platform/10/performance/datasets` every 30 seconds
   to discover datasets and then fetches the latest data points.
4. Raw API responses are converted to generic `Point` structs (measurement
   name, timestamp, key-value fields, key-value tags).

### Storage

5. Points are written to the configured backend via the `DBWriter` interface:
   - **InfluxDB v1** — line protocol writes to a database
   - **InfluxDB v2** — line protocol writes to an org/bucket
   - **Prometheus** — points are stored in memory and served on a `/metrics`
     endpoint for Prometheus to scrape
   - **Discard** — no-op (testing/debugging)

### Visualization

6. Grafana queries the time-series database (InfluxQL for InfluxDB, PromQL
   for Prometheus) and renders the pre-built dashboards.
7. For Partitioned Performance data, `dashgen` can generate additional
   dashboards tailored to specific PP dataset definitions.

## Authentication

Both collectors support two OneFS authentication modes:

- **Session auth** (default) — POST to `/session/1/session` to obtain a
  session cookie; automatic re-authentication on 401 or session timeout.
- **Basic auth** — HTTP Basic authentication on every request; set
  `authtype = "basic-auth"` in the cluster config.

All credential fields support `$env:VARNAME` substitution to avoid
storing passwords in config files.

## Configuration Reload

Both collectors support live configuration reload:

- **SIGHUP** — send `kill -HUP <pid>` to reload the config file
- **File watcher** — fsnotify-based; the collector detects config file
  changes and reloads automatically (with debounce to avoid partial writes)

Note: some changes (e.g., adding a new cluster) may require a restart
depending on the collector's implementation.
