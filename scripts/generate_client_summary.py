#!/usr/bin/env python3
"""Generate the Client Summary Statistics dashboard.

Uses node.summary.client data which provides per-client, per-protocol,
per-class breakdowns with latency statistics (avg/min/max).

Key feature: Top Clients table for identifying busiest or highest-latency
clients on the cluster.

Note: client summary stats have high tag cardinality (remote_addr × protocol
× class × node × user). On large clusters with many clients this can cause
InfluxDB performance issues. Document this in deployment guidance.
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
                     axis_label=None, axis_min=None, span_nulls=True,
                     fill_opacity=10, line_width=2, tooltip_sort="desc",
                     overrides=None):
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

def stat_panel(pid, title, target, y, x=0, w=5, h=4, unit="short",
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
    "title": "PowerScale - Client Summary Stats",
    "description": "Per-client protocol activity, throughput, and latency. Uses OneFS client summary statistics to identify busiest or highest-latency clients.",
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
            "name": "node", "label": "Node", "type": "query",
            "datasource": DS,
            "query": 'SHOW TAG VALUES FROM "node.summary.client" WITH KEY = "node" WHERE "cluster" =~ /^$cluster$/',
            "definition": 'SHOW TAG VALUES FROM "node.summary.client" WITH KEY = "node" WHERE "cluster" =~ /^$cluster$/',
            "sort": 3, "multi": True, "includeAll": True,
            "allValue": "", "current": {}, "refresh": 1, "hide": 0
        },
        {
            "name": "protocol", "label": "Protocol", "type": "query",
            "datasource": DS,
            "query": 'SHOW TAG VALUES FROM "node.summary.client" WITH KEY = "protocol" WHERE "cluster" =~ /^$cluster$/',
            "definition": 'SHOW TAG VALUES FROM "node.summary.client" WITH KEY = "protocol" WHERE "cluster" =~ /^$cluster$/',
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

WHERE = ('"cluster" =~ /^$cluster$/ AND "node" =~ /^$node$/ '
         'AND "protocol" =~ /^$protocol$/')

# ══════════════════════════════════════════════════════════════════
# Row 1: Overview stats
# ══════════════════════════════════════════════════════════════════

overview = [
    ("Total Client Ops/s",
     f'SELECT sum("operation_rate") FROM "node.summary.client" WHERE {WHERE} AND $timeFilter GROUP BY time($__interval) fill(null)',
     "ops", 0),
    ("Average Latency",
     f'SELECT mean("time_avg") / 1000 FROM "node.summary.client" WHERE {WHERE} AND $timeFilter GROUP BY time($__interval) fill(null)',
     "ms", 2),
    ("Inbound Throughput",
     f'SELECT sum("in") FROM "node.summary.client" WHERE {WHERE} AND $timeFilter GROUP BY time($__interval) fill(null)',
     "Bps", None),
    ("Outbound Throughput",
     f'SELECT sum("out") FROM "node.summary.client" WHERE {WHERE} AND $timeFilter GROUP BY time($__interval) fill(null)',
     "Bps", None),
]

for i, (title, query, unit, dec) in enumerate(overview):
    p = stat_panel(pid, title, influx_target("A", query),
                   y=y, x=i*6, w=6, h=4, unit=unit, decimals=dec)
    dashboard["panels"].append(p)
    pid += 1
y += 4

# ══════════════════════════════════════════════════════════════════
# Row 2: Top Clients Table
# ══════════════════════════════════════════════════════════════════

table_targets = [
    influx_target("A",
        f'SELECT sum("operation_rate") AS "Ops/s" '
        f'FROM "node.summary.client" '
        f'WHERE {WHERE} AND $timeFilter '
        f'GROUP BY "remote_addr"',
        fmt="table"),
    influx_target("B",
        f'SELECT mean("time_avg") / 1000 AS "Avg Latency (ms)" '
        f'FROM "node.summary.client" '
        f'WHERE {WHERE} AND $timeFilter '
        f'GROUP BY "remote_addr"',
        fmt="table"),
    influx_target("C",
        f'SELECT mean("time_max") / 1000 AS "Max Latency (ms)" '
        f'FROM "node.summary.client" '
        f'WHERE {WHERE} AND $timeFilter '
        f'GROUP BY "remote_addr"',
        fmt="table"),
    influx_target("D",
        f'SELECT sum("in") AS "Inbound (B/s)" '
        f'FROM "node.summary.client" '
        f'WHERE {WHERE} AND $timeFilter '
        f'GROUP BY "remote_addr"',
        fmt="table"),
    influx_target("E",
        f'SELECT sum("out") AS "Outbound (B/s)" '
        f'FROM "node.summary.client" '
        f'WHERE {WHERE} AND $timeFilter '
        f'GROUP BY "remote_addr"',
        fmt="table"),
]

table_overrides = [
    {"matcher": {"id": "byName", "options": "Time"}, "properties": [
        {"id": "custom.hidden", "value": True}
    ]},
    {"matcher": {"id": "byName", "options": "remote_addr"}, "properties": [
        {"id": "displayName", "value": "Client"},
        {"id": "custom.width", "value": 150}
    ]},
    {"matcher": {"id": "byName", "options": "Ops/s"}, "properties": [
        {"id": "unit", "value": "ops"}, {"id": "decimals", "value": 1},
    ]},
    {"matcher": {"id": "byName", "options": "Avg Latency (ms)"}, "properties": [
        {"id": "unit", "value": "ms"}, {"id": "decimals", "value": 2},
        {"id": "thresholds", "value": {"mode": "absolute", "steps": [
            {"color": "green", "value": None},
            {"color": "orange", "value": 10},
            {"color": "red", "value": 50}
        ]}},
        {"id": "custom.cellOptions", "value": {"type": "color-background", "mode": "gradient"}}
    ]},
    {"matcher": {"id": "byName", "options": "Max Latency (ms)"}, "properties": [
        {"id": "unit", "value": "ms"}, {"id": "decimals", "value": 1},
        {"id": "thresholds", "value": {"mode": "absolute", "steps": [
            {"color": "green", "value": None},
            {"color": "orange", "value": 50},
            {"color": "red", "value": 200}
        ]}},
        {"id": "custom.cellOptions", "value": {"type": "color-background", "mode": "gradient"}}
    ]},
    {"matcher": {"id": "byName", "options": "Inbound (B/s)"}, "properties": [
        {"id": "unit", "value": "Bps"}, {"id": "decimals", "value": 1},
    ]},
    {"matcher": {"id": "byName", "options": "Outbound (B/s)"}, "properties": [
        {"id": "unit", "value": "Bps"}, {"id": "decimals", "value": 1},
    ]},
]

dashboard["panels"].append({
    "id": pid, "type": "table",
    "title": "Top Clients",
    "description": "Per-client summary sorted by ops/s. Identify the busiest clients or those experiencing the highest latency.",
    "datasource": DS,
    "gridPos": {"h": 10, "w": 24, "x": 0, "y": y},
    "targets": table_targets,
    "fieldConfig": {"defaults": {}, "overrides": table_overrides},
    "options": {
        "showHeader": True,
        "cellHeight": "sm",
        "sortBy": [{"displayName": "Ops/s", "desc": True}],
        "footer": {"show": False, "reducer": ["sum"], "countRows": False, "fields": ""}
    },
    "transformations": [
        {"id": "merge", "options": {}}
    ]
})
pid += 1
y += 10

# ══════════════════════════════════════════════════════════════════
# Row 3: Client Activity (timeseries by client)
# ══════════════════════════════════════════════════════════════════

p = timeseries_panel(pid, "Operation Rate by Client", [
    influx_target("A",
        f'SELECT sum("operation_rate") FROM "node.summary.client" '
        f'WHERE {WHERE} AND $timeFilter '
        f'GROUP BY time($__interval), "remote_addr" fill(null)',
        alias="$tag_remote_addr")
], y=y, unit="ops", axis_label="Ops/s", axis_min=0)
dashboard["panels"].append(p)
pid += 1
y += 8

p = timeseries_panel(pid, "Average Latency by Client", [
    influx_target("A",
        f'SELECT mean("time_avg") / 1000 FROM "node.summary.client" '
        f'WHERE {WHERE} AND $timeFilter '
        f'GROUP BY time($__interval), "remote_addr" fill(null)',
        alias="$tag_remote_addr")
], y=y, unit="ms", axis_label="Latency", axis_min=0)
dashboard["panels"].append(p)
pid += 1
y += 8

# ══════════════════════════════════════════════════════════════════
# Row 4: By Protocol
# ══════════════════════════════════════════════════════════════════

p = timeseries_panel(pid, "Operation Rate by Protocol", [
    influx_target("A",
        f'SELECT sum("operation_rate") FROM "node.summary.client" '
        f'WHERE {WHERE} AND $timeFilter '
        f'GROUP BY time($__interval), "protocol" fill(null)',
        alias="$tag_protocol")
], y=y, unit="ops", axis_label="Ops/s", axis_min=0)
dashboard["panels"].append(p)
pid += 1
y += 8

p = timeseries_panel(pid, "Average Latency by Protocol", [
    influx_target("A",
        f'SELECT mean("time_avg") / 1000 FROM "node.summary.client" '
        f'WHERE {WHERE} AND $timeFilter '
        f'GROUP BY time($__interval), "protocol" fill(null)',
        alias="$tag_protocol")
], y=y, unit="ms", axis_label="Latency", axis_min=0)
dashboard["panels"].append(p)
pid += 1
y += 8

# ══════════════════════════════════════════════════════════════════
# Row 5: By Operation Class
# ══════════════════════════════════════════════════════════════════

p = timeseries_panel(pid, "Operation Rate by Class", [
    influx_target("A",
        f'SELECT sum("operation_rate") FROM "node.summary.client" '
        f'WHERE {WHERE} AND $timeFilter '
        f'GROUP BY time($__interval), "class" fill(null)',
        alias="$tag_class")
], y=y, unit="ops", axis_label="Ops/s", axis_min=0)
dashboard["panels"].append(p)
pid += 1
y += 8

p = timeseries_panel(pid, "Average Latency by Class", [
    influx_target("A",
        f'SELECT mean("time_avg") / 1000 FROM "node.summary.client" '
        f'WHERE {WHERE} AND $timeFilter '
        f'GROUP BY time($__interval), "class" fill(null)',
        alias="$tag_class")
], y=y, unit="ms", axis_label="Latency", axis_min=0)
dashboard["panels"].append(p)
pid += 1
y += 8

# ══════════════════════════════════════════════════════════════════
# Row 6: Per-Node Breakdown
# ══════════════════════════════════════════════════════════════════

p = timeseries_panel(pid, "Operation Rate by Node", [
    influx_target("A",
        f'SELECT sum("operation_rate") FROM "node.summary.client" '
        f'WHERE {WHERE} AND $timeFilter '
        f'GROUP BY time($__interval), "node" fill(null)',
        alias="Node $tag_node")
], y=y, unit="ops", axis_label="Ops/s", axis_min=0)
dashboard["panels"].append(p)
pid += 1
y += 8

p = timeseries_panel(pid, "Average Latency by Node", [
    influx_target("A",
        f'SELECT mean("time_avg") / 1000 FROM "node.summary.client" '
        f'WHERE {WHERE} AND $timeFilter '
        f'GROUP BY time($__interval), "node" fill(null)',
        alias="Node $tag_node")
], y=y, unit="ms", axis_label="Latency", axis_min=0)
dashboard["panels"].append(p)
pid += 1
y += 8

# ══════════════════════════════════════════════════════════════════
# Write output
# ══════════════════════════════════════════════════════════════════

outpath = os.path.join(PROJ_ROOT, "dashboards/influxdb/client_summary.json")
with open(outpath, 'w') as f:
    json.dump(dashboard, f, indent=2)
    f.write('\n')

print(f"Generated {len(dashboard['panels'])} panels")
for p in dashboard["panels"]:
    ptype = p["type"]
    title = p.get("title", "")
    gp = p["gridPos"]
    print(f"  {ptype:12s} w={gp['w']:2d} x={gp['x']:2d} y={gp['y']:2d} | {title}")
