#!/usr/bin/env python3
"""Generate the Protocol Overview dashboard for both InfluxDB and Prometheus.

Cluster-level protocol performance for a single Dell PowerScale cluster.
Shows client connections, operation mix, throughput, and latency broken
down by protocol operation, with an optional per-node breakdown section.

Generates both InfluxDB and Prometheus variants.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dashlib import *

README = """\
## PowerScale - Protocol Overview

Cluster-level protocol performance for a Dell PowerScale cluster. Select a \
protocol from the drop-down to view client connections, operation mix, \
throughput, and latency broken down by individual protocol operations.

Use the **cluster** and **protocol** selectors above to focus on the \
cluster and protocol of interest.

The **Node Breakdown** row at the bottom (collapsed by default) shows \
per-node latency, throughput, and ops/s for the selected protocol. \
This helps identify individual nodes with elevated latency or uneven \
load distribution. It requires `summary_stats.protocol = true` in the \
gostats configuration. For full per-node, per-operation analysis see the \
[Protocol Detail](/d/powerscale-protocol-detail/powerscale-protocol-detail) \
dashboard.

<details>
<summary>Protocol names (OneFS naming conventions)</summary>

| Name | Protocol |
|------|----------|
| nfs | NFS v3 |
| nfs4 | NFS v4 |
| smb1 | SMB v1 / CIFS |
| smb2 | SMB v2/v3 |
| hdfs | HDFS |
| http | HTTP/WebDAV |
| ftp | FTP |
| s3 | S3 |
| siq | SyncIQ replication |
| jobd | Job Engine |
| nlm | Network Lock Manager |
| irp | Internal |
| lsass_in | Authentication (inbound) |
| lsass_out | Authentication (outbound) |
| papi | Platform API |
| nfsrdma | NFS over RDMA |
| nfs4rdma | NFS v4 over RDMA |

</details>"""

PROTO_LIST = ["nfs", "nfs4", "smb1", "smb2", "hdfs", "http", "ftp", "s3",
              "siq", "jobd", "nlm", "irp", "lsass_in", "lsass_out", "papi",
              "nfsrdma", "nfs4rdma"]


def _th(*vals):
    steps = [{"color": GREEN_ORANGE_RED[0], "value": None}]
    for i, v in enumerate(vals):
        steps.append({"color": GREEN_ORANGE_RED[i + 1], "value": v})
    return {"mode": "absolute", "steps": steps}


HEALTH_MAPPINGS = [
    {"type": "range", "options": {"from": 0.0, "to": 0.0,
        "result": {"text": "Healthy", "index": 0}}},
    {"type": "range", "options": {"from": 0.0001, "to": 1.999,
        "result": {"text": "Attention", "index": 1}}},
    {"type": "range", "options": {"from": 2.0, "to": 5.0,
        "result": {"text": "Down", "index": 2}}},
    {"type": "value", "options": {
        "0": {"text": "Healthy", "index": 0},
        "1": {"text": "Attention", "index": 1},
        "2": {"text": "Down", "index": 2}}},
]


def generate(backend):
    ds = DS_INFLUXDB if backend == "influxdb" else DS_PROMETHEUS
    influx = (backend == "influxdb")
    tags = ["powerscale", "gostats"] + (["prometheus"] if not influx else [])

    def T(refId, iq, pq, alias=None, legend=None):
        if influx:
            return influx_target(ds, refId, iq, alias=alias)
        return prom_target(ds, refId, pq, legend=legend)

    W = '"cluster" =~ /^$cluster$/'
    C = '{cluster=~"$cluster"}'

    panels = []; pid = 1; y = 0

    # README
    panels.append(text_panel(pid, README, y, h=5, w=24)); pid += 1; y += 5

    # $cluster link
    panels.append(text_panel(pid,
        "### $cluster\n\n"
        "[Cluster Detail](/d/powerscale-cluster-detail/"
        "powerscale-cluster-detail?var-cluster=$cluster) | "
        "[WebUI](https://$cluster:8080/)",
        y, h=4, w=4, x=0, title="$cluster", transparent=True))
    pid += 1

    # Top-row stat/gauge panels
    panels.append(stat_panel(ds, pid, "Total Nodes",
        T("A",
          f'SELECT max("value") FROM "cluster.node.count.all" WHERE {W} AND $timeFilter GROUP BY time($__interval) fill(null)',
          f'isilon_stat_cluster_node_count_all{C}'),
        y=y, x=4, w=4, h=4, unit="none", thresholds=_th(1, 2), graph_mode="none"))
    pid += 1

    panels.append(stat_panel(ds, pid, "Nodes Down",
        T("A",
          f'SELECT mean("value") FROM "cluster.node.count.down" WHERE {W} AND $timeFilter GROUP BY time($__interval) fill(null)',
          f'isilon_stat_cluster_node_count_down{C}'),
        y=y, x=8, w=4, h=4, unit="none", thresholds=_th(1, 2),
        color_mode="background", calc="mean"))
    pid += 1

    panels.append(stat_panel(ds, pid, "Alert Status",
        T("A",
          f'SELECT max("value") FROM "cluster.health" WHERE {W} AND $timeFilter GROUP BY time($__interval) fill(null)',
          f'isilon_stat_cluster_health{C}'),
        y=y, x=12, w=4, h=4, unit="none", thresholds=_th(0.0001, 2),
        color_mode="background", graph_mode="none", calc="mean",
        mappings=HEALTH_MAPPINGS))
    pid += 1

    panels.append(gauge_panel(ds, pid, "Cluster CPU",
        T("A",
          f'SELECT 1.0 - mean("value")  / 1000 FROM "cluster.cpu.idle.avg" WHERE {W} AND $timeFilter GROUP BY time($__interval) fill(null)',
          f'1 - isilon_stat_cluster_cpu_idle_avg{C} / 1000'),
        y=y, x=16, w=4, h=4, unit="percentunit", min_val=0, max_val=1,
        thresholds=_th(0.8, 0.95)))
    pid += 1

    panels.append(gauge_panel(ds, pid, "Cluster Capacity Utilization",
        T("A",
          f'SELECT 100.0 - mean("value") FROM "ifs.percent.avail" WHERE {W} AND $timeFilter GROUP BY time($__interval) fill(null)',
          f'100 - isilon_stat_ifs_percent_avail{C}'),
        y=y, x=20, w=4, h=4, unit="percent", min_val=0, max_val=100,
        thresholds=_th(80, 90)))
    pid += 1
    y += 4

    # Protocol stat panels
    panels.append(stat_panel(ds, pid, "$protocol Throughput",
        T("A",
          f'SELECT max("in_rate") + mean("out_rate") FROM "cluster.protostats.$protocol.total" WHERE {W} AND $timeFilter GROUP BY time($__interval) fill(null)',
          f'isilon_stat_cluster_protostats_${{protocol}}_total_in_rate{C} + isilon_stat_cluster_protostats_${{protocol}}_total_out_rate{C}'),
        y=y, x=0, w=8, h=4, unit="Bps", thresholds=_th(10, 25)))
    pid += 1

    panels.append(stat_panel(ds, pid, "$protocol Op/s",
        T("A",
          f'SELECT max("op_rate") FROM "cluster.protostats.$protocol.total" WHERE {W} AND $timeFilter GROUP BY time($__interval) fill(null)',
          f'isilon_stat_cluster_protostats_${{protocol}}_total_op_rate{C}'),
        y=y, x=8, w=8, h=4, unit="ops", thresholds=_th(10, 25)))
    pid += 1

    panels.append(stat_panel(ds, pid, "$protocol Latency",
        T("A",
          f'SELECT max("time_avg") /1000 FROM "cluster.protostats.$protocol.total" WHERE {W} AND $timeFilter GROUP BY time($__interval) fill(null)',
          f'isilon_stat_cluster_protostats_${{protocol}}_total_time_avg{C} / 1000'),
        y=y, x=16, w=8, h=4, unit="ms", thresholds=_th(10, 25),
        color_mode="background"))
    pid += 1
    y += 4

    # Client Connections
    panels.append(timeseries_panel(ds, pid,
        "$protocol Client Connections for $cluster",
        [T("A",
           f'SELECT sum("value") FROM "node.clientstats.connected.$protocol" WHERE {W} AND $timeFilter GROUP BY time($__interval) fill(null)',
           f'sum(isilon_stat_node_clientstats_connected_${{protocol}}{C})',
           alias="Established $3 connections", legend="Established"),
         T("B",
           f'SELECT sum("value") FROM "node.clientstats.active.$protocol" WHERE {W} AND $timeFilter GROUP BY time($__interval) fill(null)',
           f'sum(isilon_stat_node_clientstats_active_${{protocol}}{C})',
           alias="Active $3 connections", legend="Active")],
        y=y, unit="short", axis_label="Connections", axis_min=0,
        show_points="always", point_size=1))
    pid += 1; y += 8

    # Protocol Operations and CPU overlay
    if influx:
        ops_cpu_targets = [
            influx_target(ds, "A",
                f'SELECT 1.0 - mean("value") / 1000.0 FROM "cluster.cpu.idle.avg" WHERE "cluster" =~ /$cluster$/ AND $timeFilter GROUP BY time($__interval) fill(null)',
                alias="CPU"),
            influx_target(ds, "E",
                f'SELECT mean("op_rate") FROM "cluster.protostats.$protocol.total" WHERE "cluster" =~ /$cluster$/ AND $timeFilter GROUP BY time($__interval) fill(null)',
                alias="$2 ops"),
        ]
        ops_cpu_overrides = [
            {"matcher": {"id": "byName", "options": "CPU"}, "properties": [
                {"id": "custom.drawStyle", "value": "line"},
                {"id": "custom.fillOpacity", "value": 0}]},
            {"matcher": {"id": "byRegexp", "options": "ops"}, "properties": [
                {"id": "custom.axisPlacement", "value": "right"},
                {"id": "unit", "value": "ops"},
                {"id": "custom.axisLabel", "value": "Protocol Operations per Second"},
                {"id": "min", "value": 0}]},
            {"matcher": {"id": "byName", "options": "CPU"}, "properties": [
                {"id": "color", "value": {"mode": "fixed", "fixedColor": "#7EB26D"}}]},
        ]
        panels.append(timeseries_panel(ds, pid,
            "Cluster $protocol Operations and CPU for $cluster",
            ops_cpu_targets, y=y, unit="percentunit",
            axis_label="CPU Busy", axis_min=0, axis_max=1,
            draw_style="bars", overrides=ops_cpu_overrides, tooltip_sort="none"))
    else:
        ops_cpu_targets = [
            prom_target(ds, "A", f'1 - isilon_stat_cluster_cpu_idle_avg{C} / 1000', "CPU"),
            prom_target(ds, "B", f'isilon_stat_cluster_protostats_${{protocol}}_total_op_rate{C}', "$protocol ops"),
        ]
        ops_cpu_overrides = [
            {"matcher": {"id": "byName", "options": "CPU"}, "properties": [
                {"id": "custom.drawStyle", "value": "line"},
                {"id": "custom.fillOpacity", "value": 0},
                {"id": "custom.axisPlacement", "value": "right"},
                {"id": "unit", "value": "percentunit"},
                {"id": "min", "value": 0}, {"id": "max", "value": 1},
                {"id": "color", "value": {"mode": "fixed", "fixedColor": "#7EB26D"}}]},
        ]
        panels.append(timeseries_panel(ds, pid,
            "Cluster $protocol Operations and CPU for $cluster",
            ops_cpu_targets, y=y, unit="ops", axis_label="Ops/s", axis_min=0,
            overrides=ops_cpu_overrides))
    pid += 1; y += 8

    # Operations Mix
    panels.append(timeseries_panel(ds, pid,
        "$protocol Operations Mix for $cluster",
        [T("A",
           f'SELECT mean("op_count") FROM "cluster.protostats.$protocol" WHERE {W} AND $timeFilter GROUP BY time($__interval), "op_name", "class_name" fill(null)',
           f'isilon_stat_cluster_protostats_${{protocol}}_op_rate{C}',
           alias="$tag_op_name ($tag_class_name)", legend="{{op_name}} ({{class_name}})"),
         T("B",
           f'SELECT sum("op_count") FROM "cluster.protostats.$protocol" WHERE {W} AND $timeFilter GROUP BY time($__interval) fill(null)',
           f'sum(isilon_stat_cluster_protostats_${{protocol}}_op_rate{C})',
           alias="Total", legend="Total")],
        y=y, unit="ops", overrides=[
            {"matcher": {"id": "byName", "options": "Total"}, "properties": [
                {"id": "custom.axisPlacement", "value": "right"},
                {"id": "unit", "value": "ops"}]}]))
    pid += 1; y += 8

    # Throughput (aggregate)
    panels.append(timeseries_panel(ds, pid,
        "$protocol Throughput for $cluster",
        [T("C",
           f'SELECT mean("in_rate") FROM "cluster.protostats.$protocol.total" WHERE {W} AND $timeFilter GROUP BY time($__interval) fill(null)',
           f'isilon_stat_cluster_protostats_${{protocol}}_total_in_rate{C}',
           alias="Write", legend="Write"),
         T("D",
           f'SELECT mean("out_rate") FROM "cluster.protostats.$protocol.total" WHERE {W} AND $timeFilter GROUP BY time($__interval) fill(null)',
           f'isilon_stat_cluster_protostats_${{protocol}}_total_out_rate{C}',
           alias="Read", legend="Read"),
         T("E",
           f'SELECT mean("out_rate") + mean("in_rate") FROM "cluster.protostats.$protocol.total" WHERE {W} AND $timeFilter GROUP BY time($__interval) fill(null)',
           f'isilon_stat_cluster_protostats_${{protocol}}_total_in_rate{C} + isilon_stat_cluster_protostats_${{protocol}}_total_out_rate{C}',
           alias="Total", legend="Total")],
        y=y, unit="Bps", axis_min=0))
    pid += 1; y += 8

    # Throughput by operation
    panels.append(timeseries_panel(ds, pid,
        "$protocol Throughput by Operation for $cluster",
        [T("A",
           f'SELECT mean("in_rate") FROM "cluster.protostats.$protocol" WHERE {W} AND $timeFilter GROUP BY time($__interval), "op_name", "class_name" fill(null)',
           f'isilon_stat_cluster_protostats_${{protocol}}_in_rate{C}',
           alias="$tag_op_name ($tag_class_name) write", legend="{{op_name}} write"),
         T("B",
           f'SELECT mean("out_rate") FROM "cluster.protostats.$protocol" WHERE {W} AND $timeFilter GROUP BY time($__interval), "op_name", "class_name" fill(null)',
           f'isilon_stat_cluster_protostats_${{protocol}}_out_rate{C}',
           alias="$tag_op_name ($tag_class_name) read", legend="{{op_name}} read")],
        y=y, unit="Bps", axis_min=0))
    pid += 1; y += 8

    # Average Latency (aggregate avg/max/min)
    panels.append(timeseries_panel(ds, pid,
        "Average Latency for all $protocol Operations for $cluster",
        [T("A",
           f'SELECT mean("time_avg") FROM "cluster.protostats.$protocol.total" WHERE {W} AND $timeFilter GROUP BY time($__interval) fill(null)',
           f'isilon_stat_cluster_protostats_${{protocol}}_total_time_avg{C}',
           alias="$2 avg", legend="$protocol avg"),
         T("C",
           f'SELECT mean("time_max") FROM "cluster.protostats.$protocol.total" WHERE {W} AND $timeFilter GROUP BY time($__interval) fill(null)',
           f'isilon_stat_cluster_protostats_${{protocol}}_total_time_max{C}',
           alias="$2 max", legend="$protocol max"),
         T("B",
           f'SELECT mean("time_min") FROM "cluster.protostats.$protocol.total" WHERE {W} AND $timeFilter GROUP BY time($__interval) fill(null)',
           f'isilon_stat_cluster_protostats_${{protocol}}_total_time_min{C}',
           alias="$2 min", legend="$protocol min")],
        y=y, unit="\u00b5s", axis_label="Latency", axis_min=0,
        draw_style="bars", show_points="always", point_size=1, tooltip_sort="none"))
    pid += 1; y += 8

    # Average Latency by operation
    panels.append(timeseries_panel(ds, pid,
        "Average Latency by $protocol Operation for $cluster",
        [T("A",
           f'SELECT mean("time_avg") / 1000 FROM "cluster.protostats.$protocol" WHERE {W} AND $timeFilter GROUP BY time($__interval), "class_name", "op_name" fill(null)',
           f'isilon_stat_cluster_protostats_${{protocol}}_time_avg{C} / 1000',
           alias="$tag_op_name ($tag_class_name)", legend="{{op_name}} ({{class_name}})")],
        y=y, unit="ms", axis_min=0))
    pid += 1; y += 8

    # Maximum Latency by operation
    panels.append(timeseries_panel(ds, pid,
        "Maximum Latency by $protocol Operation for $cluster",
        [T("A",
           f'SELECT mean("time_max") / 1000 FROM "cluster.protostats.$protocol" WHERE {W} AND $timeFilter GROUP BY time($__interval), "class_name", "op_name" fill(null)',
           f'isilon_stat_cluster_protostats_${{protocol}}_time_max{C} / 1000',
           alias="$tag_op_name ($tag_class_name)", legend="{{op_name}} ({{class_name}})")],
        y=y, unit="ms", axis_min=0))
    pid += 1; y += 8

    # ── Node Breakdown (collapsed row) ────────────────────────────────
    # Uses node.summary.protocol data (requires summary_stats.protocol = true).
    # Aggregates per-operation data to show per-node totals for the selected protocol.
    NSP = '{cluster=~"$cluster", protocol=~"$protocol"}'
    inner = []; iy = y + 1; ipid = pid + 1

    inner.append(timeseries_panel(ds, ipid,
        "Per-Node $protocol Latency for $cluster",
        [T("A",
           f'SELECT max("time_avg") / 1000 FROM "node.summary.protocol" WHERE {W} AND "protocol" =~ /^$protocol$/ AND $timeFilter GROUP BY time($__interval), "node" fill(null)',
           f'max by (node) (isilon_stat_node_summary_protocol_time_avg{NSP}) / 1000',
           alias="Node $tag_node", legend="{{node}}")],
        y=iy, unit="ms", axis_label="Latency", axis_min=0))
    ipid += 1; iy += 8

    inner.append(timeseries_panel(ds, ipid,
        "Per-Node $protocol Throughput for $cluster",
        [T("A",
           f'SELECT sum("in") + sum("out") FROM "node.summary.protocol" WHERE {W} AND "protocol" =~ /^$protocol$/ AND $timeFilter GROUP BY time($__interval), "node" fill(null)',
           f'sum by (node) (isilon_stat_node_summary_protocol_in{NSP}) + sum by (node) (isilon_stat_node_summary_protocol_out{NSP})',
           alias="Node $tag_node", legend="{{node}}")],
        y=iy, unit="Bps", axis_min=0))
    ipid += 1; iy += 8

    inner.append(timeseries_panel(ds, ipid,
        "Per-Node $protocol Ops/s for $cluster",
        [T("A",
           f'SELECT sum("operation_rate") FROM "node.summary.protocol" WHERE {W} AND "protocol" =~ /^$protocol$/ AND $timeFilter GROUP BY time($__interval), "node" fill(null)',
           f'sum by (node) (isilon_stat_node_summary_protocol_operation_rate{NSP})',
           alias="Node $tag_node", legend="{{node}}")],
        y=iy, unit="ops", axis_min=0))
    ipid += 1; iy += 8

    panels.append(row_panel(pid, "Node Breakdown (summary_stats.protocol)", y,
                            collapsed=True, panels=inner))
    pid = ipid; y = iy

    # Template variables
    proto_default = "nfs"
    if influx:
        variables = [
            var_query(ds, "cluster", "Cluster",
                      'SHOW TAG VALUES WITH KEY = "cluster"', sort=1),
        ]
    else:
        variables = [
            var_query(ds, "cluster", "Cluster",
                      'label_values(isilon_stat_cluster_health, cluster)'),
        ]
    variables.append(var_custom("protocol", "Protocol", PROTO_LIST, default=proto_default))

    dash = make_dashboard(
        title="PowerScale - Protocol Overview",
        description="Cluster-level protocol performance for a Dell PowerScale cluster",
        tags=tags, variables=variables, panels=panels,
        time_from="now-1h", refresh="",
    )
    write_dashboard(dash, outpath(backend, "cluster_protocol.json"))


if __name__ == "__main__":
    for b in ("influxdb", "prometheus"):
        print(f"\n=== {b} ===")
        generate(b)
