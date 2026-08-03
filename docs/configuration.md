# Configuration Reference

Both gostats and goppstats use TOML configuration files. This document
covers every option for both collectors, plus the dashgen CLI flags.

Example configs are provided in `configs/` (bare-metal) and `docker/`
(Docker Compose, with stdout logging and InfluxDB host pre-set).

## Environment Variable Substitution

Password and token fields support `$env:VARNAME` syntax. If a value starts
with `$env:`, the remainder is looked up as an environment variable:

```toml
password = "$env:CLUSTER_PASS"       # reads $CLUSTER_PASS from environment
access_token = "$env:INFLUX_TOKEN"   # reads $INFLUX_TOKEN from environment
```

If the environment variable is not set, the collector exits with an error.
Fields that support this are marked with **$env** below.

## CLI Flags

### gostats

```
gostats [flags]
  -config-file string   Pathname of config file (default "idic.toml")
  -logfile string       Pathname of log file (overrides config)
  -loglevel string      Log level (overrides config): TRACE|DEBUG|INFO|NOTICE|WARN|ERROR|CRITICAL
  -check-stat-return    Verify API returns results for every requested stat (debugging)
  -version              Print version and exit
```

### goppstats

```
goppstats [flags]
  -config-file string   Pathname of config file (default "goppstats.toml")
  -logfile string       Pathname of log file (overrides config)
  -loglevel string      Log level (overrides config): TRACE|DEBUG|INFO|NOTICE|WARN|ERROR|CRITICAL
  -version              Print version and exit
```

### dashgen

```
dashgen [flags]
  -host string          OneFS cluster hostname or IP (required)
  -port int             PAPI port (default 8080)
  -user string          PAPI username (required)
  -password string      PAPI password (required)
  -dataset int          Partitioned Performance dataset ID (required)
  -influx-version string  InfluxDB version: v1 or v2 (default "v1")
  -out string           Output file path (default: stdout)
  -skip-verify          Skip TLS certificate verification
  -export-path          Group by export_path instead of export_id
                        (use when collector has lookup_export_ids=true)
```

---

## TOML Configuration: gostats

### [global]

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `version` | string | *required* | Config format version (e.g., `"v0.40"`) |
| `stats_processor` | string | `"influxdb"` | Backend: `"influxdb"`, `"influxdbv2"`, `"prometheus"`, `"discard"` |
| `stats_processor_max_retries` | int | `8` | Max retries for backend writes; `0` = retry forever |
| `stats_processor_retry_interval` | int | `5` | Initial retry interval in seconds (exponential backoff) |
| `max_retries` | int | `8` | Max retries for PAPI HTTP requests; `0` = retry forever |
| `min_update_interval_override` | int | `5` | Minimum stat query interval in seconds |
| `preserve_case` | bool | `false` | Preserve cluster name casing; when false, names are lowercased |
| `include_degraded` | bool | `false` | Add a `degraded` tag to metrics |
| `fetch_by_statgroup` | bool | `false` | Fetch one stat group per request instead of batching by interval |
| `stat_timeout` | int | `0` | Value (seconds) sent as the OneFS `timeout` query parameter, bounding how long the cluster waits for results from remote nodes before returning a per-stat timeout (`errorcode=6`); `0` omits it and uses the cluster default |
| `stat_retries` | int | `2` | Extra attempts, within a single collection cycle, to re-query only the stat keys that returned transient per-stat errors (timeout/stale/etc.); `0` disables per-stat retry |
| `stat_retry_interval` | int | `2` | Initial delay in seconds between per-stat transient retries within a cycle (exponential backoff) |
| `active_stat_groups` | array | *required* | List of stat group names to collect |

#### Transient per-stat failures

The OneFS `statistics/current` endpoint can return successful results and
per-stat errors in the same response. A failure can also affect only one node
for a stat key. When an error is transient, `gostats` preserves every successful
result and re-queries only the affected stat keys. A recovered `(stat key,
device ID)` result replaces its failed value; successful values are never
overwritten by a retry failure.

`stat_retries` counts additional attempts within the current collection cycle.
The delay starts at `stat_retry_interval` and doubles for each attempt. With the
defaults, the collector waits 2 seconds and then 4 seconds, for up to 6 seconds
of backoff plus the request time. Transport-level PAPI retries remain controlled
separately by `max_retries`.

Increasing `stat_timeout` gives OneFS more time to gather remote-node results,
but can keep each request active longer. Increasing the retry count or interval
can extend a collection cycle, and retries add PAPI traffic. Tune these settings
conservatively on busy or large clusters.

These options are additive and existing configuration files remain valid. To
restore the previous behavior, disable targeted retries and use strict
Prometheus expiry:

```toml
[global]
stat_retries = 0

[prometheus]
expiry_multiplier = 1
```

The default `stat_timeout = 0` already preserves the previous OneFS timeout
behavior by omitting the query parameter.

### [logging]

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `logfile` | string | `""` | Log file path; empty = no file logging |
| `logfile_format` | string | `"text"` | Log format: `"text"` or `"json"` |
| `log_level` | string | `"NOTICE"` | Log level: `TRACE`, `DEBUG`, `INFO`, `NOTICE`, `WARN`, `ERROR`, `CRITICAL` |
| `log_to_stdout` | bool | `false` | Also log to stdout (set `true` for containers) |

### [influxdb]

Used when `stats_processor = "influxdb"`.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `host` | string | `"localhost"` | InfluxDB hostname |
| `port` | string | `"8086"` | InfluxDB port |
| `database` | string | *required* | Database name |
| `authenticated` | bool | `false` | Enable authentication |
| `username` | string | `""` | InfluxDB username |
| `password` | string | `""` | InfluxDB password **$env** |
| `use_ssl` | bool | `false` | Connect via HTTPS |
| `skip_ssl_verify` | bool | `false` | Skip TLS certificate verification |

### [influxdbv2]

Used when `stats_processor = "influxdbv2"`.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `host` | string | `"localhost"` | InfluxDB v2 hostname |
| `port` | string | `"8086"` | InfluxDB v2 port |
| `org` | string | *required* | Organization name |
| `bucket` | string | *required* | Bucket name |
| `access_token` | string | *required* | API access token **$env** |
| `use_ssl` | bool | `false` | Connect via HTTPS |
| `skip_ssl_verify` | bool | `false` | Skip TLS certificate verification |

### [prometheus]

Used when `stats_processor = "prometheus"`.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `authenticated` | bool | `false` | Enable basic auth on the `/metrics` endpoint |
| `username` | string | `""` | Basic auth username |
| `password` | string | `""` | Basic auth password **$env** |
| `tls_cert` | string | `""` | Path to TLS certificate |
| `tls_key` | string | `""` | Path to TLS private key |
| `instance_label_name` | string | | Additional label for the cluster name (avoids conflicts with Prometheus external labels) |
| `expiry_multiplier` | float | `2` | Multiplies each sample's expiry (based on the stat's update interval) so a single missed/timed-out collection does not immediately expire the series and create a scrape gap; clamped to `>= 1` |

### [prom_http_sd]

Prometheus HTTP service discovery endpoint. Only relevant when using the
Prometheus backend.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | bool | `false` | Enable HTTP SD endpoint |
| `listen_addr` | string | auto-detect | Hostname/IP to advertise |
| `sd_port` | int | `9999` | Port for the SD endpoint |

### [[cluster]]

One section per OneFS cluster to monitor. Multiple `[[cluster]]` sections
are supported.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `hostname` | string | *required* | Cluster hostname or IP |
| `username` | string | *required* | PAPI username |
| `password` | string | *required* | PAPI password **$env** |
| `authtype` | string | `"session"` | Authentication: `"session"` or `"basic-auth"` |
| `verify-ssl` | bool | `true` | Verify TLS certificates |
| `disabled` | bool | `false` | Skip this cluster |
| `prometheus_port` | int | | Per-cluster Prometheus listener port |
| `preserve_case` | bool | | Override the global `preserve_case` setting |

### [summary_stats]

Enable collection of OneFS summary statistics (PAPI v3). These provide
pre-aggregated per-protocol, per-client, and per-drive breakdowns.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `protocol` | bool | `false` | Collect protocol summary stats |
| `client` | bool | `false` | Collect client summary stats |
| `drive` | bool | `false` | Collect drive summary stats |

### [[statgroup]]

Defines a group of statistics to collect. Each group listed in
`active_stat_groups` must have a corresponding `[[statgroup]]` section.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | string | *required* | Group name (matches entry in `active_stat_groups`) |
| `update_interval` | string | *required* | Collection interval: `"*"` (stat's native interval), `"*N"` (N times native), or `"N"` (N seconds) |
| `stats` | array | *required* | List of PAPI stat keys to collect |

---

## TOML Configuration: goppstats

goppstats shares the same `[logging]`, `[influxdb]`, `[influxdbv2]`,
`[prometheus]`, `[prom_http_sd]`, and `[[cluster]]` sections as gostats.
Only the `[global]` section differs.

### [global]

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `version` | string | *required* | Config format version (e.g., `"v0.29"`) |
| `stats_processor` | string | `"influxdb"` | Backend: `"influxdb"`, `"influxdbv2"`, `"prometheus"`, `"discard"` |
| `stats_processor_max_retries` | int | `8` | Max retries for backend writes; `0` = retry forever |
| `stats_processor_retry_interval` | int | `5` | Initial retry interval in seconds |
| `max_retries` | int | `8` | Max retries for PAPI HTTP requests; `0` = retry forever |
| `min_update_interval_override` | int | `30` | Minimum query interval in seconds |
| `preserve_case` | bool | `false` | Preserve cluster name casing |
| `lookup_export_ids` | bool | `false` | Resolve NFS export IDs to paths (requires `ISI_PRIV_NFS`) |

goppstats does not have `active_stat_groups`, `[[statgroup]]`, or
`[summary_stats]` sections — it automatically discovers and collects all
Partitioned Performance datasets defined on each cluster.

---

## Configuration Reload

Both collectors support live configuration reload without restarting:

- **SIGHUP signal:** `kill -HUP <pid>`
- **File watcher:** changes to the config file are detected automatically
  (with debounce to handle editors that write atomically via temp files)

## Minimal Example

A minimal gostats config to get started:

```toml
[global]
version = "v0.40"
stats_processor = "influxdb"
active_stat_groups = ["cluster_health_stats"]

[logging]
log_to_stdout = true

[influxdb]
host = "localhost"
port = "8086"
database = "isi_data_insights"

[[cluster]]
hostname = "mycluster.example.com"
username = "statsuser"
password = "$env:CLUSTER_PASS"
verify-ssl = false

[[statgroup]]
name = "cluster_health_stats"
update_interval = "*"
stats = [
    "cluster.health",
    "cluster.node.count.all",
    "cluster.node.count.down",
]
```
