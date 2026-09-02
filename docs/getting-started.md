# Getting Started

This guide walks you through setting up PowerScale Data Insights from scratch:
creating a OneFS user, configuring the collectors, setting up InfluxDB and
Grafana, and seeing your first dashboards.

## Prerequisites

- A Dell PowerScale cluster running **OneFS 9.x or later**
- Network access from the machine running the collectors to the cluster's
  PAPI port (TCP 8080 by default)
- **InfluxDB** v1.8+ or v2.x
- **Grafana** 10+

## Step 1: Create a OneFS User

Create a dedicated user on your OneFS cluster with the minimum required
privileges. See [OneFS Setup](onefs-setup.md) for detailed instructions.

At minimum, the user needs:

| Privilege | Required by | Purpose |
|-----------|-------------|---------|
| `ISI_PRIV_STATISTICS` | gostats | Read cluster statistics |
| `ISI_PRIV_PERFORMANCE` | goppstats | Read Partitioned Performance data |
| `ISI_PRIV_NFS` (read-only) | goppstats (optional) | Resolve NFS export IDs to paths |
| `ISI_PRIV_QUOTA` (read-only) | goquotas | Read live quota accounting and limits |

## Step 2: Set Up InfluxDB

### InfluxDB v1

```bash
# Create the database
influx -execute "CREATE DATABASE isi_data_insights"
```

### InfluxDB v2

Create a bucket named `isi_data_insights` and generate an API token with
write access. InfluxQL compatibility must be enabled (it is by default in
InfluxDB v2).

## Step 3: Install the Collectors

### Option A: Docker Compose (recommended for evaluation)

This brings up InfluxDB, Grafana, and all collectors in one step.

```bash
cd docker/
cp gostats.example.toml gostats.toml
cp goppstats.example.toml goppstats.toml
cp goquotas.example.toml goquotas.toml
```

Edit the config files — at minimum, update the `[[cluster]]` section:

```toml
[[cluster]]
hostname = "your-cluster.example.com"
username = "statsuser"
password = "your-password"
verify-ssl = false
```

Then start the stack:

```bash
docker compose up -d
```

Skip to [Step 5](#step-5-view-dashboards) — InfluxDB and Grafana are
pre-configured.

### Option B: Build from source

Requires Go 1.25+.

```bash
git clone https://github.com/Isilon/powerscale_data_insights.git
cd powerscale_data_insights
make build
```

This produces `bin/gostats`, `bin/goppstats`, `bin/goquotas`, and
`bin/dashgen`.

### Option C: Download pre-built binaries

Download the latest release from the
[GitHub Releases](https://github.com/Isilon/powerscale_data_insights/releases)
page for your platform.

## Step 4: Configure and Run

Copy the example configs and edit them:

```bash
cp configs/gostats.example.toml idic.toml
cp configs/goppstats.example.toml goppstats.toml
cp configs/goquotas.example.toml goquotas.toml
```

In each file, update:

1. **`[[cluster]]`** — your cluster hostname, username, and password
2. **`[influxdb]`** — your InfluxDB host (default `localhost:8086`)

See [Configuration Reference](configuration.md) for all options.

Start the collectors:

```bash
# Collect cluster statistics
./bin/gostats -config-file idic.toml

# Collect Partitioned Performance data (in a separate terminal)
./bin/goppstats -config-file goppstats.toml

# Collect directory quota usage (in a separate terminal)
./bin/goquotas -config-file goquotas.toml
```

You should see log output indicating successful connection to each cluster
and stats being written to InfluxDB.

## Step 5: View Dashboards

### If using Docker Compose

Open [http://localhost:3000](http://localhost:3000) and log in with
**admin / admin**. The dashboards are already provisioned under the
**PowerScale** folder.

### If running standalone

1. Open Grafana and add an InfluxDB datasource:
   - **URL:** `http://localhost:8086`
   - **Database:** `isi_data_insights`

2. Import the dashboards from `dashboards/import/influxdb/` (not
   `dashboards/influxdb/`, which is used for Docker Compose provisioning
   and doesn't prompt for a datasource — see [Importing
   Dashboards](dashboards.md#importing-dashboards)):
   - Go to **Dashboards > Import**
   - Upload each JSON file or paste its contents
   - Select your InfluxDB datasource when prompted

The four core dashboards are:

| Dashboard | Description |
|-----------|-------------|
| **PowerScale - Cluster List** | Multi-cluster overview with health, CPU, capacity, protocol stats |
| **PowerScale - Cluster Detail** | Single cluster deep dive with CPU, network, disk, cache, protocol panels |
| **PowerScale - Cluster Capacity** | Storage utilization across clusters |
| **PowerScale - Protocol Overview** | Cluster-level protocol performance for a single cluster |
| **PowerScale - Quota Overview** | Current quota inventory, readiness, and top utilization |
| **PowerScale - Quota Detail** | Usage and limit history selected by cluster and quota path |

## Step 6: Generate PP Dashboards (Optional)

If you have Partitioned Performance datasets configured on your cluster,
use `dashgen` to generate dashboards for them:

```bash
# List datasets (check the PAPI directly or use the OneFS UI)
# Then generate a dashboard for a specific dataset ID:
./bin/dashgen \
  -host your-cluster.example.com \
  -user statsuser \
  -password your-password \
  -dataset 1 \
  -out pp-dataset-1.json
```

Import the generated JSON file into Grafana. See [Dashboards](dashboards.md)
for more details on dashgen usage.

## Next Steps

- [Configuration Reference](configuration.md) — all config options
- [Dashboards](dashboards.md) — dashboard descriptions and dashgen guide
- [Deployment](deployment.md) — systemd, Docker, Kubernetes
- [Migrating from v1](migrating-from-v1.md) — if upgrading from the Python connector
- [Migrating from standalone gostats/goppstats](migrating-from-standalone-collectors.md) — if already running the Go collectors from the separate repos
