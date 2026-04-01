#!/usr/bin/env python3
"""Generate the System Workload (PP Dataset 0) dashboard.

Dataset 0 ("System") is a predefined PP dataset present on all OneFS 9.x+
clusters. It breaks down resource consumption by system_name (OneFS daemon/
process) and node.

Generates both InfluxDB and Prometheus variants.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dashlib import *

README = """\
## PowerScale - System Workload (PP Dataset 0)

OneFS system process resource consumption from Partitioned Performance
Dataset 0. This dataset is predefined and always available on OneFS 9.x+ \
clusters — no PP dataset configuration needed.

Shows which daemons and system processes consume CPU, perform I/O, and \
generate latency. Useful for identifying runaway system processes."""

MEAS = "cluster.performance.dataset.0"  # InfluxDB measurement
M    = "isilon_ppstat_job_type_system_name"  # Prometheus metric prefix

# Normal data filter (exclude overflow workload_type buckets)
NORMAL = '("workload_type"::tag !~ /./ OR "workload_type"::tag = \'Pinned\')'


def generate(backend):
    ds = DS_INFLUXDB if backend == "influxdb" else DS_PROMETHEUS
    influx = (backend == "influxdb")
    tags = ["powerscale", "goppstats"] + (["prometheus"] if not influx else [])

    # Shorthand: build target for the active backend
    def T(refId, iq, pq, alias=None, legend=None, **kw):
        if influx:
            return influx_target(ds, refId, iq, alias=alias, **kw)
        return prom_target(ds, refId, pq, legend=legend)

    # WHERE clause fragments
    W = (f'"cluster"::tag =~ /^$cluster$/ AND "node"::tag =~ /^$node$/ '
         f'AND {NORMAL}') if influx else ""
    C = '{cluster=~"$cluster",node=~"$node"}'  # Prometheus label matcher

    panels = []; pid = 1; y = 0

    # ── README panel ──
    panels.append(text_panel(pid, README, y, h=4)); pid += 1; y += 4

    # ── Overview stats ──
    for i, (title, iq, pq, unit, dec) in enumerate([
        ("Total CPU",
         f'SELECT sum("cpu") / 1000 FROM "{MEAS}" WHERE {W} AND $timeFilter GROUP BY time($__interval) fill(null)' if influx else "",
         f'sum({M}_cpu{C}) / 1000', "ms", 0),
        ("Total Ops",
         f'SELECT sum("ops") FROM "{MEAS}" WHERE {W} AND $timeFilter GROUP BY time($__interval) fill(null)' if influx else "",
         f'sum({M}_ops{C})', "ops", 0),
        ("Total Bytes In",
         f'SELECT sum("bytes_in") FROM "{MEAS}" WHERE {W} AND $timeFilter GROUP BY time($__interval) fill(null)' if influx else "",
         f'sum({M}_bytes_in{C})', "Bps", None),
        ("Total Bytes Out",
         f'SELECT sum("bytes_out") FROM "{MEAS}" WHERE {W} AND $timeFilter GROUP BY time($__interval) fill(null)' if influx else "",
         f'sum({M}_bytes_out{C})', "Bps", None),
    ]):
        panels.append(stat_panel(ds, pid, title,
                                 T("A", iq, pq),
                                 y=y, x=i*6, w=6, h=4, unit=unit, decimals=dec))
        pid += 1
    y += 4

    # ── Timeseries panels (one metric per panel, grouped by system_name) ──
    def _iq_by_sysname(agg, field, scale=""):
        return (f'SELECT {agg}("{field}"){scale} FROM "{MEAS}" '
                f'WHERE {W} AND $timeFilter '
                f'GROUP BY time($__interval), "system_name"::tag fill(null)')

    ts_panels = [
        ("CPU by System Process",
         [T("A", _iq_by_sysname("sum", "cpu", " / 1000"),
                 f'sum by (system_name) ({M}_cpu{C}) / 1000',
                 alias="$tag_system_name", legend="{{system_name}}")],
         "ms"),
        ("Operations by System Process",
         [T("A", _iq_by_sysname("sum", "ops"),
                 f'sum by (system_name) ({M}_ops{C})',
                 alias="$tag_system_name", legend="{{system_name}}")],
         "ops"),
        ("Reads and Writes by System Process",
         [T("A", _iq_by_sysname("sum", "reads"),
                 f'sum by (system_name) ({M}_reads{C})',
                 alias="$tag_system_name reads", legend="{{system_name}} reads"),
          T("B", _iq_by_sysname("sum", "writes"),
                 f'sum by (system_name) ({M}_writes{C})',
                 alias="$tag_system_name writes", legend="{{system_name}} writes")],
         "short"),
        ("Bytes In (Write) by System Process",
         [T("A", _iq_by_sysname("sum", "bytes_in"),
                 f'sum by (system_name) ({M}_bytes_in{C})',
                 alias="$tag_system_name", legend="{{system_name}}")],
         "Bps"),
        ("Bytes Out (Read) by System Process",
         [T("A", _iq_by_sysname("sum", "bytes_out"),
                 f'sum by (system_name) ({M}_bytes_out{C})',
                 alias="$tag_system_name", legend="{{system_name}}")],
         "Bps"),
        ("Read Latency by System Process",
         [T("A", _iq_by_sysname("mean", "latency_read", " / 1000"),
                 f'avg by (system_name) ({M}_latency_read{C}) / 1000',
                 alias="$tag_system_name", legend="{{system_name}}")],
         "ms"),
        ("Write Latency by System Process",
         [T("A", _iq_by_sysname("mean", "latency_write", " / 1000"),
                 f'avg by (system_name) ({M}_latency_write{C}) / 1000',
                 alias="$tag_system_name", legend="{{system_name}}")],
         "ms"),
        ("Other Latency by System Process",
         [T("A", _iq_by_sysname("mean", "latency_other", " / 1000"),
                 f'avg by (system_name) ({M}_latency_other{C}) / 1000',
                 alias="$tag_system_name", legend="{{system_name}}")],
         "ms"),
        ("L2 Cache Hits by System Process",
         [T("A", _iq_by_sysname("sum", "l2"),
                 f'sum by (system_name) ({M}_l2{C})',
                 alias="$tag_system_name", legend="{{system_name}}")],
         "ops"),
        ("L3 Cache Hits by System Process",
         [T("A", _iq_by_sysname("sum", "l3"),
                 f'sum by (system_name) ({M}_l3{C})',
                 alias="$tag_system_name", legend="{{system_name}}")],
         "ops"),
        ("Total CPU by Node",
         [T("A",
            (f'SELECT sum("cpu") / 1000 FROM "{MEAS}" '
             f'WHERE {W} AND $timeFilter '
             f'GROUP BY time($__interval), "node"::tag fill(null)'),
            f'sum by (node) ({M}_cpu{C}) / 1000',
            alias="Node $tag_node", legend="Node {{node}}")],
         "ms"),
    ]

    for title, targets, unit in ts_panels:
        panels.append(timeseries_panel(ds, pid, title, targets,
                                       y=y, unit=unit, axis_min=0))
        pid += 1; y += 8

    # ── Template variables ──
    if influx:
        variables = [
            var_query(ds, "cluster", "Cluster",
                      f'SHOW TAG VALUES FROM "{MEAS}" WITH KEY = "cluster"'),
            var_query(ds, "node", "Node",
                      f'SHOW TAG VALUES FROM "{MEAS}" WITH KEY = "node" '
                      f'WHERE "cluster" =~ /^$cluster$/',
                      multi=True, include_all=True),
        ]
    else:
        variables = [
            var_query(ds, "cluster", "Cluster",
                      f'label_values({M}_cpu, cluster)'),
            var_query(ds, "node", "Node",
                      f'label_values({M}_cpu{{cluster=~"$cluster"}}, node)',
                      multi=True, include_all=True),
        ]

    dash = make_dashboard(
        title="PowerScale - System Workload (PP Dataset 0)",
        description="OneFS system process resource consumption from Partitioned "
                    "Performance Dataset 0 (System). Shows CPU, I/O, and latency "
                    "per system daemon/process.",
        tags=tags,
        variables=variables,
        panels=panels,
    )
    write_dashboard(dash, outpath(backend, "system_workload.json"))


if __name__ == "__main__":
    for b in ("influxdb", "prometheus"):
        print(f"\n=== {b} ===")
        generate(b)
