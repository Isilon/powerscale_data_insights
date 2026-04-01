#!/usr/bin/env python3
"""Generate the Protocol Summary Statistics dashboard.

Uses node.summary.protocol data which provides per-node, per-protocol,
per-operation breakdowns with full latency statistics (avg/min/max/stddev).

This is distinct from the Protocol Detail dashboard which uses
cluster.protostats.* (cluster-level aggregates without per-operation
latency distribution).

Generates both InfluxDB and Prometheus variants.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dashlib import *

README = """\
## PowerScale - Protocol Summary Stats

Per-node, per-operation protocol statistics with latency distribution \
(avg/min/max/stddev) from OneFS summary statistics.

Requires `protocol = true` in the `[summary_stats]` section of the \
gostats collector configuration."""

MEAS = "node.summary.protocol"  # InfluxDB measurement
M    = "isilon_stat_node_summary_protocol"  # Prometheus metric prefix

# Protocol list matches OneFS isi statistics protocol list --protocols
PROTOCOLS = "nfs3,nfs4,smb1,smb2,nlm,ftp,http,siq,jobd,irp,lsass_in,lsass_out,papi,hdfs,s3,nfsrdma,nfs4rdma"


def generate(backend):
    ds = DS_INFLUXDB if backend == "influxdb" else DS_PROMETHEUS
    influx = (backend == "influxdb")
    tags = ["powerscale", "gostats", "summary"] + (["prometheus"] if not influx else [])

    def T(refId, iq, pq, alias=None, legend=None):
        if influx:
            return influx_target(ds, refId, iq, alias=alias)
        return prom_target(ds, refId, pq, legend=legend)

    W = ('"cluster"::tag =~ /^$cluster$/ AND "node"::tag =~ /^$node$/ '
         'AND "protocol" = \'$protocol\'') if influx else ""
    C = '{cluster=~"$cluster",node=~"$node",protocol=~"$protocol"}'

    panels = []; pid = 1; y = 0

    # ── README panel ──
    panels.append(text_panel(pid, README, y, h=4)); pid += 1; y += 4

    # ── Overview stats ──
    for i, (title, iq, pq, unit, dec) in enumerate([
        ("$protocol Ops/s",
         f'SELECT sum("operation_rate") FROM "{MEAS}" WHERE {W} AND $timeFilter GROUP BY time($__interval) fill(null)' if influx else "",
         f'sum({M}_operation_rate{C})', "ops", 0),
        ("$protocol Avg Latency",
         f'SELECT mean("time_avg") / 1000 FROM "{MEAS}" WHERE {W} AND $timeFilter GROUP BY time($__interval) fill(null)' if influx else "",
         f'avg({M}_time_avg{C}) / 1000', "ms", 2),
        ("$protocol Inbound",
         f'SELECT sum("in") FROM "{MEAS}" WHERE {W} AND $timeFilter GROUP BY time($__interval) fill(null)' if influx else "",
         f'sum({M}_in{C})', "Bps", None),
        ("$protocol Outbound",
         f'SELECT sum("out") FROM "{MEAS}" WHERE {W} AND $timeFilter GROUP BY time($__interval) fill(null)' if influx else "",
         f'sum({M}_out{C})', "Bps", None),
    ]):
        panels.append(stat_panel(ds, pid, title,
                                 T("A", iq, pq),
                                 y=y, x=i*6, w=6, h=4, unit=unit, decimals=dec))
        pid += 1
    y += 4

    def _iq(agg, field, scale="", group_tag=None):
        gb = f', "{group_tag}"::tag' if group_tag else ""
        return (f'SELECT {agg}("{field}"){scale} FROM "{MEAS}" '
                f'WHERE {W} AND $timeFilter '
                f'GROUP BY time($__interval){gb} fill(null)')

    ts_panels = [
        ("$protocol Operation Rate by Class",
         [T("A", _iq("sum", "operation_rate", group_tag="class"),
            f'sum by (class) ({M}_operation_rate{C})',
            alias="$tag_class", legend="{{class}}")],
         "ops", "Ops/s"),
        ("$protocol Operation Rate by Operation",
         [T("A", _iq("sum", "operation_rate", group_tag="operation"),
            f'sum by (operation) ({M}_operation_rate{C})',
            alias="$tag_operation", legend="{{operation}}")],
         "ops", "Ops/s"),
        ("$protocol Average Latency by Class",
         [T("A", _iq("mean", "time_avg", " / 1000", group_tag="class"),
            f'avg by (class) ({M}_time_avg{C}) / 1000',
            alias="$tag_class", legend="{{class}}")],
         "ms", "Latency"),
        ("$protocol Average Latency by Operation",
         [T("A", _iq("mean", "time_avg", " / 1000", group_tag="operation"),
            f'avg by (operation) ({M}_time_avg{C}) / 1000',
            alias="$tag_operation", legend="{{operation}}")],
         "ms", "Latency"),
        ("$protocol Latency Distribution (Avg / Max / Min / StdDev)",
         [T("A", _iq("mean", "time_avg", " / 1000"),
            f'avg({M}_time_avg{C}) / 1000',
            alias="Average", legend="Average"),
          T("B", _iq("mean", "time_max", " / 1000"),
            f'avg({M}_time_max{C}) / 1000',
            alias="Maximum", legend="Maximum"),
          T("C", _iq("mean", "time_min", " / 1000"),
            f'avg({M}_time_min{C}) / 1000',
            alias="Minimum", legend="Minimum"),
          T("D", _iq("mean", "time_standard_dev", " / 1000"),
            f'avg({M}_time_standard_dev{C}) / 1000',
            alias="Std Dev", legend="Std Dev")],
         "ms", "Latency"),
        ("$protocol Inbound (Write) Throughput by Operation",
         [T("A", _iq("sum", "in", group_tag="operation"),
            f'sum by (operation) ({M}_in{C})',
            alias="$tag_operation", legend="{{operation}}")],
         "Bps", "Throughput"),
        ("$protocol Outbound (Read) Throughput by Operation",
         [T("A", _iq("sum", "out", group_tag="operation"),
            f'sum by (operation) ({M}_out{C})',
            alias="$tag_operation", legend="{{operation}}")],
         "Bps", "Throughput"),
        ("$protocol Operation Rate by Node",
         [T("A", _iq("sum", "operation_rate", group_tag="node"),
            f'sum by (node) ({M}_operation_rate{C})',
            alias="Node $tag_node", legend="Node {{node}}")],
         "ops", "Ops/s"),
        ("$protocol Average Latency by Node",
         [T("A", _iq("mean", "time_avg", " / 1000", group_tag="node"),
            f'avg by (node) ({M}_time_avg{C}) / 1000',
            alias="Node $tag_node", legend="Node {{node}}")],
         "ms", "Latency"),
    ]

    for title, targets, unit, axis_label in ts_panels:
        panels.append(timeseries_panel(ds, pid, title, targets,
                                       y=y, unit=unit,
                                       axis_label=axis_label, axis_min=0))
        pid += 1; y += 8

    if influx:
        variables = [
            var_query(ds, "cluster", "Cluster",
                      'SHOW TAG VALUES WITH KEY = "cluster"'),
            var_custom("protocol", "Protocol",
                       PROTOCOLS.split(","), default="nfs3"),
            var_query(ds, "node", "Node",
                      f'SHOW TAG VALUES FROM "{MEAS}" WITH KEY = "node" '
                      f'WHERE "cluster" =~ /^$cluster$/',
                      multi=True, include_all=True),
        ]
    else:
        variables = [
            var_query(ds, "cluster", "Cluster",
                      f'label_values({M}_operation_rate, cluster)'),
            var_query(ds, "protocol", "Protocol",
                      f'label_values({M}_operation_rate{{cluster=~"$cluster"}}, protocol)'),
            var_query(ds, "node", "Node",
                      f'label_values({M}_operation_rate{{cluster=~"$cluster"}}, node)',
                      multi=True, include_all=True),
        ]

    dash = make_dashboard(
        title="PowerScale - Protocol Summary Stats",
        description="Per-node, per-operation protocol statistics with latency "
                    "distribution (avg/min/max/stddev). Uses OneFS summary statistics.",
        tags=tags,
        variables=variables,
        panels=panels,
    )
    write_dashboard(dash, outpath(backend, "protocol_summary.json"))


if __name__ == "__main__":
    for b in ("influxdb", "prometheus"):
        print(f"\n=== {b} ===")
        generate(b)
