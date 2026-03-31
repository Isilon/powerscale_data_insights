# Migrating from v1 (Python Connector)

This guide is for users of the
[Isilon Data Insights Connector](https://github.com/Isilon/isilon_data_insights_connector)
(the Python-based collector) who are upgrading to PowerScale Data Insights v2.

## What Changed

| Area | v1 (Python) | v2 (Go) |
|------|-------------|---------|
| Language | Python 2/3 | Go |
| Config format | INI (`.cfg`) | TOML (`.toml`) |
| Minimum OneFS | 7.2+ | 9.x+ |
| Collectors | Single daemon | Two separate binaries (gostats, goppstats) |
| PP data | Not supported | goppstats collector + dashgen |
| InfluxDB v2 | Not supported | Supported (via InfluxQL) |
| Derived stats | Composite, equation, percent change | Removed (use Grafana) |
| Kapacitor | Supported | Not supported |
| HDFS dashboards | Included | Removed |
| Dashboard format | Legacy (old panel types) | Legacy (modern panel types) |
| Deployment | Python venv | Binary, Docker, Docker Compose |
| Config reload | Restart required | SIGHUP / file watcher |
| Process management | Built-in daemon (`start`/`stop`) | External (systemd, Docker) |

## What's New in v2

- **Partitioned Performance collection** — goppstats collects per-export,
  per-protocol, per-user I/O breakdowns that were not available in v1.
- **Dashboard generator** — dashgen creates Grafana dashboards tailored to
  your PP dataset definitions.
- **InfluxDB v2 support** — works via InfluxQL against both v1 and v2.
- **Docker and Docker Compose** — containerized deployment with auto-provisioned
  Grafana.
- **Shared library** — common code extracted, eliminating duplication.
- **Live config reload** — SIGHUP or automatic file-watch reload.
- **Summary stats** — protocol, client, and drive summary stats via PAPI v3.
- **Cross-platform binaries** — Linux, macOS, Windows (amd64, arm64).

## What's Removed

### Derived Stats

v1 supported composite stats, equation stats, percent change stats, and
final equation stats — all computed in the collector before writing to
InfluxDB. These are removed in v2.

**Why:** Grafana can perform these calculations at query time using
transformations and math expressions, which is more flexible and doesn't
require collector restarts to change formulas.

**Migration:** Recreate derived metrics as Grafana transformations or
calculated fields in your dashboard panels. For example, the v1
`cluster.ifs.concurrency` equation stat can be expressed as a Grafana
math expression across two InfluxQL queries.

### Kapacitor Integration

v1 included documentation and example TICK scripts for Kapacitor-based
alerting. v2 does not include Kapacitor support.

**Migration:** Use Grafana Alerting (built into Grafana 9+) as a
replacement. Grafana alerting supports the same alert conditions
(thresholds, rate of change, no-data detection) with notification
channels (email, Slack, PagerDuty, webhooks, etc.).

### HDFS Dashboards

The `grafana_hadoop_home.json` and `grafana_hadoop_datanodes.json`
dashboards are removed. HDFS protocol stats are still collected by
gostats (as part of `cluster_proto_stats` and `cluster_client_activity_stats`),
so you can create custom HDFS dashboards if needed.

### OneFS 7.2/8.0 Support

v2 requires OneFS 9.x or later. The `isi_sdk_7_2` and `isi_sdk_8_0`
Python SDK dependencies are no longer needed.

## Migration Steps

### 1. Create a New OneFS User

If your existing v1 user only has statistics privileges, you may need to
add `ISI_PRIV_PERFORMANCE` for goppstats. See [OneFS Setup](onefs-setup.md).

### 2. Convert Your Configuration

**v1 config** (`isi_data_insights_d.cfg`, INI format):

```ini
[isi_data_insights_d]
stats_processor: influxdb_plugin
stats_processor_args: localhost 8086 isi_data_insights
clusters: statsuser:password@mycluster.example.com:False

[cluster_cpu_stats]
update_interval: *
stats: cluster.cpu.sys.avg
    cluster.cpu.user.avg
    cluster.cpu.idle.avg
    cluster.cpu.intr.avg
```

**v2 config** (`gostats.toml`, TOML format):

```toml
[global]
version = "v0.39"
stats_processor = "influxdb"
active_stat_groups = ["cluster_cpu_stats"]

[influxdb]
host = "localhost"
port = "8086"
database = "isi_data_insights"

[[cluster]]
hostname = "mycluster.example.com"
username = "statsuser"
password = "password"
verify-ssl = false

[[statgroup]]
name = "cluster_cpu_stats"
update_interval = "*"
stats = [
    "cluster.cpu.sys.avg",
    "cluster.cpu.user.avg",
    "cluster.cpu.idle.avg",
    "cluster.cpu.intr.avg",
]
```

Key differences:
- Cluster credentials move from a single `clusters` line to `[[cluster]]` sections
- Stat groups use TOML array-of-tables syntax (`[[statgroup]]`)
- InfluxDB connection details move to a dedicated `[influxdb]` section
- The `active_stat_groups` list explicitly names which groups to collect
- Remove any `[composite_stats]`, `[equation_stats]`, `[percent_change_stats]`,
  or `[final_equation_stats]` sections (not supported)

### 3. Keep Your Existing InfluxDB Data

v2 writes to the same InfluxDB measurements with the same tag and field
names as v1. You can point v2 at your existing `isi_data_insights` database
and historical data will continue to appear in dashboards alongside new data.

### 4. Import New Dashboards

The v2 dashboards use modern Grafana panel types (timeseries instead of
graph, stat instead of singlestat) but query the same underlying data. Import
them from `dashboards/influxdb/` — they will work with both old and new data.

You can keep the v1 dashboards alongside the v2 ones during the transition.

### 5. Update Deployment

**v1 (Python venv):**
```bash
./isi_data_insights_d.py stop
```

**v2 (binary):**
```bash
./bin/gostats -config-file gostats.toml &
./bin/goppstats -config-file goppstats.toml &
```

Or use systemd / Docker — see [Deployment](deployment.md).

### 6. Decommission v1

Once v2 is running and dashboards look correct:

1. Stop the Python daemon: `./isi_data_insights_d.py stop`
2. Remove the Python venv and config files
3. (Optional) Archive the old repo with a pointer to the new project

## Feature Parity Reference

| Feature | v1 | v2 | Notes |
|---------|----|----|-------|
| Cluster statistics | Yes | Yes | Same stat groups |
| Multi-cluster | Yes | Yes | |
| InfluxDB v1 | Yes | Yes | |
| InfluxDB v2 | No | Yes | Via InfluxQL |
| Prometheus | Yes | Yes | |
| Partitioned Performance | No | Yes | New (goppstats) |
| Dashboard generator | No | Yes | New (dashgen) |
| Summary stats | No | Yes | Protocol, client, drive |
| Config reload | No | Yes | SIGHUP / file watcher |
| Docker | No | Yes | |
| Cross-platform binaries | No | Yes | Linux, macOS, Windows |
| Derived stats | Yes | No | Use Grafana transformations |
| Kapacitor | Yes | No | Use Grafana Alerting |
| HDFS dashboards | Yes | No | HDFS stats still collected |
| OneFS 7.2/8.0 | Yes | No | 9.x+ required |
| Concurrency dashboard | Yes | No | Recreatable in Grafana |
