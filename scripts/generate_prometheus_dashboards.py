#!/usr/bin/env python3
"""Generate PromQL versions of the PowerScale dashboards.

Converts InfluxQL dashboards to PromQL using the Prometheus metric naming:
  InfluxDB measurement "X.Y.Z" field "value" → isilon_stat_X_Y_Z
  InfluxDB measurement "X.Y.Z" field "F"     → isilon_stat_X_Y_Z_F
  Tags (cluster, node, devid, op_name, etc.) → Prometheus labels

All dashboards use datasource UID "DS_PROMETHEUS".
"""
import json, os

PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DS = {"type": "prometheus", "uid": "DS_PROMETHEUS"}

# ── Helpers ──

def prom_target(refId, expr, legend=None, fmt="time_series"):
    t = {"refId": refId, "datasource": DS, "expr": expr,
         "legendFormat": legend or "", "editorMode": "code"}
    return t

def timeseries_panel(pid, title, targets, y, unit="short", h=8, w=24, x=0,
                     axis_label=None, axis_min=None, axis_max=None,
                     span_nulls=True, fill_opacity=10, line_width=2,
                     tooltip_sort="desc", overrides=None, stacking=None):
    fc = {
        "defaults": {
            "custom": {
                "drawStyle": "line", "lineInterpolation": "linear",
                "lineWidth": line_width, "fillOpacity": fill_opacity,
                "showPoints": "never", "pointSize": 5,
                "spanNulls": span_nulls,
                "stacking": stacking or {"mode": "none", "group": "A"},
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
               decimals=None, thresholds=None, color_mode="value",
               graph_mode="area", calc="lastNotNull", mappings=None):
    th = thresholds or {"mode": "absolute", "steps": [{"color": "green", "value": None}]}
    fc = {"defaults": {"thresholds": th, "unit": unit}, "overrides": []}
    if decimals is not None:
        fc["defaults"]["decimals"] = decimals
    if mappings:
        fc["defaults"]["mappings"] = mappings
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

def gauge_panel(pid, title, target, y, x=0, w=4, h=4, unit="short",
                decimals=None, thresholds=None, min_val=0, max_val=100,
                calc="lastNotNull"):
    th = thresholds or {"mode": "absolute", "steps": [{"color": "green", "value": None}]}
    fc = {"defaults": {"thresholds": th, "unit": unit, "min": min_val, "max": max_val}, "overrides": []}
    if decimals is not None:
        fc["defaults"]["decimals"] = decimals
    return {
        "id": pid, "type": "gauge", "title": title,
        "datasource": DS, "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "targets": [target], "fieldConfig": fc,
        "options": {
            "reduceOptions": {"calcs": [calc], "fields": "", "values": False},
            "orientation": "auto",
            "showThresholdLabels": False, "showThresholdMarkers": True,
        }
    }

def make_dashboard(title, description, tags, time_from, refresh, variables, panels):
    return {
        "id": None, "uid": None,
        "title": title, "description": description,
        "tags": tags,
        "schemaVersion": 39, "version": 1,
        "editable": True, "graphTooltip": 1, "timezone": "browser",
        "time": {"from": time_from, "to": "now"},
        "timepicker": {"refresh_intervals": ["5s","10s","30s","1m","5m","15m","30m","1h","2h","1d"]},
        "refresh": refresh, "fiscalYearStartMonth": 0, "liveNow": False,
        "templating": {"list": variables},
        "annotations": {"list": [{
            "builtIn": 1, "datasource": {"type": "grafana", "uid": "-- Grafana --"},
            "enable": True, "hide": True, "iconColor": "rgba(0, 211, 255, 1)",
            "name": "Annotations & Alerts", "type": "dashboard"
        }]},
        "panels": panels, "links": []
    }

def cluster_var(multi=False, include_all=False):
    return {
        "name": "cluster", "label": "Cluster", "type": "query",
        "datasource": DS,
        "query": 'label_values(isilon_stat_cluster_health, cluster)',
        "definition": 'label_values(isilon_stat_cluster_health, cluster)',
        "sort": 3, "multi": multi, "includeAll": include_all,
        "allValue": ".*", "current": {}, "refresh": 1, "hide": 0
    }

def node_var():
    return {
        "name": "node", "label": "Node", "type": "query",
        "datasource": DS,
        "query": 'label_values(isilon_stat_node_disk_busy_avg{cluster=~"$cluster"}, node)',
        "definition": 'label_values(isilon_stat_node_disk_busy_avg{cluster=~"$cluster"}, node)',
        "sort": 3, "multi": True, "includeAll": True,
        "allValue": ".*", "current": {}, "refresh": 1, "hide": 0
    }

GREEN_ORANGE_RED = ["rgba(50, 172, 45, 0.97)", "rgba(237, 129, 40, 0.89)", "rgba(245, 54, 54, 0.9)"]

def write_dashboard(dashboard, filename):
    outpath = os.path.join(PROJ_ROOT, "dashboards/prometheus", filename)
    with open(outpath, 'w') as f:
        json.dump(dashboard, f, indent=2)
        f.write('\n')
    print(f"  Written: {filename} ({len(dashboard['panels'])} panels)")

# ══════════════════════════════════════════════════════════════════
# 1. Cluster Capacity
# ══════════════════════════════════════════════════════════════════

def gen_cluster_capacity():
    panels = [{
        "id": 1, "type": "table",
        "title": "Cluster Capacity Utilization",
        "datasource": DS,
        "gridPos": {"h": 20, "w": 24, "x": 0, "y": 0},
        "targets": [
            {
                "refId": "A", "datasource": DS,
                "expr": '100 - isilon_stat_ifs_percent_avail{cluster=~"$cluster"}',
                "legendFormat": "{{cluster}}",
                "instant": True,
                "format": "table",
                "editorMode": "code"
            }
        ],
        "fieldConfig": {
            "defaults": {
                "custom": {
                    "cellOptions": {"type": "color-background", "mode": "row"}
                }
            },
            "overrides": [
                {"matcher": {"id": "byName", "options": "Cluster"}, "properties": [
                    {"id": "custom.width", "value": 250}
                ]},
                {"matcher": {"id": "byName", "options": "Capacity Utilization %"}, "properties": [
                    {"id": "unit", "value": "percent"},
                    {"id": "decimals", "value": 2},
                    {"id": "thresholds", "value": {"mode": "absolute", "steps": [
                        {"color": GREEN_ORANGE_RED[0], "value": None},
                        {"color": GREEN_ORANGE_RED[1], "value": 85},
                        {"color": GREEN_ORANGE_RED[2], "value": 90}
                    ]}}
                ]}
            ]
        },
        "options": {
            "showHeader": True, "cellHeight": "sm",
            "sortBy": [{"displayName": "Capacity Utilization %", "desc": True}],
            "footer": {"show": False, "reducer": ["sum"], "countRows": False, "fields": ""}
        },
        "transformations": [
            {"id": "labelsToFields", "options": {"mode": "columns"}},
            {"id": "organize", "options": {
                "excludeByName": {"Time": True, "instance": True, "job": True},
                "renameByName": {"cluster": "Cluster", "Value": "Capacity Utilization %"}
            }}
        ]
    }]

    d = make_dashboard(
        "PowerScale - Cluster Capacity",
        "Cluster capacity utilization overview for Dell PowerScale clusters",
        ["powerscale", "gostats", "prometheus"],
        "now-7d", "",
        [cluster_var(multi=True, include_all=True)],
        panels
    )
    write_dashboard(d, "cluster_capacity.json")

# ══════════════════════════════════════════════════════════════════
# Generate all
# ══════════════════════════════════════════════════════════════════

print("Generating Prometheus dashboards...")
gen_cluster_capacity()
print("Done!")
