# PowerScale Data Insights

Collect, store, and visualize Dell PowerScale OneFS cluster performance data.

PowerScale Data Insights is the successor to the
[Isilon Data Insights Connector](https://github.com/Isilon/isilon_data_insights_connector).
It replaces the Python-based collector with two purpose-built Go collectors,
adds a dashboard generator for Partitioned Performance datasets, and ships
modernized Grafana dashboards.

## Components

| Component | Description |
|-----------|-------------|
| **gostats** | Collects OneFS statistics via PAPI and writes to InfluxDB v1/v2 or Prometheus |
| **goppstats** | Collects OneFS Partitioned Performance data via PAPI and writes to InfluxDB v1/v2 or Prometheus |
| **dashgen** | Generates Grafana dashboards for Partitioned Performance datasets by querying the PAPI at runtime |

## Architecture

```
┌──────────────────┐     ┌──────────────────┐
│  OneFS Cluster 1 │     │  OneFS Cluster N │
│       (PAPI)     │     │       (PAPI)     │
└────────┬─────────┘     └────────┬─────────┘
         │                        │
    ┌────┴────────────────────────┴────┐
    │                                  │
    ▼                                  ▼
┌──────────┐                    ┌────────────┐
│ gostats  │                    │ goppstats  │
│(stats)   │                    │(PP data)   │
└────┬─────┘                    └─────┬──────┘
     │                                │
     └───────────┬────────────────────┘
                 │
                 ▼
          ┌────────────────┐
          │   InfluxDB     │
          │  (v1 or v2)    │
          │       or       │
          │  Prometheus    │
          └───────┬────────┘
                  │
                  ▼
          ┌────────────────┐
          │    Grafana     │
          │ (dashboards)   │
          └────────────────┘
```

Both collectors run independently, querying one or more OneFS clusters via
PAPI and writing time-series data to the configured backend. Grafana reads
from the time-series database and renders the pre-built dashboards. See
[docs/architecture.md](docs/architecture.md) for details.

## Requirements

- **Go 1.25+** (build from source)
- **OneFS 9.x+** (PAPI v10 for Partitioned Performance, PAPI v3 for summary stats)
- **InfluxDB** v1.8+ or v2.x (InfluxQL compatibility)
- **Grafana** 10+ (legacy dashboard format with modern panel types)

## Quick Start

There are three ways to get up and running:

### Option 1: Docker Compose (fastest)

Brings up InfluxDB, Grafana, and both collectors in one command.

```bash
cd docker/
cp gostats.example.toml gostats.toml
cp goppstats.example.toml goppstats.toml
# Edit both files: set hostname, username, password under [[cluster]]

docker compose up -d
```

Open Grafana at [http://localhost:3000](http://localhost:3000) (admin/admin).
Pre-built dashboards are provisioned automatically.

### Option 2: Build from source

```bash
make build
```

This produces three binaries in `bin/`:
- `bin/gostats`
- `bin/goppstats`
- `bin/dashgen`

Configure and run:

```bash
cp configs/gostats.example.toml idic.toml
cp configs/goppstats.example.toml goppstats.toml
# Edit both files with your cluster and InfluxDB details

./bin/gostats -config-file idic.toml
./bin/goppstats -config-file goppstats.toml
```

### Option 3: Docker (standalone containers)

```bash
# Build
docker build -f docker/Dockerfile.gostats -t pdi-gostats .
docker build -f docker/Dockerfile.goppstats -t pdi-goppstats .

# Run (mount your config file)
docker run -d -v /path/to/idic.toml:/etc/gostats/idic.toml pdi-gostats
docker run -d -v /path/to/goppstats.toml:/etc/goppstats/goppstats.toml pdi-goppstats
```

### Generate a Partitioned Performance dashboard

```bash
./bin/dashgen -host <cluster> -user <user> -password <pass> \
  -dataset <id> -out pp-dashboard.json
```

Import the generated JSON into Grafana, or use the pre-built dashboards in
`dashboards/influxdb/`.

## Documentation

- [Architecture](docs/architecture.md) — component design, data flow, shared library
- [Getting Started](docs/getting-started.md) — end-to-end setup guide
- [Configuration Reference](docs/configuration.md) — complete TOML reference
- [Dashboards](docs/dashboards.md) — dashboard guide and using dashgen
- [Deployment](docs/deployment.md) — binary, Docker, Docker Compose, Kubernetes
- [OneFS Setup](docs/onefs-setup.md) — cluster user creation and privileges
- [Migrating from v1](docs/migrating-from-v1.md) — guide for Python connector users

## Project Structure

```
powerscale_data_insights/
├── cmd/
│   ├── gostats/          Statistics collector
│   ├── goppstats/        Partitioned Performance collector
│   └── dashgen/          Dashboard generator
├── internal/             Shared library (PAPI client, backends, config, logging)
├── dashboards/influxdb/  Pre-built Grafana dashboards (InfluxQL)
├── configs/              Example configuration files
├── docker/               Dockerfiles, Docker Compose, Grafana provisioning
├── docs/                 Documentation
└── papi/                 OneFS PAPI schema reference
```

## License

[MIT](LICENSE)
