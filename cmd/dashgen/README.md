# goppstats-dash-gen

A Go tool that generates Grafana dashboards for `goppstats` partitioned
performance datasets by querying the OneFS PAPI at runtime to discover the
dataset definition (attributes and metrics).

## How it works

1. Authenticates to the OneFS PAPI using session-based auth (same mechanism as goppstats)
2. Fetches the dataset definition for the specified dataset ID (tries PAPI v14 then v3)
3. Discovers the partition attributes (InfluxDB tags) and metrics (InfluxDB fields)
4. Generates a Grafana v2beta1 dashboard JSON with one time-series panel per metric

Each panel contains:
- **Query A** – normal partitioned data, `GROUP BY time, <attribute tags>`, excluding
  overflow workload_types (i.e. `workload_type !~ /./ OR workload_type = 'Pinned'`)
- **Queries B–F** – one query per overflow bucket type (`Additional`, `Excluded`,
  `Overaccounted`, `System`, `Unknown`), each gated by the `[[overflow]]` variable

The dashboard includes two template variables:
- **`cluster`** – populated at load time from `SHOW TAG VALUES WITH KEY = "cluster"`
- **`overflow`** – custom toggle (disabled=0 / enabled=1); overflow bucket queries
  use `AND [[overflow]] = 1` so they produce no data when the variable is `0`

### The overflow variable trick

Grafana's query builder has no native "show/hide query" toggle. The `[[overflow]]`
pattern embeds the variable directly into the raw InfluxDB query string. When
`$overflow = 0`, the condition `AND 0 = 1` is always false and the overflow
series returns no data. When `$overflow = 1`, the condition `AND 1 = 1` is a
no-op and the series appears. This gives a clean boolean enable/disable switch
in the dashboard UI without requiring duplicate panels.

## Build

```
go build -o goppstats-dash-gen .
```

## Usage

```
./goppstats-dash-gen \
  -host <cluster-hostname-or-ip> \
  -user <papi-username> \
  -password <papi-password> \
  -dataset <dataset-id> \
  -datasource "My InfluxDB" \
  -out dashboard.json
```

### Flags

| Flag | Default | Description |
|------|---------|-------------|
| `-host` | (required) | OneFS cluster hostname or IP |
| `-port` | `8080` | PAPI port |
| `-user` | (required) | PAPI username |
| `-password` | (required) | PAPI password |
| `-dataset` | (required) | Partitioned performance dataset ID |
| `-datasource` | (required) | Grafana datasource name shown in the datasource picker |
| `-influx-version` | `v1` | InfluxDB version: `v1` or `v2` (affects query dialect; v2/Flux not yet implemented) |
| `-out` | stdout | Output file path |
| `-skip-verify` | `false` | Skip TLS certificate verification |

### Example

```
./goppstats-dash-gen \
  -host isi911.example.com \
  -user ppstatsreader \
  -password s3kret \
  -dataset 1 \
  -datasource "isi_data_insights" \
  -out breakout-export-username.json
```

Then import `breakout-export-username.json` into Grafana via
**Dashboards → Import**.

## Known metric mappings

The generator has built-in knowledge of the following metrics for units and
aggregation functions. Unknown metrics fall back to `mean` / `short` unit.

| Metric | Title | Aggregation | Unit |
|--------|-------|-------------|------|
| `cpu` | CPU | mean | ms (after ÷1000) |
| `ops` | Operations | sum | ops |
| `latency_read` | Disk Latency (read) | mean | ms (after ÷1000) |
| `latency_write` | Disk Latency (write) | mean | ms (after ÷1000) |
| `latency_other` | Latency (other) | mean | ms (after ÷1000) |
| `throughput` | Throughput | sum | Bps |
| `read_ops` | Read Operations | sum | ops |
| `write_ops` | Write Operations | sum | ops |
| `read_bytes` | Read Bytes | sum | Bps |
| `write_bytes` | Write Bytes | sum | Bps |

## Notes

- The tool requires `ISI_PRIV_LOGIN_PAPI` and `ISI_PRIV_PERFORMANCE` privileges (same as goppstats).
- If the dataset includes `export_id` as an attribute, the tool also attempts to fetch the NFS export list (`/platform/4/protocols/nfs/exports`) to resolve IDs to paths for the dashboard description. This requires `ISI_PRIV_NFS`. Failure is non-fatal — the dashboard generates regardless, and Grafana queries will correctly use `export_path` as the tag name since that is what goppstats writes after performing its own resolution at collection time.
- The PAPI endpoint used is `/platform/10/performance/datasets/{id}`. PAPI v10 is the minimum version that exposes the partitioned performance datasets endpoint (introduced in OneFS 9). No fallback to earlier versions is attempted.
- The generated dashboard uses `apiVersion: dashboard.grafana.app/v2beta1` to match Grafana 12.x. For older Grafana installations using the classic schema (`"__inputs"` / flat `"panels"` array), the schema would need to be adapted.
- Datasource references use the datasource **name** string. If your Grafana setup requires UIDs, pass the UID as the `-datasource` flag value — they are interchangeable in the `datasource.name` field of the v2beta1 schema.
