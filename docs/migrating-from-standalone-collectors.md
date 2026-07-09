# Migrating from Standalone gostats / goppstats

This guide is for users who are already running the standalone Go collectors
([gostats](https://github.com/tenortim/gostats) and/or
[goppstats](https://github.com/tenortim/goppstats)) and are moving to the
[PowerScale Data Insights](https://github.com/Isilon/powerscale_data_insights)
monorepo — likely because they also want the updated dashboards or the new
`dashgen` tool.

If you are migrating from the original Python-based
[Isilon Data Insights Connector](https://github.com/Isilon/isilon_data_insights_connector),
see [Migrating from v1](migrating-from-v1.md) instead.

## What's Changing

The collectors themselves are the same code, now maintained in one place.
The main reasons to migrate are:

- **Updated dashboards** — modern Grafana panel types (timeseries, stat,
  table) that replace the old graph/singlestat panels from the v1 connector
  era. New dashboards cover areas not addressed by the old set: drive detail,
  drive summary, protocol summary, client summary, and system workload.
- **dashgen** — a new tool that generates Grafana dashboards tailored to your
  specific Partitioned Performance dataset definitions.
- **Single source of truth** — future development (bugfixes, new features)
  happens in the monorepo. The standalone repos are no longer actively
  maintained.

## What's NOT Changing

| Area | Detail |
|------|--------|
| Config format | TOML — same syntax, same fields |
| Config version | gostats v0.31+ and goppstats v0.29+ configs work as-is |
| InfluxDB data | Same measurement names, tags, and field names — all historical data continues to work |
| Collector behaviour | Same collection intervals, stat groups, and backend support |
| Process management | Same flags, signals (SIGHUP reload), and systemd integration |

Your existing config files **do not need to be changed** if you are running
gostats v0.31 or later, or goppstats v0.29 or later.

If your config carries an older `version =` value, update it to the current
version (`"v0.39"` for gostats, `"v0.29"` for goppstats) after reviewing the
changelogs for any breaking changes that affect your configuration.

## Migration Steps

### 1. Get the New Binaries

**Option A — Build from source:**

```bash
git clone https://github.com/Isilon/powerscale_data_insights.git
cd powerscale_data_insights
make build
# Produces bin/gostats, bin/goppstats, bin/dashgen
```

**Option B — Download a release:**

Download the latest release from the
[GitHub Releases](https://github.com/Isilon/powerscale_data_insights/releases)
page for your platform.

**Option C — Install system-wide from source:**

```bash
make build
sudo make install
# Installs to /usr/local/bin/ and /etc/powerscale-data-insights/
```

### 2. Verify Config Compatibility

Your existing configs will load without changes if they are at a compatible
version. Run the new binary with `-version` to confirm the version, and check
your config `version =` field:

| Collector | Minimum compatible config version |
|-----------|-----------------------------------|
| gostats   | `"v0.31"` or `"0.31"`            |
| goppstats | `"v0.29"` or `"0.29"`            |

If your config is at an older version, compare it against the example config
in `configs/` and update accordingly. The changelogs in
`cmd/gostats/Changelog.md` and `cmd/goppstats/Changelog.md` document all
breaking changes.

### 3. Stop the Old Collectors

```bash
# If running under systemd (standalone service names may vary)
sudo systemctl stop gostats goppstats

# If running directly
kill $(pgrep gostats) $(pgrep goppstats)
```

### 4. Start the New Collectors

Point the new binaries at your existing config files:

```bash
# Binary in /usr/local/bin, config in place from old install
gostats -config-file /path/to/your/gostats.toml
goppstats -config-file /path/to/your/goppstats.toml
```

Or via systemd — see [Deployment](deployment.md) for service file details, or
run `sudo make install-systemd` to install the included service files.

### 5. Import the New Dashboards

The old v1-era dashboards used `graph` and `singlestat` panel types that
Grafana has deprecated. The v2 dashboards replace them with `timeseries`,
`stat`, and `table` panels and cover more of the available data.

The underlying InfluxDB data format is unchanged, so both old and new
dashboards will work against the same data. You can import the new ones
alongside your existing dashboards and switch over at your own pace.

In Grafana:
1. Go to **Dashboards → Import**
2. Upload each JSON file from `dashboards/import/influxdb/` (or
   `dashboards/import/prometheus/` if you use Prometheus) — use the
   `import/` copies, not the plain `dashboards/influxdb/` ones, since only
   the `import/` copies carry the metadata that makes Grafana prompt for a
   datasource (see [Importing Dashboards](dashboards.md#importing-dashboards))
3. Select your datasource when prompted

| New Dashboard | Replaces / Description |
|---------------|------------------------|
| PowerScale - Cluster List | Multi-cluster health, CPU, capacity, protocol overview |
| PowerScale - Cluster Detail | Single-cluster deep dive: CPU, network, disk, cache, protocols |
| PowerScale - Cluster Capacity | Storage utilization across clusters |
| PowerScale - Protocol Overview | Cluster-level protocol performance, with per-node breakdown |
| PowerScale - System Workload | Node-level workload and concurrency |
| PowerScale - Protocol Summary | Per-protocol aggregate statistics |
| PowerScale - Client Summary | Active client counts by protocol |
| PowerScale - Drive Stats | Per-node disk latency and throughput |
| PowerScale - Drive Summary | Cluster-wide drive health overview |

### 6. Generate PP Dashboards with dashgen (Optional)

If you run goppstats, the `dashgen` tool generates dashboards that reflect
your actual Partitioned Performance dataset definitions:

```bash
dashgen \
  -host your-cluster.example.com \
  -user statsuser \
  -password your-password \
  -dataset 1 \
  -out pp-dataset-1.json
```

Import the resulting JSON file into Grafana. Run `dashgen -help` for all options,
or see [Dashboards](dashboards.md) for a full usage guide.

### 7. Decommission the Standalone Installs

Once the new collectors are running and dashboards look correct:

1. Remove the old binaries (e.g. from `~/go/bin/` or wherever they were installed)
2. Remove or archive the standalone repo clones
3. Update any monitoring or alerting that checks for the old process names
   (process name is unchanged: `gostats` and `goppstats`)

## Summary

| Step | Effort |
|------|--------|
| Binaries | Replace with monorepo build or release download |
| Config files | No changes needed (v0.31+/v0.29+ configs are compatible) |
| InfluxDB data | No changes — historical data works immediately |
| Old dashboards | Keep running during transition; import new ones when ready |
| dashgen | New capability — optional |
