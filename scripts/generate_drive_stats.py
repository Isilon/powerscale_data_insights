#!/usr/bin/env python3
"""Generate the Drive Statistics dashboard.

Creates a new dashboard with:
- Cluster-wide disk overview (stat panels)
- Node health summary table (sorted by worst latency first)
- Per-node timeseries: latency, queue/busy, throughput, IOPS, I/O size
"""
import json, os

PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DS = {"type": "influxdb", "uid": "DS_INFLUXDB"}

# ── Helper: build a timeseries panel ──

def timeseries_panel(pid, title, targets, y, unit="short", h=8, w=24, x=0,
                     axis_label=None, axis_min=None, axis_max=None,
                     span_nulls=True, draw_style="line", fill_opacity=10,
                     line_width=2, stacking=None, tooltip_sort="desc",
                     overrides=None):
    fc = {
        "defaults": {
            "custom": {
                "drawStyle": draw_style,
                "lineInterpolation": "linear",
                "lineWidth": line_width,
                "fillOpacity": fill_opacity,
                "showPoints": "never",
                "pointSize": 5,
                "spanNulls": span_nulls,
                "stacking": stacking or {"mode": "none", "group": "A"},
                "axisPlacement": "auto",
                "barAlignment": 0,
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

def stat_panel(pid, title, target, y, x=0, w=4, h=4, unit="short",
               decimals=None, thresholds=None, color_mode="value",
               graph_mode="area", calc="lastNotNull"):
    th = thresholds or {"mode": "absolute", "steps": [{"color": "green", "value": None}]}
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

def influx_target(refId, query, alias=None, fmt="time_series"):
    t = {"refId": refId, "datasource": DS, "rawQuery": True,
         "query": query, "resultFormat": fmt}
    if alias:
        t["alias"] = alias
    return t

# ══════════════════════════════════════════════════════════════════
# Build dashboard
# ══════════════════════════════════════════════════════════════════

dashboard = {
    "id": None, "uid": None,
    "title": "PowerScale - Drive Statistics",
    "description": "Per-node disk performance: latency, queue depth, utilization, throughput, and IOPS",
    "tags": ["powerscale", "gostats"],
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
            "regex": "", "sort": 3, "multi": False, "includeAll": False,
            "current": {}, "refresh": 1, "hide": 0
        },
        {
            "name": "node", "label": "Node", "type": "query",
            "datasource": DS,
            "query": 'SHOW TAG VALUES FROM "node.disk.busy.avg" WITH KEY = "node" WHERE "cluster" =~ /^$cluster$/',
            "definition": 'SHOW TAG VALUES FROM "node.disk.busy.avg" WITH KEY = "node" WHERE "cluster" =~ /^$cluster$/',
            "regex": "", "sort": 3, "multi": True, "includeAll": True,
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

# ══════════════════════════════════════════════════════════════════
# Row 1: Cluster-Wide Disk Overview (stat panels)
# ══════════════════════════════════════════════════════════════════

cluster_stats = [
    ("Total Disk IOPS", 'SELECT mean("value") FROM "cluster.disk.xfers.rate" WHERE "cluster" =~ /^$cluster$/ AND $timeFilter GROUP BY time($__interval) fill(null)', "ops", 0),
    ("Disk Read IOPS", 'SELECT mean("value") FROM "cluster.disk.xfers.out.rate" WHERE "cluster" =~ /^$cluster$/ AND $timeFilter GROUP BY time($__interval) fill(null)', "ops", 0),
    ("Disk Write IOPS", 'SELECT mean("value") FROM "cluster.disk.xfers.in.rate" WHERE "cluster" =~ /^$cluster$/ AND $timeFilter GROUP BY time($__interval) fill(null)', "ops", 0),
    ("Disk Read Throughput", 'SELECT mean("value") FROM "cluster.disk.bytes.out.rate" WHERE "cluster" =~ /^$cluster$/ AND $timeFilter GROUP BY time($__interval) fill(null)', "Bps", None),
    ("Disk Write Throughput", 'SELECT mean("value") FROM "cluster.disk.bytes.in.rate" WHERE "cluster" =~ /^$cluster$/ AND $timeFilter GROUP BY time($__interval) fill(null)', "Bps", None),
]

for i, (title, query, unit, dec) in enumerate(cluster_stats):
    w = 5 if i < 4 else 4  # 5+5+5+5+4 = 24
    if i == 4: w = 4
    # Actually let's just do even: first 3 at w=8, then 2 at w=12? No, 5 panels.
    # 5 panels: w=4,5,5,5,5 = 24. Or just all at w=4 with some extra space.
    # Let's do 5 even panels that won't fill exactly: round to w=4 each = 20, leave 4 empty
    # Better: 3 at w=8 = 24 for IOPS row, then 2 at w=12 = 24 for throughput row
    pass

# Simpler: IOPS row (3 panels) + Throughput row (2 panels)
iops_stats = [
    ("Total Disk IOPS", 'SELECT mean("value") FROM "cluster.disk.xfers.rate" WHERE "cluster" =~ /^$cluster$/ AND $timeFilter GROUP BY time($__interval) fill(null)', "ops", 0),
    ("Disk Read IOPS", 'SELECT mean("value") FROM "cluster.disk.xfers.out.rate" WHERE "cluster" =~ /^$cluster$/ AND $timeFilter GROUP BY time($__interval) fill(null)', "ops", 0),
    ("Disk Write IOPS", 'SELECT mean("value") FROM "cluster.disk.xfers.in.rate" WHERE "cluster" =~ /^$cluster$/ AND $timeFilter GROUP BY time($__interval) fill(null)', "ops", 0),
]
for i, (title, query, unit, dec) in enumerate(iops_stats):
    p = stat_panel(pid, title,
                   influx_target("A", query),
                   y=y, x=i*8, w=8, h=4, unit=unit, decimals=dec)
    dashboard["panels"].append(p)
    pid += 1

y += 4
throughput_stats = [
    ("Disk Read Throughput", 'SELECT mean("value") FROM "cluster.disk.bytes.out.rate" WHERE "cluster" =~ /^$cluster$/ AND $timeFilter GROUP BY time($__interval) fill(null)', "Bps"),
    ("Disk Write Throughput", 'SELECT mean("value") FROM "cluster.disk.bytes.in.rate" WHERE "cluster" =~ /^$cluster$/ AND $timeFilter GROUP BY time($__interval) fill(null)', "Bps"),
]
for i, (title, query, unit) in enumerate(throughput_stats):
    p = stat_panel(pid, title,
                   influx_target("A", query),
                   y=y, x=i*12, w=12, h=4, unit=unit, decimals=1)
    dashboard["panels"].append(p)
    pid += 1
y += 4

# ══════════════════════════════════════════════════════════════════
# Row 2: Node Health Summary Table
# ══════════════════════════════════════════════════════════════════

# Table query: latest values per node for key metrics
# We use multiple queries and Grafana's table merge
table_targets = [
    influx_target("A",
        'SELECT last("value") * 1000 AS "Access Latency (ms)" '
        'FROM "node.disk.access.latency.avg" '
        'WHERE "cluster" =~ /^$cluster$/ AND "node" =~ /^$node$/ AND $timeFilter '
        'GROUP BY "node"',
        fmt="table"),
    influx_target("B",
        'SELECT last("value") * 1000 AS "IOSched Latency (ms)" '
        'FROM "node.disk.iosched.latency.avg" '
        'WHERE "cluster" =~ /^$cluster$/ AND "node" =~ /^$node$/ AND $timeFilter '
        'GROUP BY "node"',
        fmt="table"),
    influx_target("C",
        'SELECT last("value") AS "Queue Depth" '
        'FROM "node.disk.iosched.queue.avg" '
        'WHERE "cluster" =~ /^$cluster$/ AND "node" =~ /^$node$/ AND $timeFilter '
        'GROUP BY "node"',
        fmt="table"),
    influx_target("D",
        'SELECT last("value") / 10 AS "Busy %" '
        'FROM "node.disk.busy.avg" '
        'WHERE "cluster" =~ /^$cluster$/ AND "node" =~ /^$node$/ AND $timeFilter '
        'GROUP BY "node"',
        fmt="table"),
    influx_target("E",
        'SELECT last("value") AS "Slow Accesses/s" '
        'FROM "node.disk.access.slow.avg" '
        'WHERE "cluster" =~ /^$cluster$/ AND "node" =~ /^$node$/ AND $timeFilter '
        'GROUP BY "node"',
        fmt="table"),
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

dashboard["panels"].append({
    "id": pid, "type": "table",
    "title": "Node Disk Health Summary",
    "description": "Current disk metrics per node. Sorted by access latency (worst first). Color thresholds highlight problem nodes.",
    "datasource": DS,
    "gridPos": {"h": 10, "w": 24, "x": 0, "y": y},
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
y += 10

# ══════════════════════════════════════════════════════════════════
# Row 3: Latency
# ══════════════════════════════════════════════════════════════════

# Access Latency (convert seconds to ms in query)
p = timeseries_panel(pid, "Disk Access Latency by Node", [
    influx_target("A",
        'SELECT mean("value") * 1000 FROM "node.disk.access.latency.avg" '
        'WHERE "cluster" =~ /^$cluster$/ AND "node" =~ /^$node$/ AND $timeFilter '
        'GROUP BY time($__interval), "node" fill(null)',
        alias="Node $tag_node")
], y=y, unit="ms", axis_label="Latency", axis_min=0)
dashboard["panels"].append(p)
pid += 1
y += 8

# I/O Scheduler Latency
p = timeseries_panel(pid, "I/O Scheduler Latency by Node", [
    influx_target("A",
        'SELECT mean("value") * 1000 FROM "node.disk.iosched.latency.avg" '
        'WHERE "cluster" =~ /^$cluster$/ AND "node" =~ /^$node$/ AND $timeFilter '
        'GROUP BY time($__interval), "node" fill(null)',
        alias="Node $tag_node")
], y=y, unit="ms", axis_label="Latency", axis_min=0)
dashboard["panels"].append(p)
pid += 1
y += 8

# ══════════════════════════════════════════════════════════════════
# Row 4: Queue Depth & Utilization
# ══════════════════════════════════════════════════════════════════

# I/O Scheduler Queue Depth
p = timeseries_panel(pid, "I/O Scheduler Queue Depth by Node", [
    influx_target("A",
        'SELECT mean("value") FROM "node.disk.iosched.queue.avg" '
        'WHERE "cluster" =~ /^$cluster$/ AND "node" =~ /^$node$/ AND $timeFilter '
        'GROUP BY time($__interval), "node" fill(null)',
        alias="Node $tag_node")
], y=y, unit="short", axis_label="Queue Depth", axis_min=0)
dashboard["panels"].append(p)
pid += 1
y += 8

# Disk Busy % (convert tenths of percent to percent: / 10)
p = timeseries_panel(pid, "Disk Busy % by Node", [
    influx_target("A",
        'SELECT mean("value") / 10 FROM "node.disk.busy.avg" '
        'WHERE "cluster" =~ /^$cluster$/ AND "node" =~ /^$node$/ AND $timeFilter '
        'GROUP BY time($__interval), "node" fill(null)',
        alias="Node $tag_node")
], y=y, unit="percent", axis_label="Busy %", axis_min=0, axis_max=100)
dashboard["panels"].append(p)
pid += 1
y += 8

# ══════════════════════════════════════════════════════════════════
# Row 5: Throughput & IOPS
# ══════════════════════════════════════════════════════════════════

# Disk Throughput (read + write)
p = timeseries_panel(pid, "Disk Throughput by Node", [
    influx_target("A",
        'SELECT mean("value") FROM "node.disk.bytes.out.rate.avg" '
        'WHERE "cluster" =~ /^$cluster$/ AND "node" =~ /^$node$/ AND $timeFilter '
        'GROUP BY time($__interval), "node" fill(null)',
        alias="Node $tag_node Read"),
    influx_target("B",
        'SELECT (mean("value")) * -1 FROM "node.disk.bytes.in.rate.avg" '
        'WHERE "cluster" =~ /^$cluster$/ AND "node" =~ /^$node$/ AND $timeFilter '
        'GROUP BY time($__interval), "node" fill(null)',
        alias="Node $tag_node Write"),
], y=y, unit="Bps", axis_label="Throughput")
dashboard["panels"].append(p)
pid += 1
y += 8

# Disk IOPS (read + write)
p = timeseries_panel(pid, "Disk IOPS by Node", [
    influx_target("A",
        'SELECT mean("value") FROM "node.disk.xfers.out.rate.avg" '
        'WHERE "cluster" =~ /^$cluster$/ AND "node" =~ /^$node$/ AND $timeFilter '
        'GROUP BY time($__interval), "node" fill(null)',
        alias="Node $tag_node Read"),
    influx_target("B",
        'SELECT (mean("value")) * -1 FROM "node.disk.xfers.in.rate.avg" '
        'WHERE "cluster" =~ /^$cluster$/ AND "node" =~ /^$node$/ AND $timeFilter '
        'GROUP BY time($__interval), "node" fill(null)',
        alias="Node $tag_node Write"),
], y=y, unit="ops", axis_label="IOPS")
dashboard["panels"].append(p)
pid += 1
y += 8

# ══════════════════════════════════════════════════════════════════
# Row 6: I/O Size & Slow Accesses
# ══════════════════════════════════════════════════════════════════

# Average I/O Size
p = timeseries_panel(pid, "Average I/O Size by Node", [
    influx_target("A",
        'SELECT mean("value") FROM "node.disk.xfer.size.out.avg" '
        'WHERE "cluster" =~ /^$cluster$/ AND "node" =~ /^$node$/ AND $timeFilter '
        'GROUP BY time($__interval), "node" fill(null)',
        alias="Node $tag_node Read"),
    influx_target("B",
        'SELECT mean("value") FROM "node.disk.xfer.size.in.avg" '
        'WHERE "cluster" =~ /^$cluster$/ AND "node" =~ /^$node$/ AND $timeFilter '
        'GROUP BY time($__interval), "node" fill(null)',
        alias="Node $tag_node Write"),
], y=y, unit="bytes", axis_label="I/O Size", axis_min=0)
dashboard["panels"].append(p)
pid += 1
y += 8

# Slow Accesses
p = timeseries_panel(pid, "Slow Disk Accesses by Node", [
    influx_target("A",
        'SELECT mean("value") FROM "node.disk.access.slow.avg" '
        'WHERE "cluster" =~ /^$cluster$/ AND "node" =~ /^$node$/ AND $timeFilter '
        'GROUP BY time($__interval), "node" fill(null)',
        alias="Node $tag_node")
], y=y, unit="ops", axis_label="Slow Accesses/s", axis_min=0)
dashboard["panels"].append(p)
pid += 1
y += 8

# ══════════════════════════════════════════════════════════════════
# Write output
# ══════════════════════════════════════════════════════════════════

outpath = os.path.join(PROJ_ROOT, "dashboards/influxdb/drive_stats.json")
with open(outpath, 'w') as f:
    json.dump(dashboard, f, indent=2)
    f.write('\n')

print(f"Generated {len(dashboard['panels'])} panels")
for p in dashboard["panels"]:
    ptype = p["type"]
    title = p.get("title", "")
    gp = p["gridPos"]
    print(f"  {ptype:12s} w={gp['w']:2d} x={gp['x']:2d} y={gp['y']:2d} | {title}")
