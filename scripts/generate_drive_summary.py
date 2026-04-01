#!/usr/bin/env python3
"""Generate the Drive Summary Statistics dashboard.

Uses node.summary.drive data which provides per-physical-drive statistics
including latency, throughput, IOPS, queue depth, utilization, and capacity.

Filters out UNKNOWN drive type (empty/unpopulated drive slots) by default.
Drive IDs use node:bay format (e.g., "1:5" = node 1, bay 5).

Units (from OneFS CLI humanized output):
  access_latency: milliseconds
  iosched_latency: milliseconds
  iosched_queue: count
  busy: percent (0-100)
  bytes_in/out: bytes/s
  xfers_in/out: ops/s
  xfer_size_in/out: bytes
  used_bytes_percent: percent (0-100)
  used_inodes: count
  access_slow: count/s
"""
import json, os

PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DS = {"type": "influxdb", "uid": "DS_INFLUXDB"}

# ── Helpers ──

def influx_target(refId, query, alias=None, fmt="time_series"):
    t = {"refId": refId, "datasource": DS, "rawQuery": True,
         "query": query, "resultFormat": fmt}
    if alias:
        t["alias"] = alias
    return t

def timeseries_panel(pid, title, targets, y, unit="short", h=8, w=24, x=0,
                     axis_label=None, axis_min=None, axis_max=None,
                     span_nulls=True, fill_opacity=10, line_width=2,
                     tooltip_sort="desc", overrides=None):
    fc = {
        "defaults": {
            "custom": {
                "drawStyle": "line", "lineInterpolation": "linear",
                "lineWidth": line_width, "fillOpacity": fill_opacity,
                "showPoints": "never", "pointSize": 5,
                "spanNulls": span_nulls,
                "stacking": {"mode": "none", "group": "A"},
                "axisPlacement": "auto", "barAlignment": 0,
                "gradientMode": "none",
                "thresholdsStyle": {"mode": "off"},
            },
            "unit": unit,
        },
        "overrides": overrides or []
    }
    if axis_label:
        fc["defaults"]["custom"]["axisLabel"] = axis_label
    if axis_min is not None:
        fc["defaults"]["min"] = axis_min
    if axis_max is not None:
        fc["defaults"]["max"] = axis_max
    return {
        "id": pid, "type": "timeseries", "title": title,
        "datasource": DS, "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "targets": targets, "fieldConfig": fc,
        "options": {
            "legend": {
                "displayMode": "table", "placement": "right",
                "calcs": ["min", "max", "mean", "lastNotNull"],
                "width": 500,
            },
            "tooltip": {"mode": "multi", "sort": tooltip_sort},
        }
    }

def stat_panel(pid, title, target, y, x=0, w=6, h=4, unit="short",
               decimals=None, color_mode="value", graph_mode="area",
               calc="lastNotNull"):
    th = {"mode": "absolute", "steps": [{"color": "green", "value": None}]}
    fc = {"defaults": {"thresholds": th, "unit": unit}, "overrides": []}
    if decimals is not None:
        fc["defaults"]["decimals"] = decimals
    return {
        "id": pid, "type": "stat", "title": title,
        "datasource": DS, "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "targets": [target], "fieldConfig": fc,
        "options": {
            "reduceOptions": {"calcs": [calc], "fields": "", "values": False},
            "colorMode": color_mode, "orientation": "auto",
            "graphMode": graph_mode, "textMode": "auto", "wideLayout": True,
        }
    }

# ══════════════════════════════════════════════════════════════════
# Build dashboard
# ══════════════════════════════════════════════════════════════════

dashboard = {
    "id": None, "uid": None,
    "title": "PowerScale - Drive Summary Stats",
    "description": "Per-physical-drive performance and capacity statistics. Uses OneFS drive summary statistics. Filters out empty drive slots.",
    "tags": ["powerscale", "gostats", "summary"],
    "schemaVersion": 39, "version": 1,
    "editable": True, "graphTooltip": 1, "timezone": "browser",
    "time": {"from": "now-1h", "to": "now"},
    "timepicker": {"refresh_intervals": ["5s","10s","30s","1m","5m","15m","30m","1h","2h","1d"]},
    "refresh": "30s", "fiscalYearStartMonth": 0, "liveNow": False,
    "templating": {"list": [
        {
            "name": "cluster", "label": "Cluster", "type": "query",
            "datasource": DS,
            "query": 'SHOW TAG VALUES WITH KEY = "cluster"',
            "definition": 'SHOW TAG VALUES WITH KEY = "cluster"',
            "sort": 3, "multi": False, "includeAll": False,
            "current": {}, "refresh": 1, "hide": 0
        },
        {
            "name": "type", "label": "Drive Type", "type": "query",
            "datasource": DS,
            "query": 'SHOW TAG VALUES FROM "node.summary.drive" WITH KEY = "type" WHERE "cluster" =~ /^$cluster$/ AND "type" != \'UNKNOWN\'',
            "definition": 'SHOW TAG VALUES FROM "node.summary.drive" WITH KEY = "type" WHERE "cluster" =~ /^$cluster$/ AND "type" != \'UNKNOWN\'',
            "sort": 1, "multi": True, "includeAll": True,
            "allValue": "", "current": {}, "refresh": 1, "hide": 0
        },
        {
            "name": "drive_id", "label": "Drive", "type": "query",
            "datasource": DS,
            "query": 'SHOW TAG VALUES FROM "node.summary.drive" WITH KEY = "drive_id" WHERE "cluster" =~ /^$cluster$/ AND "type" =~ /^$type$/',
            "definition": 'SHOW TAG VALUES FROM "node.summary.drive" WITH KEY = "drive_id" WHERE "cluster" =~ /^$cluster$/ AND "type" =~ /^$type$/',
            "sort": 3, "multi": True, "includeAll": True,
            "allValue": "", "current": {}, "refresh": 1, "hide": 0
        }
    ]},
    "annotations": {"list": [{
        "builtIn": 1, "datasource": {"type": "grafana", "uid": "-- Grafana --"},
        "enable": True, "hide": True, "iconColor": "rgba(0, 211, 255, 1)",
        "name": "Annotations & Alerts", "type": "dashboard"
    }]},
    "panels": [], "links": []
}

pid = 1
y = 0

WHERE = ('"cluster" =~ /^$cluster$/ AND "type" =~ /^$type$/ '
         'AND "drive_id" =~ /^$drive_id$/')

# ══════════════════════════════════════════════════════════════════
# Row 1: Overview stats
# ══════════════════════════════════════════════════════════════════

overview = [
    ("Total Drive IOPS",
     f'SELECT sum("xfers_in") + sum("xfers_out") FROM "node.summary.drive" WHERE {WHERE} AND $timeFilter GROUP BY time($__interval) fill(null)',
     "ops", 0),
    ("Avg Access Latency",
     f'SELECT mean("access_latency") FROM "node.summary.drive" WHERE {WHERE} AND "access_latency" > 0 AND $timeFilter GROUP BY time($__interval) fill(null)',
     "ms", 2),
    ("Avg IOSched Latency",
     f'SELECT mean("iosched_latency") FROM "node.summary.drive" WHERE {WHERE} AND "iosched_latency" > 0 AND $timeFilter GROUP BY time($__interval) fill(null)',
     "ms", 2),
    ("Avg Busy %",
     f'SELECT mean("busy") FROM "node.summary.drive" WHERE {WHERE} AND "busy" > 0 AND $timeFilter GROUP BY time($__interval) fill(null)',
     "percent", 1),
]

for i, (title, query, unit, dec) in enumerate(overview):
    p = stat_panel(pid, title, influx_target("A", query),
                   y=y, x=i*6, w=6, h=4, unit=unit, decimals=dec)
    dashboard["panels"].append(p)
    pid += 1
y += 4

# ══════════════════════════════════════════════════════════════════
# Row 2: Drive Health Table (worst drives first)
# ══════════════════════════════════════════════════════════════════

table_targets = [
    influx_target("A",
        f'SELECT last("access_latency") AS "Access Latency (ms)" '
        f'FROM "node.summary.drive" '
        f'WHERE {WHERE} AND $timeFilter '
        f'GROUP BY "drive_id", "type"',
        fmt="table"),
    influx_target("B",
        f'SELECT last("iosched_latency") AS "IOSched Latency (ms)" '
        f'FROM "node.summary.drive" '
        f'WHERE {WHERE} AND $timeFilter '
        f'GROUP BY "drive_id", "type"',
        fmt="table"),
    influx_target("C",
        f'SELECT last("iosched_queue") AS "Queue Depth" '
        f'FROM "node.summary.drive" '
        f'WHERE {WHERE} AND $timeFilter '
        f'GROUP BY "drive_id", "type"',
        fmt="table"),
    influx_target("D",
        f'SELECT last("busy") AS "Busy %" '
        f'FROM "node.summary.drive" '
        f'WHERE {WHERE} AND $timeFilter '
        f'GROUP BY "drive_id", "type"',
        fmt="table"),
    influx_target("E",
        f'SELECT last("access_slow") AS "Slow/s" '
        f'FROM "node.summary.drive" '
        f'WHERE {WHERE} AND $timeFilter '
        f'GROUP BY "drive_id", "type"',
        fmt="table"),
    influx_target("F",
        f'SELECT last("used_bytes_percent") AS "Capacity Used %" '
        f'FROM "node.summary.drive" '
        f'WHERE {WHERE} AND $timeFilter '
        f'GROUP BY "drive_id", "type"',
        fmt="table"),
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

dashboard["panels"].append({
    "id": pid, "type": "table",
    "title": "Drive Health Summary",
    "description": "Current metrics per physical drive. Sorted by access latency (worst first). Color thresholds highlight problem drives.",
    "datasource": DS,
    "gridPos": {"h": 12, "w": 24, "x": 0, "y": y},
    "targets": table_targets,
    "fieldConfig": {"defaults": {}, "overrides": table_overrides},
    "options": {
        "showHeader": True,
        "cellHeight": "sm",
        "sortBy": [{"displayName": "Access Latency (ms)", "desc": True}],
        "footer": {"show": False, "reducer": ["sum"], "countRows": False, "fields": ""}
    },
    "transformations": [
        {"id": "merge", "options": {}}
    ]
})
pid += 1
y += 12

# ══════════════════════════════════════════════════════════════════
# Row 3: Latency
# ══════════════════════════════════════════════════════════════════

p = timeseries_panel(pid, "Access Latency by Drive", [
    influx_target("A",
        f'SELECT mean("access_latency") FROM "node.summary.drive" '
        f'WHERE {WHERE} AND $timeFilter '
        f'GROUP BY time($__interval), "drive_id" fill(null)',
        alias="$tag_drive_id")
], y=y, unit="ms", axis_label="Latency", axis_min=0)
dashboard["panels"].append(p)
pid += 1
y += 8

p = timeseries_panel(pid, "I/O Scheduler Latency by Drive", [
    influx_target("A",
        f'SELECT mean("iosched_latency") FROM "node.summary.drive" '
        f'WHERE {WHERE} AND $timeFilter '
        f'GROUP BY time($__interval), "drive_id" fill(null)',
        alias="$tag_drive_id")
], y=y, unit="ms", axis_label="Latency", axis_min=0)
dashboard["panels"].append(p)
pid += 1
y += 8

# ══════════════════════════════════════════════════════════════════
# Row 4: Queue & Utilization
# ══════════════════════════════════════════════════════════════════

p = timeseries_panel(pid, "I/O Scheduler Queue Depth by Drive", [
    influx_target("A",
        f'SELECT mean("iosched_queue") FROM "node.summary.drive" '
        f'WHERE {WHERE} AND $timeFilter '
        f'GROUP BY time($__interval), "drive_id" fill(null)',
        alias="$tag_drive_id")
], y=y, unit="short", axis_label="Queue Depth", axis_min=0)
dashboard["panels"].append(p)
pid += 1
y += 8

p = timeseries_panel(pid, "Drive Busy % by Drive", [
    influx_target("A",
        f'SELECT mean("busy") FROM "node.summary.drive" '
        f'WHERE {WHERE} AND $timeFilter '
        f'GROUP BY time($__interval), "drive_id" fill(null)',
        alias="$tag_drive_id")
], y=y, unit="percent", axis_label="Busy %", axis_min=0, axis_max=100)
dashboard["panels"].append(p)
pid += 1
y += 8

# ══════════════════════════════════════════════════════════════════
# Row 5: Throughput & IOPS
# ══════════════════════════════════════════════════════════════════

p = timeseries_panel(pid, "Drive Throughput by Drive", [
    influx_target("A",
        f'SELECT mean("bytes_out") FROM "node.summary.drive" '
        f'WHERE {WHERE} AND $timeFilter '
        f'GROUP BY time($__interval), "drive_id" fill(null)',
        alias="$tag_drive_id Read"),
    influx_target("B",
        f'SELECT (mean("bytes_in")) * -1 FROM "node.summary.drive" '
        f'WHERE {WHERE} AND $timeFilter '
        f'GROUP BY time($__interval), "drive_id" fill(null)',
        alias="$tag_drive_id Write"),
], y=y, unit="Bps", axis_label="Throughput")
dashboard["panels"].append(p)
pid += 1
y += 8

p = timeseries_panel(pid, "Drive IOPS by Drive", [
    influx_target("A",
        f'SELECT mean("xfers_out") FROM "node.summary.drive" '
        f'WHERE {WHERE} AND $timeFilter '
        f'GROUP BY time($__interval), "drive_id" fill(null)',
        alias="$tag_drive_id Read"),
    influx_target("B",
        f'SELECT (mean("xfers_in")) * -1 FROM "node.summary.drive" '
        f'WHERE {WHERE} AND $timeFilter '
        f'GROUP BY time($__interval), "drive_id" fill(null)',
        alias="$tag_drive_id Write"),
], y=y, unit="ops", axis_label="IOPS")
dashboard["panels"].append(p)
pid += 1
y += 8

# ══════════════════════════════════════════════════════════════════
# Row 6: I/O Size & Slow Accesses
# ══════════════════════════════════════════════════════════════════

p = timeseries_panel(pid, "Average I/O Size by Drive", [
    influx_target("A",
        f'SELECT mean("xfer_size_out") FROM "node.summary.drive" '
        f'WHERE {WHERE} AND $timeFilter '
        f'GROUP BY time($__interval), "drive_id" fill(null)',
        alias="$tag_drive_id Read"),
    influx_target("B",
        f'SELECT mean("xfer_size_in") FROM "node.summary.drive" '
        f'WHERE {WHERE} AND $timeFilter '
        f'GROUP BY time($__interval), "drive_id" fill(null)',
        alias="$tag_drive_id Write"),
], y=y, unit="bytes", axis_label="I/O Size", axis_min=0)
dashboard["panels"].append(p)
pid += 1
y += 8

p = timeseries_panel(pid, "Slow Accesses by Drive", [
    influx_target("A",
        f'SELECT mean("access_slow") FROM "node.summary.drive" '
        f'WHERE {WHERE} AND $timeFilter '
        f'GROUP BY time($__interval), "drive_id" fill(null)',
        alias="$tag_drive_id")
], y=y, unit="ops", axis_label="Slow/s", axis_min=0)
dashboard["panels"].append(p)
pid += 1
y += 8

# ══════════════════════════════════════════════════════════════════
# Row 7: Capacity
# ══════════════════════════════════════════════════════════════════

p = timeseries_panel(pid, "Drive Capacity Used % by Drive", [
    influx_target("A",
        f'SELECT mean("used_bytes_percent") FROM "node.summary.drive" '
        f'WHERE {WHERE} AND $timeFilter '
        f'GROUP BY time($__interval), "drive_id" fill(null)',
        alias="$tag_drive_id")
], y=y, unit="percent", axis_label="Used %", axis_min=0, axis_max=100)
dashboard["panels"].append(p)
pid += 1
y += 8

# ══════════════════════════════════════════════════════════════════
# Write output
# ══════════════════════════════════════════════════════════════════

outpath = os.path.join(PROJ_ROOT, "dashboards/influxdb/drive_summary.json")
with open(outpath, 'w') as f:
    json.dump(dashboard, f, indent=2)
    f.write('\n')

print(f"Generated {len(dashboard['panels'])} panels")
for p in dashboard["panels"]:
    ptype = p["type"]
    title = p.get("title", "")
    gp = p["gridPos"]
    print(f"  {ptype:12s} w={gp['w']:2d} x={gp['x']:2d} y={gp['y']:2d} | {title}")
