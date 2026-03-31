# AGENTS.md — PowerScale Data Insights

Project guidance for AI assistants and contributors.

## Build & Test

```bash
# Build all binaries
make build

# Run all tests
make test

# Build individual components
make build-gostats
make build-goppstats
make build-dashgen

# Clean build artifacts
make clean
```

Requires Go 1.24+. The project uses a Go workspace (`go.work`) with three
modules under `cmd/`.

## Architecture

This is a Go workspace monorepo with three commands and a shared internal
library (extraction in progress):

```
cmd/gostats/      — OneFS statistics collector (package main)
cmd/goppstats/    — Partitioned Performance collector (package main)
cmd/dashgen/      — Grafana dashboard generator (package main)
internal/         — Shared packages (api, backend, config, logging, platform)
```

### cmd/gostats

Collects OneFS statistics via PAPI and writes to InfluxDB v1/v2 or Prometheus.

**Key files:**
- `main.go` — entry point, config loading, per-cluster goroutine orchestration
- `isilon_api.go` — OneFS PAPI client (auth, stat collection, metadata)
- `backend.go` — JSON decoding, Point struct creation
- `config.go` — TOML config parsing
- `statssink.go` — DBWriter interface
- `influxdb.go` / `influxdbv2.go` / `prometheus.go` / `discard.go` — backends
- `logging.go` — slog setup with custom levels
- `pq.go` — min-heap priority queue for scheduling

### cmd/goppstats

Collects Partitioned Performance data via PAPI and writes to the same backends.

**Key files:** Same structure as gostats. The `DBWriter` interface differs
(`WritePPStats` instead of `WritePoints`). Polls PP datasets every 30 seconds.

### cmd/dashgen

Generates Grafana v2beta1 dashboard JSON for PP datasets. Queries the PAPI
to discover dataset attributes and generates one panel per metric with
overflow workload type support.

**Key files:**
- `main.go` — all logic in a single file (~1037 lines)

## Configuration

- gostats config: TOML format, default `idic.toml`
- goppstats config: TOML format, default `goppstats.toml`
- Example configs in `configs/`
- Passwords support `$env:VAR` syntax for environment variable substitution

## Backends

Both collectors support:
- **InfluxDB v1** — HTTP batch writes
- **InfluxDB v2** — async writes, token auth
- **Prometheus** — per-cluster HTTP `/metrics` endpoint
- **Discard** — no-op for testing

## Go Module Paths

Current module paths are from the original repos and will be updated to
`github.com/isilon/powerscale_data_insights/...` during Phase 2 refactoring.
Note: lowercase `isilon` for Go module paths (Go convention) even though
the GitHub org is `Isilon`.

## Testing

```bash
# All tests
make test

# Individual module tests
go test -v ./cmd/gostats/...
go test -v ./cmd/goppstats/...
```

dashgen has no tests currently.
