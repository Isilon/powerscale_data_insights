# AGENTS.md — PowerScale Data Insights

Project guidance for AI assistants and contributors.

## Project Status

**Phase 1 (Scaffolding):** Complete
**Phase 2 (Shared Library Extraction):** Complete
**Phase 3 (Dashboard Modernization):** Not started
**Phase 4 (Containerization):** Not started
**Phase 5 (Documentation):** Skeleton only
**Phase 6 (Release):** Not started

See `PLAN.md` for the full project plan with detailed phase descriptions.

### What's been done
- Monorepo created at `github.com/isilon/powerscale_data_insights`
- Single Go module (go 1.24.6), no workspace — `go.mod` at root
- Three commands: `cmd/gostats/`, `cmd/goppstats/`, `cmd/dashgen/`
- Five shared internal packages extracted (see Architecture below)
- goppstats refactored: PP data converts to generic Points before backends
- All duplicated code between collectors eliminated
- All builds and tests pass (`make build && make test`)

### What's next
- Phase 3: Modernize dashboards to Grafana v2beta1 (4 core + 3-5 interim)
- A test system (OneFS cluster + InfluxDB + Grafana) will be needed to
  validate dashboards against real data

## Build & Test

```bash
# Build all binaries
make build

# Run all tests (includes internal/ packages)
make test

# Build individual components
make build-gostats
make build-goppstats
make build-dashgen

# Run all tests with verbose output
go test -v ./...

# Clean build artifacts
make clean
```

Requires Go 1.24+. Single-module project with `go.mod` at root.

## Architecture

```
powerscale_data_insights/
├── cmd/
│   ├── gostats/      — OneFS statistics collector (package main)
│   ├── goppstats/    — Partitioned Performance collector (package main)
│   └── dashgen/      — Grafana dashboard generator (package main)
├── internal/
│   ├── api/          — Shared OneFS PAPI HTTP client (auth, retry, TLS)
│   ├── backend/      — Point types, DBWriter interface, InfluxDB v1/v2, Discard
│   ├── config/       — Shared config structs, SecretFromEnv, defaults
│   ├── logging/      — slog setup, custom levels (TRACE-FATAL), LoggingConfig
│   └── platform/     — Config watcher, SIGHUP, socket options, network utils
├── dashboards/       — Pre-built Grafana dashboards (empty, Phase 3)
├── configs/          — Example TOML config files
├── docker/           — Dockerfiles and Compose (empty, Phase 4)
├── docs/             — Documentation (empty, Phase 5)
└── papi/             — OneFS PAPI 9.11 schema reference
```

### internal/api
Shared PAPI client used by all three commands. Provides `Cluster` struct with:
- Session and basic auth with exponential backoff retry
- Automatic re-authentication on 401 and session timeout
- `Connect()`, `RestGet()`, `Authenticate()`, `GetClusterConfig()`
- TLS configuration, CSRF token handling

### internal/backend
Generic time-series data model and backend interface:
- `Point{Name, Time, Fields[], Tags[]}` — the universal data representation
- `DBWriter` interface with `WritePoints(ctx, []Point)`
- `NewInfluxDB()`, `NewInfluxDBv2()`, `NewDiscard()` constructors
- Prometheus backends remain per-collector (different metric strategies)

### internal/config
Shared configuration primitives:
- `SecretFromEnv()` for `$env:VAR` credential substitution
- Config structs: `InfluxDBConfig`, `InfluxDBv2Config`, `PrometheusConfig`,
  `PromHTTPSDConfig`, `ClusterConfig` (with SSL/TLS fields)
- Default constants for retry limits, update intervals

### internal/logging
Structured logging with custom levels:
- Levels: TRACE, DEBUG, INFO, NOTICE, WARN, ERROR, CRITICAL, FATAL
- `Setup(progName, config, logLevel, logFile)` returns configured `*slog.Logger`
- `SetupEarlyLogging()` for pre-config stdout logging
- `ParseLevel()` for string-to-level conversion

### internal/platform
Platform-specific and OS utilities:
- `StartConfigWatcher()` — fsnotify-based config reload with debounce
- `NotifySIGHUP()` — Unix/Windows signal handling
- `Control()` — SO_REUSEADDR/SO_REUSEPORT socket options
- `FindExternalAddr()` — external IP discovery for Prometheus SD

### cmd/gostats
Collects OneFS statistics via PAPI. Key local files:
- `main.go` — entry point, per-cluster goroutines, priority queue scheduling
- `isilon_api.go` — stat-specific PAPI queries (GetStats, summary stats)
- `backend.go` — OneFS stat → Point conversion (decodeStat, etc.)
- `prometheus.go` — gostats-specific Prometheus backend
- `config.go` — gostats-specific config (stat groups, summary stats)
- `pq.go` — min-heap priority queue

### cmd/goppstats
Collects Partitioned Performance data via PAPI. Key local files:
- `main.go` — entry point, per-cluster goroutines, 30s poll loop
- `isilon_api.go` — PP-specific PAPI queries (datasets, workloads, exports)
- `backend.go` — PPStatResult → Point conversion (ppStatsToPoints)
- `prometheus.go` — goppstats-specific Prometheus backend
- `config.go` — goppstats-specific config (export lookup, etc.)

### cmd/dashgen
Generates Grafana v2beta1 dashboard JSON for PP datasets. Single file
(`main.go`, ~950 lines). Uses `internal/api` for PAPI access.

## Configuration

- gostats config: TOML format, default `idic.toml`
- goppstats config: TOML format, default `goppstats.toml`
- Example configs in `configs/`
- Passwords support `$env:VAR` syntax for environment variable substitution

## Go Module Path

Module: `github.com/isilon/powerscale_data_insights`

Note: lowercase `isilon` for Go module paths (Go convention) even though
the GitHub org is canonically `Isilon`. GitHub resolves both.

## Testing

```bash
# All tests (5 packages)
go test ./...

# Verbose
go test -v ./cmd/gostats/...
go test -v ./cmd/goppstats/...
go test -v ./internal/...
```

dashgen has no tests currently (backlog item).
