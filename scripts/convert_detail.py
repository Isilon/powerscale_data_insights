#!/usr/bin/env python3
"""Convert cluster detail dashboard from Grafana 3.x to modern format (schemaVersion 39).

Faithful conversion of all 24 panels (text + 12 singlestats + 11 graphs).
Maps every non-default setting including:
- Stacked bars (CPU panel), negative-Y transforms (network panels)
- Stepped lines (client connections), regex measurements
- Dual Y-axes, series overrides, alias colors
- Legend table with right placement, calcs, sideWidth
- Null point handling (connected/null → spanNulls)
"""
import json, os

PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DS = {"type": "influxdb", "uid": "DS_INFLUXDB"}

with open(os.path.join(PROJ_ROOT,
    "../isilon_data_insights_connector/grafana_cluster_detail_dashboard.json")) as f:
    orig = json.load(f)

# ── Shared conversion helpers ──

def convert_query(target):
    t = {"refId": target.get("refId", "A"), "datasource": DS,
         "resultFormat": target.get("resultFormat", "time_series")}
    if target.get("rawQuery"):
        t["rawQuery"] = True
        t["query"] = target["query"].replace("$interval", "$__interval")
    else:
        measurement = target["measurement"]
        selects = target.get("select", [[]])[0]
        field = next((s["params"][0] for s in selects if s["type"] == "field"), "value")
        agg = next((s["type"] for s in selects if s["type"] in ("mean","max","min","last","sum")), "mean")
        math = next((s["params"][0] for s in selects if s["type"] == "math"), None)
        select_expr = f'{agg}("{field}")'
        if math:
            select_expr += f" {math.strip()}"
        group_tags = [g["params"][0] for g in target.get("groupBy", []) if g["type"] == "tag"]
        group_tag_str = "".join(f', "{tag}"' for tag in group_tags)
        # Handle regex measurements
        if measurement.startswith("/"):
            meas_str = measurement
        else:
            meas_str = f'"{measurement}"'
        # Handle time interval
        time_params = [g["params"][0] for g in target.get("groupBy", []) if g["type"] == "time"]
        time_interval = time_params[0].replace("$interval", "$__interval") if time_params else "$__interval"
        t["rawQuery"] = True
        t["query"] = (f'SELECT {select_expr} FROM {meas_str} '
                      f'WHERE "cluster" =~ /^$cluster$/ AND $timeFilter '
                      f'GROUP BY time({time_interval}){group_tag_str} fill(null)')
    if target.get("alias"):
        t["alias"] = target["alias"]
    if target.get("hide"):
        t["hide"] = True
    return t

def make_thresholds(threshold_str, colors):
    steps = [{"color": colors[0] if colors else "green", "value": None}]
    if threshold_str:
        for i, val in enumerate(p.strip() for p in threshold_str.split(",") if p.strip()):
            color = colors[i + 1] if i + 1 < len(colors) else "red"
            steps.append({"color": color, "value": float(val)})
    return {"mode": "absolute", "steps": steps}

def convert_mappings(panel):
    mappings = []
    if panel.get("mappingType") == 2:
        for rm in panel.get("rangeMaps", []):
            if rm.get("from") == "null": continue
            mappings.append({"type": "range", "options": {
                "from": float(rm["from"]), "to": float(rm["to"]),
                "result": {"text": rm["text"], "index": len(mappings)}}})
    value_opts = {}
    for vm in panel.get("valueMaps", []):
        if vm.get("value") and vm.get("text") and vm["value"] not in ("", "null"):
            value_opts[vm["value"]] = {"text": vm["text"], "index": len(value_opts)}
    if value_opts:
        mappings.append({"type": "value", "options": value_opts})
    return mappings if mappings else []

def calc_from_valuename(vn):
    return {"current": "lastNotNull", "avg": "mean", "max": "max",
            "min": "min", "total": "sum"}.get(vn, "lastNotNull")

# ── Singlestat → stat/gauge ──

def convert_singlestat(panel, pid, x, y, w=4, h=4):
    colors = panel.get("colors", [])
    threshold_str = panel.get("thresholds", "")
    use_gauge = panel.get("gauge", {}).get("show", False)
    has_sparkline = panel.get("sparkline", {}).get("show", False)
    panel_type = "gauge" if use_gauge else "stat"
    color_mode = "background" if panel.get("colorBackground") else "value"
    targets = [convert_query(t) for t in panel.get("targets", [])]
    thresholds = make_thresholds(threshold_str, colors)
    mappings = convert_mappings(panel)
    field_config = {"defaults": {"thresholds": thresholds, "unit": panel.get("format", "none")}, "overrides": []}
    if mappings: field_config["defaults"]["mappings"] = mappings
    if use_gauge:
        gauge = panel.get("gauge", {})
        field_config["defaults"]["min"] = gauge.get("minValue", 0)
        field_config["defaults"]["max"] = gauge.get("maxValue", 100)
    result = {
        "id": pid, "type": panel_type, "title": panel.get("title", ""),
        "datasource": DS, "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "targets": targets, "fieldConfig": field_config,
        "options": {
            "reduceOptions": {"calcs": [calc_from_valuename(panel.get("valueName", "current"))], "fields": "", "values": False},
            "colorMode": color_mode, "orientation": "auto",
        }
    }
    if panel_type == "stat":
        result["options"]["graphMode"] = "area" if has_sparkline else "none"
        result["options"]["textMode"] = "auto"
        result["options"]["wideLayout"] = True
    if panel_type == "gauge":
        result["options"]["showThresholdLabels"] = panel.get("gauge", {}).get("thresholdLabels", False)
        result["options"]["showThresholdMarkers"] = panel.get("gauge", {}).get("thresholdMarkers", True)
    return result

# ── Graph → timeseries ──

def convert_graph(panel, pid, x, y, w=24, h=8):
    # Collect negative-Y alias patterns before converting queries
    neg_y_patterns = []
    for so in panel.get("seriesOverrides", []):
        if so.get("transform") == "negative-Y":
            alias = so.get("alias", "")
            if alias.startswith("/") and alias.endswith("/"):
                import re
                neg_y_patterns.append(re.compile(alias[1:-1]))
            else:
                neg_y_patterns.append(alias)

    def target_needs_negate(target):
        """Check if this target's alias matches a negative-Y pattern."""
        alias = target.get("alias", "")
        if not alias or not neg_y_patterns:
            return False
        for pat in neg_y_patterns:
            if hasattr(pat, "search"):
                if pat.search(alias):
                    return True
            elif pat == alias:
                return True
        return False

    def negate_query(query_str):
        """Wrap a SELECT query to multiply the result by -1."""
        # Transform "SELECT mean(...) FROM" to "SELECT mean(...) * -1 FROM"
        import re
        return re.sub(r'(SELECT\s+)(.*?)(\s+FROM)', 
                      lambda m: m.group(1) + '(' + m.group(2) + ') * -1' + m.group(3),
                      query_str, count=1)

    targets = []
    for t in panel.get("targets", []):
        converted = convert_query(t)
        if target_needs_negate(t) and converted.get("rawQuery"):
            converted["query"] = negate_query(converted["query"])
        targets.append(converted)

    yaxes = panel.get("yaxes", [{}, {}])
    ax1 = yaxes[0] if len(yaxes) > 0 else {}
    ax2 = yaxes[1] if len(yaxes) > 1 else {}
    npm = panel.get("nullPointMode", "null")
    span_nulls = True if npm == "connected" else False
    fill_opacity = min(panel.get("fill", 1) * 10, 100)
    line_width = panel.get("linewidth", 1)
    show_points = "always" if panel.get("points") else "never"
    point_size = panel.get("pointradius", 5)

    if panel.get("bars") and not panel.get("lines"):
        draw_style = "bars"
        line_interpolation = "linear"
    elif panel.get("steppedLine"):
        draw_style = "line"
        line_interpolation = "stepAfter"
    else:
        draw_style = "line"
        line_interpolation = "linear"

    if panel.get("stack") and panel.get("percentage"):
        stacking = {"mode": "percent", "group": "A"}
    elif panel.get("stack"):
        stacking = {"mode": "normal", "group": "A"}
    else:
        stacking = {"mode": "none", "group": "A"}

    legend_cfg = panel.get("legend", {})
    if not legend_cfg.get("show", True):
        legend_display = "hidden"
    elif legend_cfg.get("alignAsTable"):
        legend_display = "table"
    else:
        legend_display = "list"
    legend_placement = "right" if legend_cfg.get("rightSide") else "bottom"
    legend_calcs = []
    if legend_cfg.get("min"): legend_calcs.append("min")
    if legend_cfg.get("max"): legend_calcs.append("max")
    if legend_cfg.get("avg"): legend_calcs.append("mean")
    if legend_cfg.get("current"): legend_calcs.append("lastNotNull")
    if legend_cfg.get("total"): legend_calcs.append("sum")

    tooltip_cfg = panel.get("tooltip", {})
    tooltip_mode = "multi" if tooltip_cfg.get("shared", True) else "single"
    tooltip_sort_map = {0: "none", 1: "asc", 2: "desc"}
    tooltip_sort = tooltip_sort_map.get(tooltip_cfg.get("sort", 0), "none")

    field_config = {
        "defaults": {
            "custom": {
                "drawStyle": draw_style,
                "lineInterpolation": line_interpolation,
                "lineWidth": line_width,
                "fillOpacity": fill_opacity,
                "showPoints": show_points,
                "pointSize": point_size,
                "spanNulls": span_nulls,
                "stacking": stacking,
                "axisPlacement": "auto",
                "barAlignment": 0,
                "gradientMode": "none",
                "thresholdsStyle": {"mode": "off"},
            },
            "unit": ax1.get("format", "short"),
        },
        "overrides": []
    }
    if ax1.get("label"):
        field_config["defaults"]["custom"]["axisLabel"] = ax1["label"]
    if ax1.get("min") is not None:
        field_config["defaults"]["min"] = ax1["min"]
    if ax1.get("max") is not None:
        field_config["defaults"]["max"] = ax1["max"]

    # Handle mixed bars+lines: bars as default drawStyle
    if panel.get("bars") and panel.get("lines"):
        field_config["defaults"]["custom"]["drawStyle"] = "bars"

    # Series overrides
    for so in panel.get("seriesOverrides", []):
        alias = so.get("alias", "")
        props = []
        if so.get("yaxis") == 2:
            props.append({"id": "custom.axisPlacement", "value": "right"})
            if ax2.get("format"):
                props.append({"id": "unit", "value": ax2["format"]})
            if ax2.get("label") and ax2["label"].strip():
                props.append({"id": "custom.axisLabel", "value": ax2["label"]})
            if ax2.get("min") is not None:
                props.append({"id": "min", "value": ax2["min"]})
            if ax2.get("max") is not None:
                props.append({"id": "max", "value": ax2["max"]})
        if "bars" in so:
            props.append({"id": "custom.drawStyle", "value": "bars" if so["bars"] else "line"})
        if "fill" in so:
            props.append({"id": "custom.fillOpacity", "value": so["fill"] * 10})
        if "linewidth" in so:
            props.append({"id": "custom.lineWidth", "value": so["linewidth"]})
        if so.get("transform") == "negative-Y":
            pass  # Handled via query negation (timeseries doesn't support this override)
        if props:
            if alias.startswith("/") and alias.endswith("/"):
                matcher = {"id": "byRegexp", "options": alias[1:-1]}
            else:
                matcher = {"id": "byName", "options": alias}
            field_config["overrides"].append({"matcher": matcher, "properties": props})

    # Alias colors
    for alias, color in panel.get("aliasColors", {}).items():
        field_config["overrides"].append({
            "matcher": {"id": "byName", "options": alias},
            "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": color}}]
        })

    result = {
        "id": pid, "type": "timeseries", "title": panel.get("title", ""),
        "datasource": DS, "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "targets": targets, "fieldConfig": field_config,
        "options": {
            "legend": {
                "displayMode": legend_display,
                "placement": legend_placement,
                "calcs": legend_calcs,
            },
            "tooltip": {"mode": tooltip_mode, "sort": tooltip_sort},
        }
    }
    if legend_cfg.get("sideWidth"):
        result["options"]["legend"]["width"] = legend_cfg["sideWidth"]

    return result

# ══════════════════════════════════════════════════════════════════
# Build the modernized dashboard
# ══════════════════════════════════════════════════════════════════

dashboard = {
    "id": None, "uid": None,
    "title": "PowerScale - Cluster Detail",
    "description": "Detailed performance metrics for a single Dell PowerScale cluster",
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
            "regex": "", "sort": 1, "multi": False, "includeAll": False,
            "current": {}, "refresh": 1, "hide": 0
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

# ── Row 0: Welcome (collapsed) ──
wp = orig["rows"][0]["panels"][0]
dashboard["panels"].append({
    "id": 100, "type": "row",
    "title": "Welcome to the PowerScale Cluster Detail Dashboard",
    "collapsed": True,
    "gridPos": {"h": 1, "w": 24, "x": 0, "y": y},
    "panels": [{
        "id": 101, "type": "text",
        "title": "Welcome to the PowerScale Cluster Detail Dashboard",
        "gridPos": {"h": 6, "w": 24, "x": 0, "y": y + 1},
        "options": {"mode": "markdown",
                    "content": wp.get("content", "").replace("Isilon", "PowerScale"),
                    "code": {"language": "plaintext", "showLineNumbers": False, "showMiniMap": False}}
    }]
})
y += 1

# ── Row 1: Cluster status singlestats ──
# Layout: 2 rows, same as cluster list
# Row 1a: Link(w=4) + Total Nodes + Nodes Down + Alert Status + CPU + Capacity = 6 × w=4
# Row 1b: NFS Throughput + NFS Op/s + NFS Latency + SMB2 Throughput + SMB2 Op/s + SMB2 Latency = 6 × w=4

status_panels = orig["rows"][1]["panels"]

# Text/link panel
dashboard["panels"].append({
    "id": pid, "type": "text", "title": "$cluster", "transparent": True,
    "gridPos": {"h": 4, "w": 4, "x": 0, "y": y},
    "options": {"mode": "markdown",
                "content": "### $cluster\n\n[WebUI](https://$cluster:8080/)",
                "code": {"language": "plaintext", "showLineNumbers": False, "showMiniMap": False}}
})
pid += 1

x = 4
for old_panel in status_panels[1:6]:
    p = convert_singlestat(old_panel, pid, x, y, w=4, h=4)
    dashboard["panels"].append(p)
    pid += 1
    x += 4

y += 4
x = 0
for old_panel in status_panels[6:12]:
    p = convert_singlestat(old_panel, pid, x, y, w=4, h=4)
    dashboard["panels"].append(p)
    pid += 1
    x += 4
y += 4

# ── Rows 2-10: Graph panels ──
for row in orig["rows"][2:]:
    for gp in row["panels"]:
        if gp["type"] != "graph":
            continue
        p = convert_graph(gp, pid, 0, y)
        dashboard["panels"].append(p)
        pid += 1
        y += 8

# Write output
outpath = os.path.join(PROJ_ROOT, "dashboards/influxdb/cluster_detail.json")
with open(outpath, 'w') as f:
    json.dump(dashboard, f, indent=2)
    f.write('\n')

print(f"Generated {len(dashboard['panels'])} panels")
for p in dashboard["panels"]:
    ptype = p["type"]
    title = p.get("title", "")
    nested = len(p.get("panels", []))
    extra = f" ({nested} nested)" if nested else ""
    print(f"  {ptype:12s} | {title}{extra}")
