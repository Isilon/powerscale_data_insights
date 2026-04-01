#!/usr/bin/env python3
"""Generate the Drive Summary Statistics dashboard.

Per-physical-drive performance and capacity statistics. Requires
``drive = true`` in ``[summary_stats]`` config. Filters out UNKNOWN
drive types by default.

Generates both InfluxDB and Prometheus variants.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dashlib import *

README = """\
## PowerScale - Drive Summary Stats

Per-physical-drive performance and capacity statistics. Requires \
`drive = true` in `[summary_stats]` config. Filters out UNKNOWN \
drive types by default."""

MEAS = "node.summary.drive"  # InfluxDB measurement
M = "isilon_stat_node_summary_drive"  # Prometheus metric prefix


def generate(backend):
    ds = DS_INFLUXDB if backend == "influxdb" else DS_PROMETHEUS
    influx = (backend == "influxdb")
    tags = ["powerscale", "gostats", "summary"] + (["prometheus"] if not influx else [])

    def T(refId, iq, pq, alias=None, legend=None, **kw):
        if influx:
            return influx_target(ds, refId, iq, alias=alias, **kw)
        return prom_target(ds, refId, pq, legend=legend)

    # WHERE / label-matcher fragments
    W = ('"cluster" =~ /^$cluster$/ AND "type" =~ /^$type$/ '
         'AND "drive_id" =~ /^$drive_id$/')
    C = '{cluster=~"$cluster",type=~"$type",drive_id=~"$drive_id",type!="UNKNOWN"}'

    panels = []; pid = 1; y = 0

    # ── README panel ──
    panels.append(text_panel(pid, README, y, h=4)); pid += 1; y += 4

    # ── Overview stat panels ──
    for i, (title, iq, pq, unit, dec) in enumerate([
        ("Total Drive IOPS",
         f'SELECT sum("xfers_in") + sum("xfers_out") FROM "{MEAS}" '
         f'WHERE {W} AND $timeFilter GROUP BY time($__interval) fill(null)',
         f'sum({M}_xfers_in{C}) + sum({M}_xfers_out{C})',
         "ops", 0),
        ("Avg Access Latency",
         f'SELECT mean("access_latency") FROM "{MEAS}" '
         f'WHERE {W} AND "access_latency" > 0 AND $timeFilter '
         f'GROUP BY time($__interval) fill(null)',
         f'avg({M}_access_latency{C} > 0)',
         "ms", 2),
        ("Avg IOSched Latency",
         f'SELECT mean("iosched_latency") FROM "{MEAS}" '
         f'WHERE {W} AND "iosched_latency" > 0 AND $timeFilter '
         f'GROUP BY time($__interval) fill(null)',
         f'avg({M}_iosched_latency{C} > 0)',
         "ms", 2),
        ("Avg Busy %",
         f'SELECT mean("busy") FROM "{MEAS}" '
         f'WHERE {W} AND "busy" > 0 AND $timeFilter '
         f'GROUP BY time($__interval) fill(null)',
         f'avg({M}_busy{C} > 0)',
         "percent", 1),
    ]):
        panels.append(stat_panel(ds, pid, title, T("A", iq, pq),
                                 y=y, x=i*6, w=6, h=4, unit=unit, decimals=dec))
        pid += 1
    y += 4

    # ── Drive Health Summary table ──
    if influx:
        table_targets = [
            influx_target(ds, "A",
                f'SELECT last("access_latency") AS "Access Latency (ms)" '
                f'FROM "{MEAS}" WHERE {W} AND $timeFilter '
                f'GROUP BY "drive_id", "type"', fmt="table"),
            influx_target(ds, "B",
                f'SELECT last("iosched_latency") AS "IOSched Latency (ms)" '
                f'FROM "{MEAS}" WHERE {W} AND $timeFilter '
                f'GROUP BY "drive_id", "type"', fmt="table"),
            influx_target(ds, "C",
                f'SELECT last("iosched_queue") AS "Queue Depth" '
                f'FROM "{MEAS}" WHERE {W} AND $timeFilter '
                f'GROUP BY "drive_id", "type"', fmt="table"),
            influx_target(ds, "D",
                f'SELECT last("busy") AS "Busy %" '
                f'FROM "{MEAS}" WHERE {W} AND $timeFilter '
                f'GROUP BY "drive_id", "type"', fmt="table"),
            influx_target(ds, "E",
                f'SELECT last("access_slow") AS "Slow/s" '
                f'FROM "{MEAS}" WHERE {W} AND $timeFilter '
                f'GROUP BY "drive_id", "type"', fmt="table"),
            influx_target(ds, "F",
                f'SELECT last("used_bytes_percent") AS "Capacity Used %" '
                f'FROM "{MEAS}" WHERE {W} AND $timeFilter '
                f'GROUP BY "drive_id", "type"', fmt="table"),
        ]
        transformations = [{"id": "merge", "options": {}}]
    else:
        def _pt(rid, expr):
            t = prom_target(ds, rid, expr)
            t["instant"] = True
            t["format"] = "table"
            return t
        table_targets = [
            _pt("A", f'max by (drive_id, type) ({M}_access_latency{C})'),
            _pt("B", f'max by (drive_id, type) ({M}_iosched_latency{C})'),
            _pt("C", f'max by (drive_id, type) ({M}_iosched_queue{C})'),
            _pt("D", f'max by (drive_id, type) ({M}_busy{C})'),
            _pt("E", f'max by (drive_id, type) ({M}_access_slow{C})'),
            _pt("F", f'max by (drive_id, type) ({M}_used_bytes_percent{C})'),
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
                    "Value #E": "Slow/s",
                    "Value #F": "Capacity Used %",
                }
            }},
        ]

    table_overrides = [
        {"matcher": {"id": "byName", "options": "Time"}, "properties": [
            {"id": "custom.hidden", "value": True}
        ]},
        {"matcher": {"id": "byName", "options": "drive_id"}, "properties": [
            {"id": "displayName", "value": "Drive"},
            {"id": "custom.width", "value": 80}
        ]},
        {"matcher": {"id": "byName", "options": "type"}, "properties": [
            {"id": "displayName", "value": "Type"},
            {"id": "custom.width", "value": 70}
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
        {"matcher": {"id": "byName", "options": "Slow/s"}, "properties": [
            {"id": "decimals", "value": 1},
            {"id": "thresholds", "value": {"mode": "absolute", "steps": [
                {"color": "green", "value": None},
                {"color": "orange", "value": 1},
                {"color": "red", "value": 10}
            ]}},
            {"id": "custom.cellOptions", "value": {"type": "color-background", "mode": "gradient"}}
        ]},
        {"matcher": {"id": "byName", "options": "Capacity Used %"}, "properties": [
            {"id": "unit", "value": "percent"}, {"id": "decimals", "value": 1},
            {"id": "thresholds", "value": {"mode": "absolute", "steps": [
                {"color": "green", "value": None},
                {"color": "orange", "value": 80},
                {"color": "red", "value": 90}
            ]}},
            {"id": "custom.cellOptions", "value": {"type": "color-background", "mode": "gradient"}}
        ]},
    ]

    panels.append(table_panel(ds, pid, "Drive Health Summary", table_targets,
                              y=y, h=12, overrides=table_overrides,
                              sort_by=[{"displayName": "Access Latency (ms)", "desc": True}],
                              transformations=transformations))
    pid += 1; y += 12

    # ── Timeseries: Latency ──
    for title, iq, pq, unit, label, minv, maxv in [
        ("Access Latency by Drive",
         f'SELECT mean("access_latency") FROM "{MEAS}" WHERE {W} AND $timeFilter '
         f'GROUP BY time($__interval), "drive_id" fill(null)',
         f'{M}_access_latency{C}',
         "ms", "Latency", 0, None),
        ("I/O Scheduler Latency by Drive",
         f'SELECT mean("iosched_latency") FROM "{MEAS}" WHERE {W} AND $timeFilter '
         f'GROUP BY time($__interval), "drive_id" fill(null)',
         f'{M}_iosched_latency{C}',
         "ms", "Latency", 0, None),
    ]:
        panels.append(timeseries_panel(ds, pid, title,
            [T("A", iq, pq, alias="$tag_drive_id", legend="{{drive_id}}")],
            y=y, unit=unit, axis_label=label, axis_min=minv, axis_max=maxv))
        pid += 1; y += 8

    # ── Timeseries: Queue Depth & Utilization ──
    for title, iq, pq, unit, label, minv, maxv in [
        ("I/O Scheduler Queue Depth by Drive",
         f'SELECT mean("iosched_queue") FROM "{MEAS}" WHERE {W} AND $timeFilter '
         f'GROUP BY time($__interval), "drive_id" fill(null)',
         f'{M}_iosched_queue{C}',
         "short", "Queue Depth", 0, None),
        ("Drive Busy % by Drive",
         f'SELECT mean("busy") FROM "{MEAS}" WHERE {W} AND $timeFilter '
         f'GROUP BY time($__interval), "drive_id" fill(null)',
         f'{M}_busy{C}',
         "percent", "Busy %", 0, 100),
    ]:
        panels.append(timeseries_panel(ds, pid, title,
            [T("A", iq, pq, alias="$tag_drive_id", legend="{{drive_id}}")],
            y=y, unit=unit, axis_label=label, axis_min=minv, axis_max=maxv))
        pid += 1; y += 8

    # ── Timeseries: Throughput (read positive, write negative) ──
    panels.append(timeseries_panel(ds, pid, "Drive Throughput by Drive", [
        T("A",
          f'SELECT mean("bytes_out") FROM "{MEAS}" WHERE {W} AND $timeFilter '
          f'GROUP BY time($__interval), "drive_id" fill(null)',
          f'{M}_bytes_out{C}',
          alias="$tag_drive_id Read", legend="{{drive_id}} Read"),
        T("B",
          f'SELECT (mean("bytes_in")) * -1 FROM "{MEAS}" WHERE {W} AND $timeFilter '
          f'GROUP BY time($__interval), "drive_id" fill(null)',
          f'-{M}_bytes_in{C}',
          alias="$tag_drive_id Write", legend="{{drive_id}} Write"),
    ], y=y, unit="Bps", axis_label="Read (+) / Write (-)"))
    pid += 1; y += 8

    # ── Timeseries: IOPS (read positive, write negative) ──
    panels.append(timeseries_panel(ds, pid, "Drive IOPS by Drive", [
        T("A",
          f'SELECT mean("xfers_out") FROM "{MEAS}" WHERE {W} AND $timeFilter '
          f'GROUP BY time($__interval), "drive_id" fill(null)',
          f'{M}_xfers_out{C}',
          alias="$tag_drive_id Read", legend="{{drive_id}} Read"),
        T("B",
          f'SELECT (mean("xfers_in")) * -1 FROM "{MEAS}" WHERE {W} AND $timeFilter '
          f'GROUP BY time($__interval), "drive_id" fill(null)',
          f'-{M}_xfers_in{C}',
          alias="$tag_drive_id Write", legend="{{drive_id}} Write"),
    ], y=y, unit="ops", axis_label="Read (+) / Write (-)"))
    pid += 1; y += 8

    # ── Timeseries: I/O Size (read + write, not negated) ──
    panels.append(timeseries_panel(ds, pid, "Average I/O Size by Drive", [
        T("A",
          f'SELECT mean("xfer_size_out") FROM "{MEAS}" WHERE {W} AND $timeFilter '
          f'GROUP BY time($__interval), "drive_id" fill(null)',
          f'{M}_xfer_size_out{C}',
          alias="$tag_drive_id Read", legend="{{drive_id}} Read"),
        T("B",
          f'SELECT mean("xfer_size_in") FROM "{MEAS}" WHERE {W} AND $timeFilter '
          f'GROUP BY time($__interval), "drive_id" fill(null)',
          f'{M}_xfer_size_in{C}',
          alias="$tag_drive_id Write", legend="{{drive_id}} Write"),
    ], y=y, unit="bytes", axis_label="I/O Size", axis_min=0))
    pid += 1; y += 8

    # ── Timeseries: Slow Accesses ──
    panels.append(timeseries_panel(ds, pid, "Slow Accesses by Drive", [
        T("A",
          f'SELECT mean("access_slow") FROM "{MEAS}" WHERE {W} AND $timeFilter '
          f'GROUP BY time($__interval), "drive_id" fill(null)',
          f'{M}_access_slow{C}',
          alias="$tag_drive_id", legend="{{drive_id}}"),
    ], y=y, unit="ops", axis_label="Slow/s", axis_min=0))
    pid += 1; y += 8

    # ── Timeseries: Capacity ──
    panels.append(timeseries_panel(ds, pid, "Drive Capacity Used % by Drive", [
        T("A",
          f'SELECT mean("used_bytes_percent") FROM "{MEAS}" WHERE {W} AND $timeFilter '
          f'GROUP BY time($__interval), "drive_id" fill(null)',
          f'{M}_used_bytes_percent{C}',
          alias="$tag_drive_id", legend="{{drive_id}}"),
    ], y=y, unit="percent", axis_label="Used %", axis_min=0, axis_max=100))
    pid += 1; y += 8

    # ── Template variables ──
    if influx:
        variables = [
            var_query(ds, "cluster", "Cluster",
                      'SHOW TAG VALUES WITH KEY = "cluster"'),
            var_query(ds, "type", "Drive Type",
                      f'SHOW TAG VALUES FROM "{MEAS}" WITH KEY = "type" '
                      f'WHERE "cluster" =~ /^$cluster$/ AND "type" != \'UNKNOWN\'',
                      multi=True, include_all=True, sort=1),
            var_query(ds, "drive_id", "Drive",
                      f'SHOW TAG VALUES FROM "{MEAS}" WITH KEY = "drive_id" '
                      f'WHERE "cluster" =~ /^$cluster$/ AND "type" =~ /^$type$/',
                      multi=True, include_all=True),
        ]
    else:
        variables = [
            var_query(ds, "cluster", "Cluster",
                      f'label_values({M}_busy, cluster)'),
            var_query(ds, "type", "Drive Type",
                      f'label_values({M}_busy{{cluster=~"$cluster",type!="UNKNOWN"}}, type)',
                      multi=True, include_all=True, sort=1),
            var_query(ds, "drive_id", "Drive",
                      f'label_values({M}_busy{{cluster=~"$cluster",type=~"$type"}}, drive_id)',
                      multi=True, include_all=True),
        ]

    dash = make_dashboard(
        title="PowerScale - Drive Summary Stats",
        description="Per-physical-drive performance and capacity statistics. "
                    "Uses OneFS drive summary statistics. Filters out empty "
                    "drive slots.",
        tags=tags,
        variables=variables,
        panels=panels,
    )
    write_dashboard(dash, outpath(backend, "drive_summary.json"))


if __name__ == "__main__":
    for b in ("influxdb", "prometheus"):
        print(f"\n=== {b} ===")
        generate(b)
