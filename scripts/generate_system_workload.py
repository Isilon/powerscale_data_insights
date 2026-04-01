#!/usr/bin/env python3
"""Generate the System Workload (PP Dataset 0) dashboard.

Dataset 0 ("System") is a predefined PP dataset present on all OneFS 9.x+
clusters. It breaks down resource consumption by system_name (OneFS daemon/
process) and node. Useful for finding runaway system processes.

Units (from isi statistics workload list --nohumanize):
  cpu: microseconds (520731 raw = 520.7ms humanized)
  latency_read/write/other: microseconds
  ops, reads, writes: count per interval
  bytes_in/out: bytes per second
  l2, l3: cache hits per second
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

# Normal data filter: exclude overflow workload_type buckets
# Uses same pattern as dashgen
NORMAL = '("workload_type"::tag !~ /./ OR "workload_type"::tag = \'Pinned\')'

dashboard = {
    "id": None, "uid": None,
    "title": "PowerScale - System Workload (PP Dataset 0)",
    "description": "OneFS system process resource consumption from Partitioned Performance Dataset 0 (System). Shows CPU, I/O, and latency per system daemon/process.",
    "tags": ["powerscale", "goppstats"],
    "schemaVersion": 39, "version": 1,
    "editable": True, "graphTooltip": 1, "timezone": "browser",
    "time": {"from": "now-1h", "to": "now"},
    "timepicker": {"refresh_intervals": ["5s","10s","30s","1m","5m","15m","30m","1h","2h","1d"]},
    "refresh": "30s", "fiscalYearStartMonth": 0, "liveNow": False,
    "templating": {"list": [
        {
            "name": "cluster", "label": "Cluster", "type": "query",
            "datasource": DS,
            "query": 'SHOW TAG VALUES FROM "cluster.performance.dataset.0" WITH KEY = "cluster"',
            "definition": 'SHOW TAG VALUES FROM "cluster.performance.dataset.0" WITH KEY = "cluster"',
            "sort": 3, "multi": False, "includeAll": False,
            "current": {}, "refresh": 1, "hide": 0
        },
        {
            "name": "node", "label": "Node", "type": "query",
            "datasource": DS,
            "query": 'SHOW TAG VALUES FROM "cluster.performance.dataset.0" WITH KEY = "node" WHERE "cluster" =~ /^$cluster$/',
            "definition": 'SHOW TAG VALUES FROM "cluster.performance.dataset.0" WITH KEY = "node" WHERE "cluster" =~ /^$cluster$/',
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

WHERE = (f'"cluster"::tag =~ /^$cluster$/ AND "node"::tag =~ /^$node$/ '
         f'AND {NORMAL}')

# ══════════════════════════════════════════════════════════════════
# Row 1: Overview stats
# ══════════════════════════════════════════════════════════════════

overview = [
    ("Total CPU",
     f'SELECT sum("cpu") / 1000 FROM "cluster.performance.dataset.0" WHERE {WHERE} AND $timeFilter GROUP BY time($__interval) fill(null)',
     "ms", 0),
    ("Total Ops",
     f'SELECT sum("ops") FROM "cluster.performance.dataset.0" WHERE {WHERE} AND $timeFilter GROUP BY time($__interval) fill(null)',
     "ops", 0),
    ("Total Bytes In",
     f'SELECT sum("bytes_in") FROM "cluster.performance.dataset.0" WHERE {WHERE} AND $timeFilter GROUP BY time($__interval) fill(null)',
     "Bps", None),
    ("Total Bytes Out",
     f'SELECT sum("bytes_out") FROM "cluster.performance.dataset.0" WHERE {WHERE} AND $timeFilter GROUP BY time($__interval) fill(null)',
     "Bps", None),
]

for i, (title, query, unit, dec) in enumerate(overview):
    p = stat_panel(pid, title, influx_target("A", query),
                   y=y, x=i*6, w=6, h=4, unit=unit, decimals=dec)
    dashboard["panels"].append(p)
    pid += 1
y += 4

# ══════════════════════════════════════════════════════════════════
# Row 2: CPU by System Process (the headline panel)
# ══════════════════════════════════════════════════════════════════

p = timeseries_panel(pid, "CPU by System Process", [
    influx_target("A",
        f'SELECT sum("cpu") / 1000 FROM "cluster.performance.dataset.0" '
        f'WHERE {WHERE} AND $timeFilter '
        f'GROUP BY time($__interval), "system_name"::tag fill(null)',
        alias="$tag_system_name")
], y=y, unit="ms", axis_label="CPU (ms)", axis_min=0)
dashboard["panels"].append(p)
pid += 1
y += 8

# ══════════════════════════════════════════════════════════════════
# Row 3: Operations by System Process
# ══════════════════════════════════════════════════════════════════

p = timeseries_panel(pid, "Operations by System Process", [
    influx_target("A",
        f'SELECT sum("ops") FROM "cluster.performance.dataset.0" '
        f'WHERE {WHERE} AND $timeFilter '
        f'GROUP BY time($__interval), "system_name"::tag fill(null)',
        alias="$tag_system_name")
], y=y, unit="ops", axis_label="Ops", axis_min=0)
dashboard["panels"].append(p)
pid += 1
y += 8

p = timeseries_panel(pid, "Reads and Writes by System Process", [
    influx_target("A",
        f'SELECT sum("reads") FROM "cluster.performance.dataset.0" '
        f'WHERE {WHERE} AND $timeFilter '
        f'GROUP BY time($__interval), "system_name"::tag fill(null)',
        alias="$tag_system_name reads"),
    influx_target("B",
        f'SELECT sum("writes") FROM "cluster.performance.dataset.0" '
        f'WHERE {WHERE} AND $timeFilter '
        f'GROUP BY time($__interval), "system_name"::tag fill(null)',
        alias="$tag_system_name writes"),
], y=y, unit="short", axis_label="Count", axis_min=0)
dashboard["panels"].append(p)
pid += 1
y += 8

# ══════════════════════════════════════════════════════════════════
# Row 4: Throughput by System Process
# ══════════════════════════════════════════════════════════════════

p = timeseries_panel(pid, "Bytes In (Write) by System Process", [
    influx_target("A",
        f'SELECT sum("bytes_in") FROM "cluster.performance.dataset.0" '
        f'WHERE {WHERE} AND $timeFilter '
        f'GROUP BY time($__interval), "system_name"::tag fill(null)',
        alias="$tag_system_name")
], y=y, unit="Bps", axis_label="Throughput", axis_min=0)
dashboard["panels"].append(p)
pid += 1
y += 8

p = timeseries_panel(pid, "Bytes Out (Read) by System Process", [
    influx_target("A",
        f'SELECT sum("bytes_out") FROM "cluster.performance.dataset.0" '
        f'WHERE {WHERE} AND $timeFilter '
        f'GROUP BY time($__interval), "system_name"::tag fill(null)',
        alias="$tag_system_name")
], y=y, unit="Bps", axis_label="Throughput", axis_min=0)
dashboard["panels"].append(p)
pid += 1
y += 8

# ══════════════════════════════════════════════════════════════════
# Row 5: Latency by System Process
# ══════════════════════════════════════════════════════════════════

p = timeseries_panel(pid, "Read Latency by System Process", [
    influx_target("A",
        f'SELECT mean("latency_read") / 1000 FROM "cluster.performance.dataset.0" '
        f'WHERE {WHERE} AND $timeFilter '
        f'GROUP BY time($__interval), "system_name"::tag fill(null)',
        alias="$tag_system_name")
], y=y, unit="ms", axis_label="Latency", axis_min=0)
dashboard["panels"].append(p)
pid += 1
y += 8

p = timeseries_panel(pid, "Write Latency by System Process", [
    influx_target("A",
        f'SELECT mean("latency_write") / 1000 FROM "cluster.performance.dataset.0" '
        f'WHERE {WHERE} AND $timeFilter '
        f'GROUP BY time($__interval), "system_name"::tag fill(null)',
        alias="$tag_system_name")
], y=y, unit="ms", axis_label="Latency", axis_min=0)
dashboard["panels"].append(p)
pid += 1
y += 8

p = timeseries_panel(pid, "Other Latency by System Process", [
    influx_target("A",
        f'SELECT mean("latency_other") / 1000 FROM "cluster.performance.dataset.0" '
        f'WHERE {WHERE} AND $timeFilter '
        f'GROUP BY time($__interval), "system_name"::tag fill(null)',
        alias="$tag_system_name")
], y=y, unit="ms", axis_label="Latency", axis_min=0)
dashboard["panels"].append(p)
pid += 1
y += 8

# ══════════════════════════════════════════════════════════════════
# Row 6: Cache Hits by System Process
# ══════════════════════════════════════════════════════════════════

p = timeseries_panel(pid, "L2 Cache Hits by System Process", [
    influx_target("A",
        f'SELECT sum("l2") FROM "cluster.performance.dataset.0" '
        f'WHERE {WHERE} AND $timeFilter '
        f'GROUP BY time($__interval), "system_name"::tag fill(null)',
        alias="$tag_system_name")
], y=y, unit="ops", axis_label="L2 Hits/s", axis_min=0)
dashboard["panels"].append(p)
pid += 1
y += 8

p = timeseries_panel(pid, "L3 Cache Hits by System Process", [
    influx_target("A",
        f'SELECT sum("l3") FROM "cluster.performance.dataset.0" '
        f'WHERE {WHERE} AND $timeFilter '
        f'GROUP BY time($__interval), "system_name"::tag fill(null)',
        alias="$tag_system_name")
], y=y, unit="ops", axis_label="L3 Hits/s", axis_min=0)
dashboard["panels"].append(p)
pid += 1
y += 8

# ══════════════════════════════════════════════════════════════════
# Row 7: Per-Node CPU Breakdown
# ══════════════════════════════════════════════════════════════════

p = timeseries_panel(pid, "Total CPU by Node", [
    influx_target("A",
        f'SELECT sum("cpu") / 1000 FROM "cluster.performance.dataset.0" '
        f'WHERE {WHERE} AND $timeFilter '
        f'GROUP BY time($__interval), "node"::tag fill(null)',
        alias="Node $tag_node")
], y=y, unit="ms", axis_label="CPU (ms)", axis_min=0)
dashboard["panels"].append(p)
pid += 1
y += 8

# ══════════════════════════════════════════════════════════════════
# Write output
# ══════════════════════════════════════════════════════════════════

outpath = os.path.join(PROJ_ROOT, "dashboards/influxdb/system_workload.json")
with open(outpath, 'w') as f:
    json.dump(dashboard, f, indent=2)
    f.write('\n')

print(f"Generated {len(dashboard['panels'])} panels")
for p in dashboard["panels"]:
    ptype = p["type"]
    title = p.get("title", "")
    gp = p["gridPos"]
    print(f"  {ptype:12s} w={gp['w']:2d} x={gp['x']:2d} y={gp['y']:2d} | {title}")
