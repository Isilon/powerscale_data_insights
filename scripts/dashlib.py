#!/usr/bin/env python3
"""Shared dashboard generation library for PowerScale Data Insights.

Provides panel builders, target constructors, template variable helpers,
and dashboard output utilities for both InfluxDB and Prometheus backends.

Usage from a generator script:

    import os, sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from dashlib import *

    def generate(backend):
        ds = DS_INFLUXDB if backend == "influxdb" else DS_PROMETHEUS
        influx = (backend == "influxdb")
        ...
"""

import json
import os

PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ---------------------------------------------------------------------------
# Datasource references
# ---------------------------------------------------------------------------

DS_INFLUXDB = {"type": "influxdb", "uid": "DS_INFLUXDB"}
DS_PROMETHEUS = {"type": "prometheus", "uid": "DS_PROMETHEUS"}

# The uid above is a literal placeholder, not a Grafana "${VAR}" template —
# that's intentional. The dashboards/<backend>/*.json files are bind-mounted
# straight into Grafana's file-based dashboard provisioner for the bundled
# Docker Compose stack (see docker/*/docker-compose*.yml), and that provider
# does not perform "${DS_X}" substitution, only exact uid matching against
# docker/*/grafana-provisioning/datasources/*.yml, which provisions a
# datasource with this exact literal uid. A second, import-ready copy with
# proper "${DS_X}" + __inputs metadata is written by write_dashboard() below
# for customers importing into their own pre-existing Grafana instance.
DS_INPUTS = {
    "influxdb": {
        "name": "DS_INFLUXDB", "label": "InfluxDB",
        "description": "InfluxDB datasource for PowerScale metrics",
        "type": "datasource", "pluginId": "influxdb", "pluginName": "InfluxDB",
    },
    "prometheus": {
        "name": "DS_PROMETHEUS", "label": "Prometheus",
        "description": "Prometheus datasource for PowerScale metrics",
        "type": "datasource", "pluginId": "prometheus", "pluginName": "Prometheus",
    },
}

DS_REQUIRES = {
    "influxdb": [
        {"type": "grafana", "id": "grafana", "name": "Grafana", "version": "10.0.0"},
        {"type": "datasource", "id": "influxdb", "name": "InfluxDB", "version": "1.0.0"},
    ],
    "prometheus": [
        {"type": "grafana", "id": "grafana", "name": "Grafana", "version": "10.0.0"},
        {"type": "datasource", "id": "prometheus", "name": "Prometheus", "version": "1.0.0"},
    ],
}

# ---------------------------------------------------------------------------
# Common constants
# ---------------------------------------------------------------------------

GREEN_ORANGE_RED = [
    "rgba(50, 172, 45, 0.97)",
    "rgba(237, 129, 40, 0.89)",
    "rgba(245, 54, 54, 0.9)",
]

# Threshold shortcuts
TH_GREEN = {"mode": "absolute", "steps": [{"color": "green", "value": None}]}

# ---------------------------------------------------------------------------
# Target builders
# ---------------------------------------------------------------------------

def influx_target(ds, refId, query, alias=None, fmt="time_series"):
    """Build an InfluxDB target dict."""
    t = {"refId": refId, "datasource": dict(ds), "rawQuery": True,
         "query": query, "resultFormat": fmt}
    if alias:
        t["alias"] = alias
    return t


def prom_target(ds, refId, expr, legend=None):
    """Build a Prometheus target dict."""
    return {"refId": refId, "datasource": dict(ds),
            "expr": expr, "legendFormat": legend or "",
            "editorMode": "code"}

# ---------------------------------------------------------------------------
# Panel builders
# ---------------------------------------------------------------------------

def timeseries_panel(ds, pid, title, targets, y, unit="short", h=8, w=24, x=0,
                     axis_label=None, axis_min=None, axis_max=None,
                     span_nulls=True, fill_opacity=10, line_width=2,
                     draw_style="line", line_interpolation="linear",
                     show_points="never", point_size=5,
                     stacking=None, tooltip_sort="desc",
                     overrides=None, legend_placement="right",
                     legend_calcs=None, legend_width=500,
                     legend_mode="table"):
    """Build a timeseries panel."""
    custom = {
        "drawStyle": draw_style,
        "lineInterpolation": line_interpolation,
        "lineWidth": line_width,
        "fillOpacity": fill_opacity,
        "showPoints": show_points,
        "pointSize": point_size,
        "spanNulls": span_nulls,
        "stacking": stacking or {"mode": "none", "group": "A"},
        "axisPlacement": "auto",
        "barAlignment": 0,
        "gradientMode": "none",
        "thresholdsStyle": {"mode": "off"},
    }
    if axis_label:
        custom["axisLabel"] = axis_label

    defaults = {"custom": custom, "unit": unit}
    if axis_min is not None:
        defaults["min"] = axis_min
    if axis_max is not None:
        defaults["max"] = axis_max

    if legend_calcs is None:
        legend_calcs = ["min", "max", "mean", "lastNotNull"]

    legend = {
        "displayMode": legend_mode,
        "placement": legend_placement,
        "calcs": legend_calcs,
    }
    if legend_width and legend_placement == "right":
        legend["width"] = legend_width

    return {
        "id": pid, "type": "timeseries", "title": title,
        "datasource": dict(ds),
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "targets": targets,
        "fieldConfig": {"defaults": defaults, "overrides": overrides or []},
        "options": {
            "legend": legend,
            "tooltip": {"mode": "multi", "sort": tooltip_sort},
        },
    }


def stat_panel(ds, pid, title, target, y, x=0, w=6, h=4, unit="short",
               decimals=None, thresholds=None, color_mode="value",
               graph_mode="area", calc="lastNotNull", mappings=None):
    """Build a stat panel."""
    th = thresholds or dict(TH_GREEN)
    defaults = {"thresholds": th, "unit": unit}
    if decimals is not None:
        defaults["decimals"] = decimals
    if mappings:
        defaults["mappings"] = mappings

    return {
        "id": pid, "type": "stat", "title": title,
        "datasource": dict(ds),
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "targets": [target],
        "fieldConfig": {"defaults": defaults, "overrides": []},
        "options": {
            "reduceOptions": {"calcs": [calc], "fields": "", "values": False},
            "colorMode": color_mode, "orientation": "auto",
            "graphMode": graph_mode, "textMode": "auto", "wideLayout": True,
        },
    }


def gauge_panel(ds, pid, title, target, y, x=0, w=4, h=4, unit="short",
                decimals=None, thresholds=None, min_val=0, max_val=100,
                calc="lastNotNull"):
    """Build a gauge panel."""
    th = thresholds or dict(TH_GREEN)
    defaults = {"thresholds": th, "unit": unit, "min": min_val, "max": max_val}
    if decimals is not None:
        defaults["decimals"] = decimals

    return {
        "id": pid, "type": "gauge", "title": title,
        "datasource": dict(ds),
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "targets": [target],
        "fieldConfig": {"defaults": defaults, "overrides": []},
        "options": {
            "reduceOptions": {"calcs": [calc], "fields": "", "values": False},
            "orientation": "auto",
            "showThresholdLabels": False,
            "showThresholdMarkers": True,
        },
    }


def text_panel(pid, content, y, h=4, w=24, x=0, title="", transparent=False):
    """Build a markdown text panel (used for README/info panels)."""
    p = {
        "id": pid, "type": "text", "title": title,
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "options": {
            "mode": "markdown",
            "content": content,
            "code": {"language": "plaintext", "showLineNumbers": False,
                     "showMiniMap": False},
        },
    }
    if transparent:
        p["transparent"] = True
    return p


def row_panel(pid, title, y, collapsed=False, repeat=None, panels=None):
    """Build a row panel."""
    p = {
        "id": pid, "type": "row", "title": title,
        "collapsed": collapsed,
        "gridPos": {"h": 1, "w": 24, "x": 0, "y": y},
        "panels": panels or [],
    }
    if repeat:
        p["repeat"] = repeat
        p["repeatDirection"] = "h"
    return p


def table_panel(ds, pid, title, targets, y, h=10, w=24, x=0,
                overrides=None, sort_by=None, transformations=None,
                cell_height="sm", interval=None):
    """Build a table panel."""
    opts = {
        "showHeader": True,
        "cellHeight": cell_height,
        "footer": {"show": False, "reducer": ["sum"],
                   "countRows": False, "fields": ""},
    }
    if sort_by:
        opts["sortBy"] = sort_by
    p = {
        "id": pid, "type": "table", "title": title,
        "datasource": dict(ds),
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "targets": targets,
        "fieldConfig": {"defaults": {}, "overrides": overrides or []},
        "options": opts,
    }
    if transformations:
        p["transformations"] = transformations
    if interval:
        p["interval"] = interval
    return p

# ---------------------------------------------------------------------------
# Dashboard builder
# ---------------------------------------------------------------------------

def make_dashboard(title, description, tags, variables, panels,
                   time_from="now-1h", refresh="30s", tooltip=1):
    """Build a complete Grafana dashboard shell."""
    return {
        "id": None, "uid": None,
        "title": title, "description": description,
        "tags": tags,
        "schemaVersion": 39, "version": 1,
        "editable": True, "graphTooltip": tooltip, "timezone": "browser",
        "time": {"from": time_from, "to": "now"},
        "timepicker": {
            "refresh_intervals": [
                "5s", "10s", "30s", "1m", "5m",
                "15m", "30m", "1h", "2h", "1d",
            ]
        },
        "refresh": refresh, "fiscalYearStartMonth": 0, "liveNow": False,
        "templating": {"list": variables},
        "annotations": {"list": [{
            "builtIn": 1,
            "datasource": {"type": "grafana", "uid": "-- Grafana --"},
            "enable": True, "hide": True,
            "iconColor": "rgba(0, 211, 255, 1)",
            "name": "Annotations & Alerts", "type": "dashboard",
        }]},
        "panels": panels, "links": [],
    }

# ---------------------------------------------------------------------------
# Template variable builders
# ---------------------------------------------------------------------------

def var_query(ds, name, label, query, multi=False, include_all=False,
              all_value=None, sort=3):
    """Build a query-type template variable."""
    v = {
        "name": name, "label": label, "type": "query",
        "datasource": dict(ds),
        "query": query, "definition": query,
        "sort": sort, "multi": multi, "includeAll": include_all,
        "current": {}, "refresh": 1, "hide": 0,
    }
    if all_value is not None:
        v["allValue"] = all_value
    elif include_all:
        # InfluxDB uses empty string, Prometheus uses regex wildcard
        v["allValue"] = "" if ds == DS_INFLUXDB else ".*"
    return v


def var_custom(name, label, values, default=None, multi=False):
    """Build a custom-type template variable with a fixed list of options."""
    if default is None:
        default = values[0]
    return {
        "name": name, "label": label, "type": "custom",
        "query": ",".join(values),
        "current": {"selected": True, "text": default, "value": default},
        "options": [{"selected": v == default, "text": v, "value": v}
                    for v in values],
        "multi": multi, "includeAll": False, "hide": 0,
    }

# ---------------------------------------------------------------------------
# Output utilities
# ---------------------------------------------------------------------------

def _importable_variant(dashboard, backend):
    """Return a copy of dashboard for manual import into a pre-existing
    Grafana instance.

    Wraps the literal DS_INFLUXDB/DS_PROMETHEUS uid as a "${DS_X}" template
    and adds an __inputs entry, which makes Grafana's Import screen prompt
    the user to pick a datasource instead of silently falling back to
    whatever datasource is marked default.
    """
    placeholder = DS_INPUTS[backend]["name"]
    raw = json.dumps(dashboard).replace(
        f'"{placeholder}"', '"${' + placeholder + '}"')
    variant = json.loads(raw)
    variant["__inputs"] = [DS_INPUTS[backend]]
    variant["__requires"] = DS_REQUIRES[backend]
    return variant


def write_dashboard(dashboard, outpath):
    """Write dashboard JSON to disk with consistent formatting.

    Also writes an import-ready variant (see _importable_variant) to
    dashboards/import/<backend>/, for users importing into an existing
    Grafana instance rather than using the bundled Docker Compose
    provisioning.
    """
    os.makedirs(os.path.dirname(outpath), exist_ok=True)
    with open(outpath, 'w') as f:
        json.dump(dashboard, f, indent=2)
        f.write('\n')
    n = len(dashboard.get("panels", []))
    print(f"  Written: {os.path.relpath(outpath, PROJ_ROOT)} ({n} panels)")

    backend = os.path.basename(os.path.dirname(outpath))
    if backend not in DS_INPUTS:
        return
    variant = _importable_variant(dashboard, backend)
    variant_path = import_outpath(backend, os.path.basename(outpath))
    os.makedirs(os.path.dirname(variant_path), exist_ok=True)
    with open(variant_path, 'w') as f:
        json.dump(variant, f, indent=2)
        f.write('\n')
    print(f"  Written: {os.path.relpath(variant_path, PROJ_ROOT)} (import-ready)")


def outpath(backend, filename):
    """Return the standard output path for a dashboard JSON file."""
    return os.path.join(PROJ_ROOT, "dashboards", backend, filename)


def import_outpath(backend, filename):
    """Return the output path for the import-ready dashboard JSON file.

    Deliberately outside dashboards/<backend>/ so it is never picked up by
    the Docker Compose stack's file-based dashboard provisioner, which
    bind-mounts dashboards/<backend>/ directly and recurses into it.
    """
    return os.path.join(PROJ_ROOT, "dashboards", "import", backend, filename)
