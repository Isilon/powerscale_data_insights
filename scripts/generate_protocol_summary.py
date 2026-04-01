#!/usr/bin/env python3
"""Generate the Protocol Summary Statistics dashboard.

Uses node.summary.protocol data which provides per-node, per-protocol,
per-operation breakdowns with full latency statistics (avg/min/max/stddev).

This is distinct from the Protocol Detail dashboard which uses
cluster.protostats.* (cluster-level aggregates without per-operation
latency distribution).
"""
import json, os

PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DS = {"type": "influxdb", "uid": "DS_INFLUXDB"}

# Protocol list matches OneFS isi statistics protocol list --protocols
PROTOCOLS = "nfs3,nfs4,smb1,smb2,nlm,ftp,http,siq,jobd,irp,lsass_in,lsass_out,papi,hdfs,s3,nfsrdma,nfs4rdma"

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
    "title": "PowerScale - Protocol Summary Stats",
    "description": "Per-node, per-operation protocol statistics with latency distribution (avg/min/max/stddev). Uses OneFS summary statistics.",
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
            "name": "protocol", "label": "Protocol", "type": "custom",
            "query": PROTOCOLS,
            "current": {"selected": True, "text": "nfs3", "value": "nfs3"},
            "options": [{"selected": p == "nfs3", "text": p, "value": p}
                        for p in PROTOCOLS.split(",")],
            "multi": False, "includeAll": False, "hide": 0
        },
        {
            "name": "node", "label": "Node", "type": "query",
            "datasource": DS,
            "query": 'SHOW TAG VALUES FROM "node.summary.protocol" WITH KEY = "node" WHERE "cluster" =~ /^$cluster$/',
            "definition": 'SHOW TAG VALUES FROM "node.summary.protocol" WITH KEY = "node" WHERE "cluster" =~ /^$cluster$/',
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

# ══════════════════════════════════════════════════════════════════
# Row 1: Overview stats (aggregated across selected nodes)
# ══════════════════════════════════════════════════════════════════

overview = [
    ("$protocol Ops/s", 'SELECT sum("operation_rate") FROM "node.summary.protocol" WHERE "cluster" =~ /^$cluster$/ AND "node" =~ /^$node$/ AND "protocol" = \'$protocol\' AND $timeFilter GROUP BY time($__interval) fill(null)', "ops", 0),
    ("$protocol Avg Latency", 'SELECT mean("time_avg") / 1000 FROM "node.summary.protocol" WHERE "cluster" =~ /^$cluster$/ AND "node" =~ /^$node$/ AND "protocol" = \'$protocol\' AND $timeFilter GROUP BY time($__interval) fill(null)', "ms", 2),
    ("$protocol Inbound", 'SELECT sum("in") FROM "node.summary.protocol" WHERE "cluster" =~ /^$cluster$/ AND "node" =~ /^$node$/ AND "protocol" = \'$protocol\' AND $timeFilter GROUP BY time($__interval) fill(null)', "Bps", None),
    ("$protocol Outbound", 'SELECT sum("out") FROM "node.summary.protocol" WHERE "cluster" =~ /^$cluster$/ AND "node" =~ /^$node$/ AND "protocol" = \'$protocol\' AND $timeFilter GROUP BY time($__interval) fill(null)', "Bps", None),
]

for i, (title, query, unit, dec) in enumerate(overview):
    p = stat_panel(pid, title, influx_target("A", query),
                   y=y, x=i*6, w=6, h=4, unit=unit, decimals=dec)
    dashboard["panels"].append(p)
    pid += 1
y += 4

# ══════════════════════════════════════════════════════════════════
# Row 2: Operation Rate by Class and by Operation
# ══════════════════════════════════════════════════════════════════

p = timeseries_panel(pid, "$protocol Operation Rate by Class", [
    influx_target("A",
        'SELECT sum("operation_rate") FROM "node.summary.protocol" '
        'WHERE "cluster" =~ /^$cluster$/ AND "node" =~ /^$node$/ '
        'AND "protocol" = \'$protocol\' AND $timeFilter '
        'GROUP BY time($__interval), "class" fill(null)',
        alias="$tag_class")
], y=y, unit="ops", axis_label="Ops/s", axis_min=0)
dashboard["panels"].append(p)
pid += 1
y += 8

p = timeseries_panel(pid, "$protocol Operation Rate by Operation", [
    influx_target("A",
        'SELECT sum("operation_rate") FROM "node.summary.protocol" '
        'WHERE "cluster" =~ /^$cluster$/ AND "node" =~ /^$node$/ '
        'AND "protocol" = \'$protocol\' AND $timeFilter '
        'GROUP BY time($__interval), "operation" fill(null)',
        alias="$tag_operation")
], y=y, unit="ops", axis_label="Ops/s", axis_min=0)
dashboard["panels"].append(p)
pid += 1
y += 8

# ══════════════════════════════════════════════════════════════════
# Row 3: Average Latency by Class and by Operation
# ══════════════════════════════════════════════════════════════════

p = timeseries_panel(pid, "$protocol Average Latency by Class", [
    influx_target("A",
        'SELECT mean("time_avg") / 1000 FROM "node.summary.protocol" '
        'WHERE "cluster" =~ /^$cluster$/ AND "node" =~ /^$node$/ '
        'AND "protocol" = \'$protocol\' AND $timeFilter '
        'GROUP BY time($__interval), "class" fill(null)',
        alias="$tag_class")
], y=y, unit="ms", axis_label="Latency", axis_min=0)
dashboard["panels"].append(p)
pid += 1
y += 8

p = timeseries_panel(pid, "$protocol Average Latency by Operation", [
    influx_target("A",
        'SELECT mean("time_avg") / 1000 FROM "node.summary.protocol" '
        'WHERE "cluster" =~ /^$cluster$/ AND "node" =~ /^$node$/ '
        'AND "protocol" = \'$protocol\' AND $timeFilter '
        'GROUP BY time($__interval), "operation" fill(null)',
        alias="$tag_operation")
], y=y, unit="ms", axis_label="Latency", axis_min=0)
dashboard["panels"].append(p)
pid += 1
y += 8

# ══════════════════════════════════════════════════════════════════
# Row 4: Latency Distribution (avg/max/min for selected protocol)
# ══════════════════════════════════════════════════════════════════

p = timeseries_panel(pid, "$protocol Latency Distribution (Avg / Max / Min)", [
    influx_target("A",
        'SELECT mean("time_avg") / 1000 FROM "node.summary.protocol" '
        'WHERE "cluster" =~ /^$cluster$/ AND "node" =~ /^$node$/ '
        'AND "protocol" = \'$protocol\' AND $timeFilter '
        'GROUP BY time($__interval) fill(null)',
        alias="Average"),
    influx_target("B",
        'SELECT mean("time_max") / 1000 FROM "node.summary.protocol" '
        'WHERE "cluster" =~ /^$cluster$/ AND "node" =~ /^$node$/ '
        'AND "protocol" = \'$protocol\' AND $timeFilter '
        'GROUP BY time($__interval) fill(null)',
        alias="Maximum"),
    influx_target("C",
        'SELECT mean("time_min") / 1000 FROM "node.summary.protocol" '
        'WHERE "cluster" =~ /^$cluster$/ AND "node" =~ /^$node$/ '
        'AND "protocol" = \'$protocol\' AND $timeFilter '
        'GROUP BY time($__interval) fill(null)',
        alias="Minimum"),
    influx_target("D",
        'SELECT mean("time_standard_dev") / 1000 FROM "node.summary.protocol" '
        'WHERE "cluster" =~ /^$cluster$/ AND "node" =~ /^$node$/ '
        'AND "protocol" = \'$protocol\' AND $timeFilter '
        'GROUP BY time($__interval) fill(null)',
        alias="Std Dev"),
], y=y, unit="ms", axis_label="Latency", axis_min=0)
dashboard["panels"].append(p)
pid += 1
y += 8

# ══════════════════════════════════════════════════════════════════
# Row 5: Throughput by Operation
# ══════════════════════════════════════════════════════════════════

p = timeseries_panel(pid, "$protocol Inbound (Write) Throughput by Operation", [
    influx_target("A",
        'SELECT sum("in") FROM "node.summary.protocol" '
        'WHERE "cluster" =~ /^$cluster$/ AND "node" =~ /^$node$/ '
        'AND "protocol" = \'$protocol\' AND $timeFilter '
        'GROUP BY time($__interval), "operation" fill(null)',
        alias="$tag_operation")
], y=y, unit="Bps", axis_label="Throughput", axis_min=0)
dashboard["panels"].append(p)
pid += 1
y += 8

p = timeseries_panel(pid, "$protocol Outbound (Read) Throughput by Operation", [
    influx_target("A",
        'SELECT sum("out") FROM "node.summary.protocol" '
        'WHERE "cluster" =~ /^$cluster$/ AND "node" =~ /^$node$/ '
        'AND "protocol" = \'$protocol\' AND $timeFilter '
        'GROUP BY time($__interval), "operation" fill(null)',
        alias="$tag_operation")
], y=y, unit="Bps", axis_label="Throughput", axis_min=0)
dashboard["panels"].append(p)
pid += 1
y += 8

# ══════════════════════════════════════════════════════════════════
# Row 6: Per-Node Breakdown (for identifying hot nodes)
# ══════════════════════════════════════════════════════════════════

p = timeseries_panel(pid, "$protocol Operation Rate by Node", [
    influx_target("A",
        'SELECT sum("operation_rate") FROM "node.summary.protocol" '
        'WHERE "cluster" =~ /^$cluster$/ AND "node" =~ /^$node$/ '
        'AND "protocol" = \'$protocol\' AND $timeFilter '
        'GROUP BY time($__interval), "node" fill(null)',
        alias="Node $tag_node")
], y=y, unit="ops", axis_label="Ops/s", axis_min=0)
dashboard["panels"].append(p)
pid += 1
y += 8

p = timeseries_panel(pid, "$protocol Average Latency by Node", [
    influx_target("A",
        'SELECT mean("time_avg") / 1000 FROM "node.summary.protocol" '
        'WHERE "cluster" =~ /^$cluster$/ AND "node" =~ /^$node$/ '
        'AND "protocol" = \'$protocol\' AND $timeFilter '
        'GROUP BY time($__interval), "node" fill(null)',
        alias="Node $tag_node")
], y=y, unit="ms", axis_label="Latency", axis_min=0)
dashboard["panels"].append(p)
pid += 1
y += 8

# ══════════════════════════════════════════════════════════════════
# Write output
# ══════════════════════════════════════════════════════════════════

outpath = os.path.join(PROJ_ROOT, "dashboards/influxdb/protocol_summary.json")
with open(outpath, 'w') as f:
    json.dump(dashboard, f, indent=2)
    f.write('\n')

print(f"Generated {len(dashboard['panels'])} panels")
for p in dashboard["panels"]:
    ptype = p["type"]
    title = p.get("title", "")
    gp = p["gridPos"]
    print(f"  {ptype:12s} w={gp['w']:2d} x={gp['x']:2d} y={gp['y']:2d} | {title}")
