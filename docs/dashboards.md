# Dashboards

PowerScale Data Insights ships pre-built Grafana dashboards for InfluxDB
and includes a tool (`dashgen`) to generate dashboards for Partitioned
Performance datasets.

All dashboards use the Grafana legacy JSON format (schemaVersion 39) with
modern panel types (timeseries, stat) and InfluxQL queries. They are
compatible with Grafana 10 and later, and work against both InfluxDB v1
and v2 (via InfluxQL).

## Pre-Built Dashboards

The pre-built dashboards are in `dashboards/influxdb/`. They are tagged
with `["powerscale", "gostats"]` and use data collected by the **gostats**
collector.

### PowerScale - Cluster List

**File:** `cluster_list.json`

Multi-cluster overview. Displays a repeating row per cluster with at-a-glance
health, performance, and capacity metrics. Designed as the entry point for
multi-cluster monitoring.

**Panels per cluster:**
- Cluster name (with link to Cluster Detail)
- Total Nodes, Nodes Down, Health status
- CPU utilization, Storage capacity utilization
- NFS throughput, ops/s, latency
- SMB2 throughput, ops/s, latency

**Variables:** cluster (multi-select)

### PowerScale - Cluster Detail

**File:** `cluster_detail.json`

Deep dive into a single cluster. Top row of stat panels for key metrics,
followed by collapsible sections for detailed time-series data.

**Stat panels:**
- Total Nodes, Nodes Down, Health
- CPU, Capacity
- NFS throughput/ops/latency, SMB2 throughput/ops/latency

**Time-series sections:**
- Cluster Capacity Utilization over time
- CPU Breakdown (interrupt, system, user, idle — stacked)
- External Network Throughput (bytes in/out)
- Protocol Operations with CPU overlay
- Client Connections by protocol
- Cache Hit Ratios (L1/L2/L3 data and metadata)

**Variables:** cluster (single-select)

### PowerScale - Cluster Capacity

**File:** `cluster_capacity.json`

Storage capacity utilization across clusters. Table showing current
utilization per cluster with color-coded thresholds (green <85%,
orange 85-90%, red >90%).

**Variables:** cluster (multi-select)

### PowerScale - Protocol Detail

**File:** `cluster_protocol.json`

Per-protocol performance analysis for a single cluster. Select a protocol
to see its throughput, operations, latency, client connections, and
operation mix breakdown.

**Stat panels:** Total Nodes, Nodes Down, Health, CPU, Capacity,
protocol-specific throughput/ops/latency

**Time-series sections:**
- Client Connections for selected protocol
- Protocol Operations with CPU overlay
- Operation Mix (breakdown by operation type and class)

**Variables:** cluster (single-select), protocol (single-select: nfs, nfs3,
nfs4, smb1, smb2, hdfs, ftp, siq, lsass_in, lsass_out, papi)

### PowerScale - Drive Statistics

**File:** `drive_stats.json`

Per-node disk performance dashboard. Designed to help identify nodes with
abnormal latency or queue depth, especially on large clusters.

**Cluster-wide overview (stat panels):**
- Total Disk IOPS, Read IOPS, Write IOPS
- Read Throughput, Write Throughput

**Node Health Summary (table):**
- One row per node showing current access latency, I/O scheduler latency,
  queue depth, busy %, and slow accesses per second
- Sorted by access latency descending (worst nodes first)
- Color-coded thresholds for quick identification of problem nodes

**Per-node time-series panels:**
- Disk Access Latency by Node (ms)
- I/O Scheduler Latency by Node (ms)
- I/O Scheduler Queue Depth by Node
- Disk Busy % by Node
- Disk Throughput by Node (reads positive, writes negative)
- Disk IOPS by Node (reads positive, writes negative)
- Average I/O Size by Node (read and write)
- Slow Disk Accesses by Node

**Variables:** cluster (single-select), node (multi-select with include-all,
populated from selected cluster)

### PowerScale - Protocol Summary Stats

**File:** `protocol_summary.json`

Per-node, per-operation protocol statistics using OneFS summary statistics.
Provides deeper analysis than the Protocol Detail dashboard, with full
latency distribution (avg/min/max/stddev) and per-operation breakdowns.

> **Note:** This dashboard uses `node.summary.protocol` data which requires
> `protocol = true` in the `[summary_stats]` config section. The Protocol
> Detail dashboard uses `cluster.protostats.*` data which is always collected.
> Use Protocol Detail for cluster-level overview; use Protocol Summary Stats
> for per-node, per-operation drill-down with latency distribution.

**Overview stats:**
- Total ops/s, average latency, inbound/outbound throughput

**Time-series panels:**
- Operation Rate by Class (read, write, namespace_read, etc.)
- Operation Rate by Operation (getattr, setattr, write, etc.)
- Average Latency by Class
- Average Latency by Operation
- Latency Distribution (average, maximum, minimum, standard deviation)
- Inbound (Write) Throughput by Operation
- Outbound (Read) Throughput by Operation
- Operation Rate by Node (identify hot nodes)
- Average Latency by Node (identify slow nodes)

**Variables:** cluster (single-select), protocol (single-select: nfs3, nfs4,
smb1, smb2, etc.), node (multi-select with include-all, populated from
selected cluster)

### PowerScale - Client Summary Stats

**File:** `client_summary.json`

Per-client activity dashboard using OneFS client summary statistics. Shows
which clients are generating the most load or experiencing the highest
latency -- invaluable for "who's hammering the cluster" investigations.

> **Note:** This dashboard uses `node.summary.client` data which requires
> `client = true` in the `[summary_stats]` config section.
>
> **Cardinality warning:** Client summary stats have high tag cardinality
> (`remote_addr` x `protocol` x `class` x `node` x `user_name`). On
> clusters with hundreds of active clients, this can cause InfluxDB
> performance and storage issues. Monitor your InfluxDB resource usage
> if enabling this on large production clusters.

**Overview stats:**
- Total client ops/s, average latency, inbound/outbound throughput

**Top Clients table:**
- Per-client: address, ops/s, avg/max latency, inbound/outbound throughput
- Sorted by ops/s descending (busiest clients first)
- Color-coded latency thresholds

**Time-series panels:**
- Operation Rate and Average Latency by Client
- Operation Rate and Average Latency by Protocol
- Operation Rate and Average Latency by Operation Class
- Operation Rate and Average Latency by Node

**Variables:** cluster (single-select), node (multi-select with include-all),
protocol (multi-select with include-all, populated from active protocols)

## Thresholds

The dashboards use consistent threshold values:

| Metric | Green | Orange | Red |
|--------|-------|--------|-----|
| Capacity | < 80% | 80-90% | > 90% |
| CPU | < 80% | >= 80% | >= 95% |
| Latency | < 10ms | 10-25ms | >= 25ms |
| Nodes Down | 0 | >= 1 | >= 2 |
| Health | 0 (Healthy) | 1 (Attention) | 2 (Down) |
| Disk Access Latency | < 5ms | 5-20ms | >= 20ms |
| Disk Queue Depth | < 5 | 5-20 | >= 20 |
| Disk Busy | < 50% | 50-80% | >= 80% |
| Slow Accesses | 0 | >= 1/s | >= 10/s |
| Client Avg Latency | < 10ms | 10-50ms | >= 50ms |
| Client Max Latency | < 50ms | 50-200ms | >= 200ms |

## Importing Dashboards

### Grafana UI

1. Go to **Dashboards > Import**
2. Click **Upload dashboard JSON file** or paste the JSON contents
3. Select your InfluxDB datasource
4. Click **Import**

### Grafana Provisioning (Docker Compose)

When using the Docker Compose stack, dashboards are provisioned
automatically via volume mount. The provisioning config at
`docker/grafana/provisioning/dashboards/dashboards.yml` loads all JSON
files from `dashboards/influxdb/` into a **PowerScale** folder.

### Grafana API

```bash
curl -X POST http://admin:admin@localhost:3000/api/dashboards/db \
  -H "Content-Type: application/json" \
  -d "{\"dashboard\": $(cat dashboards/influxdb/cluster_list.json), \"overwrite\": true}"
```

## Customizing Dashboards

The dashboards are standard Grafana JSON — you can modify them freely in the
Grafana UI after import. Common customizations:

- **Change default time range** — edit the dashboard settings
- **Add panels** — add new panels using the same InfluxDB datasource
- **Adjust thresholds** — edit panel overrides to change color thresholds
- **Add protocols** — edit the protocol variable in Protocol Detail to add
  or remove protocol options

If you re-import a dashboard, set **overwrite = true** to replace the
existing version.

## dashgen — Partitioned Performance Dashboards

The `dashgen` tool generates Grafana dashboards for Partitioned Performance
(PP) datasets. It connects to a OneFS cluster via PAPI, discovers the
dataset definition (partition attributes, workload types), and produces a
dashboard with panels correctly grouped by those attributes.

### Usage

```bash
dashgen -host <cluster> -user <user> -password <pass> -dataset <id> [-out file.json]
```

### Flags

| Flag | Default | Description |
|------|---------|-------------|
| `-host` | *required* | OneFS cluster hostname or IP |
| `-port` | `8080` | PAPI port |
| `-user` | *required* | PAPI username |
| `-password` | *required* | PAPI password |
| `-dataset` | *required* | PP dataset ID |
| `-influx-version` | `"v1"` | InfluxDB version: `v1` or `v2` |
| `-out` | stdout | Output file path |
| `-skip-verify` | `false` | Skip TLS certificate verification |
| `-export-path` | `false` | Group by `export_path` instead of `export_id` |

### What It Generates

The generated dashboard includes:

- **Title:** `Partitioned Performance: <DatasetName>`
- **Tags:** `["goppstats", "powerscale"]`
- **Variables:** cluster selector, overflow workload toggle

**Panels** (one timeseries panel per metric):

| Metric | Title | Unit |
|--------|-------|------|
| cpu | CPU | ms |
| ops | Protocol Operations | ops/s |
| reads | Read Operations | ops/s |
| writes | Write Operations | ops/s |
| bytes_in | Bytes In | bytes/s |
| bytes_out | Bytes Out | bytes/s |
| latency_read | Disk Latency (read) | ms |
| latency_write | Disk Latency (write) | ms |
| latency_other | Latency (other) | ms |
| l2 | L2 Cache Hit Rate | ops/s |
| l3 | L3 Cache Hit Rate | ops/s |

Each panel contains queries grouped by the dataset's partition attributes
(export ID/path, protocol, username, etc.) and separate queries for
overflow workload types (Additional, Excluded, Overaccounted, System,
Unknown) gated by the overflow toggle variable.

### Example

```bash
# Generate a dashboard for dataset 1
./bin/dashgen \
  -host mycluster.example.com \
  -user statsuser \
  -password mypass \
  -dataset 1 \
  -out pp-dataset-1.json

# If using export path lookup (goppstats has lookup_export_ids=true)
./bin/dashgen \
  -host mycluster.example.com \
  -user statsuser \
  -password mypass \
  -dataset 1 \
  -export-path \
  -out pp-dataset-1.json
```

Import the generated file into Grafana as described above. The dashboard
uses the same InfluxDB datasource as the pre-built dashboards.
