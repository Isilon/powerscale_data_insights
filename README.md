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
          ┌─────────────┐
          │  InfluxDB    │
          │  (v1 or v2)  │
          └──────┬───────┘
                 │
                 ▼
          ┌─────────────┐
          │   Grafana    │
          │ (dashboards) │
          └─────────────┘
```

## Requirements

- **Go 1.24+** (build from source)
- **OneFS 9.x+** (PAPI v10 for Partitioned Performance, PAPI v3 for summary stats)
- **InfluxDB** v1.8+ or v2.x (InfluxQL compatibility)
- **Grafana** 12.x+ (v2beta1 dashboard schema)

## Quick Start

### Build from source

```bash
make build
```

This produces three binaries in `bin/`:
- `bin/gostats`
- `bin/goppstats`
- `bin/dashgen`

### Configure

1. Create a local user on your OneFS cluster with the following privileges:
   - `ISI_PRIV_STATISTICS` — required for gostats
   - `ISI_PRIV_PERFORMANCE` — required for goppstats
   - `ISI_PRIV_NFS` — optional, for NFS export path resolution

2. Copy and edit the example configuration files:
   ```bash
   cp configs/gostats.example.toml idic.toml
   cp configs/goppstats.example.toml goppstats.toml
   ```

3. Edit the config files with your cluster hostname, credentials, and InfluxDB
   connection details. See [docs/configuration.md](docs/configuration.md) for
   the complete reference.

### Run

```bash
# Collect cluster statistics
./bin/gostats -config-file idic.toml

# Collect Partitioned Performance data
./bin/goppstats -config-file goppstats.toml

# Generate a PP dashboard
./bin/dashgen -host <cluster> -user <user> -password <pass> \
  -dataset 1 -datasource "isi_data_insights" -out pp-dashboard.json
```

### Import dashboards

Import the pre-built dashboards from `dashboards/influxdb/` into Grafana,
or use `dashgen` to generate Partitioned Performance dashboards tailored to
your dataset definitions.

## Documentation

- [Architecture](docs/architecture.md)
- [Getting Started](docs/getting-started.md)
- [Configuration Reference](docs/configuration.md)
- [Dashboards](docs/dashboards.md)
- [Deployment](docs/deployment.md)
- [OneFS Setup](docs/onefs-setup.md)
- [Migrating from v1](docs/migrating-from-v1.md)

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
├── docker/               Dockerfiles and Docker Compose stack
├── docs/                 Documentation
└── papi/                 OneFS PAPI schema reference
```

## License

[MIT](LICENSE)
