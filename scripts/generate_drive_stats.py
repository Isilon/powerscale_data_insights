#!/usr/bin/env python3
"""Generate the Drive Statistics dashboard.

Per-node disk performance using node.disk.* stats (always collected).
Shows disk access latency, I/O scheduler latency and queue depth,
disk utilization, throughput, IOPS, I/O size, and slow accesses per node.

Generates both InfluxDB and Prometheus variants.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dashlib import *

README = """\
## PowerScale - Drive Statistics

Per-node disk performance using `node.disk.*` stats (always collected). \
Shows disk access latency, I/O scheduler latency and queue depth, \
disk utilization, throughput, IOPS, I/O size, and slow accesses per node."""


def generate(backend):
    ds = DS_INFLUXDB if backend == "influxdb" else DS_PROMETHEUS
    influx = (backend == "influxdb")
    tags = ["powerscale", "gostats"] + (["prometheus"] if not influx else [])

    def T(refId, iq, pq, alias=None, legend=None, **kw):
        if influx:
            return influx_target(ds, refId, iq, alias=alias, **kw)
        return prom_target(ds, refId, pq, legend=legend)

    # WHERE / label-matcher fragments
    WC = '"cluster" =~ /^$cluster$/'  # cluster-level InfluxDB
    W = '"cluster" =~ /^$cluster$/ AND "node" =~ /^$node$/'  # node-level
    C = '{cluster=~"$cluster",node=~"$node"}'  # Prometheus label matcher

    panels = []; pid = 1; y = 0

    # ── README panel ──
    panels.append(text_panel(pid, README, y, h=4)); pid += 1; y += 4

    # ── Cluster-wide IOPS stats ──
    for i, (title, iq, pq, unit, dec) in enumerate([
        ("Total Disk IOPS",
         f'SELECT mean("value") FROM "cluster.disk.xfers.rate" WHERE {WC} AND $timeFilter GROUP BY time($__interval) fill(null)',
         f'sum(isilon_stat_node_disk_xfers_in_rate_avg{C}) + sum(isilon_stat_node_disk_xfers_out_rate_avg{C})',
         "ops", 0),
        ("Disk Read IOPS",
         f'SELECT mean("value") FROM "cluster.disk.xfers.out.rate" WHERE {WC} AND $timeFilter GROUP BY time($__interval) fill(null)',
         f'sum(isilon_stat_node_disk_xfers_out_rate_avg{C})',
         "ops", 0),
        ("Disk Write IOPS",
         f'SELECT mean("value") FROM "cluster.disk.xfers.in.rate" WHERE {WC} AND $timeFilter GROUP BY time($__interval) fill(null)',
         f'sum(isilon_stat_node_disk_xfers_in_rate_avg{C})',
         "ops", 0),
    ]):
        panels.append(stat_panel(ds, pid, title, T("A", iq, pq),
                                 y=y, x=i*8, w=8, h=4, unit=unit, decimals=dec))
        pid += 1
    y += 4

    # ── Cluster-wide throughput stats ──
    for i, (title, iq, pq, unit) in enumerate([
        ("Disk Read Throughput",
         f'SELECT mean("value") FROM "cluster.disk.bytes.out.rate" WHERE {WC} AND $timeFilter GROUP BY time($__interval) fill(null)',
         f'sum(isilon_stat_node_disk_bytes_out_rate_avg{C})',
         "Bps"),
        ("Disk Write Throughput",
         f'SELECT mean("value") FROM "cluster.disk.bytes.in.rate" WHERE {WC} AND $timeFilter GROUP BY time($__interval) fill(null)',
         f'sum(isilon_stat_node_disk_bytes_in_rate_avg{C})',
         "Bps"),
    ]):
        panels.append(stat_panel(ds, pid, title, T("A", iq, pq),
                                 y=y, x=i*12, w=12, h=4, unit=unit, decimals=1))
        pid += 1
    y += 4

    # ── Node Disk Health Summary table ──
    if influx:
        table_targets = [
            influx_target(ds, "A",
                f'SELECT last("value") * 1000 AS "Access Latency (ms)" '
                f'FROM "node.disk.access.latency.avg" '
                f'WHERE {W} AND $timeFilter GROUP BY "node"',
                fmt="table"),
            influx_target(ds, "B",
                f'SELECT last("value") * 1000 AS "IOSched Latency (ms)" '
                f'FROM "node.disk.iosched.latency.avg" '
                f'WHERE {W} AND $timeFilter GROUP BY "node"',
                fmt="table"),
            influx_target(ds, "C",
                f'SELECT last("value") AS "Queue Depth" '
                f'FROM "node.disk.iosched.queue.avg" '
                f'WHERE {W} AND $timeFilter GROUP BY "node"',
                fmt="table"),
            influx_target(ds, "D",
                f'SELECT last("value") / 10 AS "Busy %" '
                f'FROM "node.disk.busy.avg" '
                f'WHERE {W} AND $timeFilter GROUP BY "node"',
                fmt="table"),
            influx_target(ds, "E",
                f'SELECT last("value") AS "Slow Accesses/s" '
                f'FROM "node.disk.access.slow.avg" '
                f'WHERE {W} AND $timeFilter GROUP BY "node"',
                fmt="table"),
        ]
        transformations = [{"id": "merge", "options": {}}]
    else:
        def _pt(rid, expr):
            t = prom_target(ds, rid, expr)
            t["instant"] = True
            t["format"] = "table"
            return t
        table_targets = [
            _pt("A", f'max by (node) (isilon_stat_node_disk_access_latency_avg{C}) * 1000'),
            _pt("B", f'max by (node) (isilon_stat_node_disk_iosched_latency_avg{C}) * 1000'),
            _pt("C", f'max by (node) (isilon_stat_node_disk_iosched_queue_avg{C})'),
            _pt("D", f'max by (node) (isilon_stat_node_disk_busy_avg{C}) / 10'),
            _pt("E", f'max by (node) (isilon_stat_node_disk_access_slow_avg{C})'),
        ]
        transformations = [
            {"id": "merge", "options": {}},
            {"id": "organize", "options": {
                "excludeByName": {"Time": True},
                "renameByName": {
                    "Value #A": "Access Latency (ms)",
                    "Value #B": "IOSched Latency (ms)",
                    "Value #C": "Queue Depth",
                    "Value #D": "Busy %",
                    "Value #E": "Slow Accesses/s",
                }
            }},
        ]

    table_overrides = [
        {"matcher": {"id": "byName", "options": "Time"}, "properties": [
            {"id": "custom.hidden", "value": True}
        ]},
        {"matcher": {"id": "byName", "options": "Access Latency (ms)"}, "properties": [
            {"id": "unit", "value": "ms"}, {"id": "decimals", "value": 2},
            {"id": "thresholds", "value": {"mode": "absolute", "steps": [
                {"color": "green", "value": None},
                {"color": "orange", "value": 5},
                {"color": "red", "value": 20}
            ]}},
            {"id": "custom.cellOptions", "value": {"type": "color-background", "mode": "gradient"}}
        ]},
        {"matcher": {"id": "byName", "options": "IOSched Latency (ms)"}, "properties": [
            {"id": "unit", "value": "ms"}, {"id": "decimals", "value": 2},
            {"id": "thresholds", "value": {"mode": "absolute", "steps": [
                {"color": "green", "value": None},
                {"color": "orange", "value": 5},
                {"color": "red", "value": 20}
            ]}},
            {"id": "custom.cellOptions", "value": {"type": "color-background", "mode": "gradient"}}
        ]},
        {"matcher": {"id": "byName", "options": "Queue Depth"}, "properties": [
            {"id": "decimals", "value": 1},
            {"id": "thresholds", "value": {"mode": "absolute", "steps": [
                {"color": "green", "value": None},
                {"color": "orange", "value": 5},
                {"color": "red", "value": 20}
            ]}},
            {"id": "custom.cellOptions", "value": {"type": "color-background", "mode": "gradient"}}
        ]},
        {"matcher": {"id": "byName", "options": "Busy %"}, "properties": [
            {"id": "unit", "value": "percent"}, {"id": "decimals", "value": 1},
            {"id": "thresholds", "value": {"mode": "absolute", "steps": [
                {"color": "green", "value": None},
                {"color": "orange", "value": 50},
                {"color": "red", "value": 80}
            ]}},
            {"id": "custom.cellOptions", "value": {"type": "color-background", "mode": "gradient"}}
        ]},
        {"matcher": {"id": "byName", "options": "Slow Accesses/s"}, "properties": [
            {"id": "decimals", "value": 1},
            {"id": "thresholds", "value": {"mode": "absolute", "steps": [
                {"color": "green", "value": None},
                {"color": "orange", "value": 1},
                {"color": "red", "value": 10}
            ]}},
            {"id": "custom.cellOptions", "value": {"type": "color-background", "mode": "gradient"}}
        ]},
        {"matcher": {"id": "byName", "options": "node"}, "properties": [
            {"id": "displayName", "value": "Node"},
            {"id": "custom.width", "value": 80}
        ]},
    ]

    panels.append(table_panel(ds, pid, "Node Disk Health Summary", table_targets,
                              y=y, h=10, overrides=table_overrides,
                              sort_by=[{"displayName": "Access Latency (ms)", "desc": True}],
                              transformations=transformations))
    pid += 1; y += 10

    # ── Timeseries: Latency ──
    for title, iq, pq, unit, label, minv, maxv in [
        ("Disk Access Latency by Node",
         f'SELECT mean("value") * 1000 FROM "node.disk.access.latency.avg" '
         f'WHERE {W} AND $timeFilter GROUP BY time($__interval), "node" fill(null)',
         f'isilon_stat_node_disk_access_latency_avg{C} * 1000',
         "ms", "Latency", 0, None),
        ("I/O Scheduler Latency by Node",
         f'SELECT mean("value") * 1000 FROM "node.disk.iosched.latency.avg" '
         f'WHERE {W} AND $timeFilter GROUP BY time($__interval), "node" fill(null)',
         f'isilon_stat_node_disk_iosched_latency_avg{C} * 1000',
         "ms", "Latency", 0, None),
    ]:
        panels.append(timeseries_panel(ds, pid, title,
            [T("A", iq, pq, alias="Node $tag_node", legend="Node {{node}}")],
            y=y, unit=unit, axis_label=label, axis_min=minv, axis_max=maxv))
        pid += 1; y += 8

    # ── Timeseries: Queue Depth & Utilization ──
    for title, iq, pq, unit, label, minv, maxv in [
        ("I/O Scheduler Queue Depth by Node",
         f'SELECT mean("value") FROM "node.disk.iosched.queue.avg" '
         f'WHERE {W} AND $timeFilter GROUP BY time($__interval), "node" fill(null)',
         f'isilon_stat_node_disk_iosched_queue_avg{C}',
         "short", "Queue Depth", 0, None),
        ("Disk Busy % by Node",
         f'SELECT mean("value") / 10 FROM "node.disk.busy.avg" '
         f'WHERE {W} AND $timeFilter GROUP BY time($__interval), "node" fill(null)',
         f'isilon_stat_node_disk_busy_avg{C} / 10',
         "percent", "Busy %", 0, 100),
    ]:
        panels.append(timeseries_panel(ds, pid, title,
            [T("A", iq, pq, alias="Node $tag_node", legend="Node {{node}}")],
            y=y, unit=unit, axis_label=label, axis_min=minv, axis_max=maxv))
        pid += 1; y += 8

    # ── Timeseries: Throughput (read positive, write negative) ──
    panels.append(timeseries_panel(ds, pid, "Disk Throughput by Node", [
        T("A",
          f'SELECT mean("value") FROM "node.disk.bytes.out.rate.avg" '
          f'WHERE {W} AND $timeFilter GROUP BY time($__interval), "node" fill(null)',
          f'isilon_stat_node_disk_bytes_out_rate_avg{C}',
          alias="Node $tag_node Read", legend="Node {{node}} Read"),
        T("B",
          f'SELECT (mean("value")) * -1 FROM "node.disk.bytes.in.rate.avg" '
          f'WHERE {W} AND $timeFilter GROUP BY time($__interval), "node" fill(null)',
          f'-isilon_stat_node_disk_bytes_in_rate_avg{C}',
          alias="Node $tag_node Write", legend="Node {{node}} Write"),
    ], y=y, unit="Bps", axis_label="Read (+) / Write (-)"))
    pid += 1; y += 8

    # ── Timeseries: IOPS (read positive, write negative) ──
    panels.append(timeseries_panel(ds, pid, "Disk IOPS by Node", [
        T("A",
          f'SELECT mean("value") FROM "node.disk.xfers.out.rate.avg" '
          f'WHERE {W} AND $timeFilter GROUP BY time($__interval), "node" fill(null)',
          f'isilon_stat_node_disk_xfers_out_rate_avg{C}',
          alias="Node $tag_node Read", legend="Node {{node}} Read"),
        T("B",
          f'SELECT (mean("value")) * -1 FROM "node.disk.xfers.in.rate.avg" '
          f'WHERE {W} AND $timeFilter GROUP BY time($__interval), "node" fill(null)',
          f'-isilon_stat_node_disk_xfers_in_rate_avg{C}',
          alias="Node $tag_node Write", legend="Node {{node}} Write"),
    ], y=y, unit="ops", axis_label="Read (+) / Write (-)"))
    pid += 1; y += 8

    # ── Timeseries: I/O Size (read + write, not negated) ──
    panels.append(timeseries_panel(ds, pid, "Average I/O Size by Node", [
        T("A",
          f'SELECT mean("value") FROM "node.disk.xfer.size.out.avg" '
          f'WHERE {W} AND $timeFilter GROUP BY time($__interval), "node" fill(null)',
          f'isilon_stat_node_disk_xfer_size_out_avg{C}',
          alias="Node $tag_node Read", legend="Node {{node}} Read"),
        T("B",
          f'SELECT mean("value") FROM "node.disk.xfer.size.in.avg" '
          f'WHERE {W} AND $timeFilter GROUP BY time($__interval), "node" fill(null)',
          f'isilon_stat_node_disk_xfer_size_in_avg{C}',
          alias="Node $tag_node Write", legend="Node {{node}} Write"),
    ], y=y, unit="bytes", axis_label="I/O Size", axis_min=0))
    pid += 1; y += 8

    # ── Timeseries: Slow Accesses ──
    panels.append(timeseries_panel(ds, pid, "Slow Disk Accesses by Node", [
        T("A",
          f'SELECT mean("value") FROM "node.disk.access.slow.avg" '
          f'WHERE {W} AND $timeFilter GROUP BY time($__interval), "node" fill(null)',
          f'isilon_stat_node_disk_access_slow_avg{C}',
          alias="Node $tag_node", legend="Node {{node}}"),
    ], y=y, unit="ops", axis_label="Slow Accesses/s", axis_min=0))
    pid += 1; y += 8

    # ── Template variables ──
    if influx:
        variables = [
            var_query(ds, "cluster", "Cluster",
                      'SHOW TAG VALUES WITH KEY = "cluster"'),
            var_query(ds, "node", "Node",
                      'SHOW TAG VALUES FROM "node.disk.busy.avg" WITH KEY = "node" '
                      'WHERE "cluster" =~ /^$cluster$/',
                      multi=True, include_all=True),
        ]
    else:
        variables = [
            var_query(ds, "cluster", "Cluster",
                      'label_values(isilon_stat_node_disk_busy_avg, cluster)'),
            var_query(ds, "node", "Node",
                      'label_values(isilon_stat_node_disk_busy_avg{cluster=~"$cluster"}, node)',
                      multi=True, include_all=True),
        ]

    dash = make_dashboard(
        title="PowerScale - Drive Statistics",
        description="Per-node disk performance: latency, queue depth, "
                    "utilization, throughput, and IOPS",
        tags=tags,
        variables=variables,
        panels=panels,
    )
    write_dashboard(dash, outpath(backend, "drive_stats.json"))


if __name__ == "__main__":
    for b in ("influxdb", "prometheus"):
        print(f"\n=== {b} ===")
        generate(b)
