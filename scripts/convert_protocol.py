#!/usr/bin/env python3
"""Convert protocol dashboard from Grafana 3.x to modern format (schemaVersion 39).

Maps every non-default setting from original graph/singlestat panels to
modern timeseries/stat/gauge panels, preserving:
- All queries and aliases
- Legend settings (table mode, right placement, sideWidth, calcs)
- Tooltip settings (shared/multi, sort order)
- Axis settings (units, labels, min/max, dual axes)
- Series overrides (axis assignment, bar/line style, colors)
- Null point handling (connected → spanNulls)
- Stacking and percentage modes
- Fill opacity, line width, point display
"""
import json, sys, os

sys.path.insert(0, os.path.dirname(__file__))

DS = {"type": "influxdb", "uid": "DS_INFLUXDB"}

PROJ_ROOT = os.path.dirname(os.path.dirname(__file__))

with open(os.path.join(PROJ_ROOT,
    "../isilon_data_insights_connector/grafana_cluster_protocol_dashboard.json")) as f:
    orig = json.load(f)

# ── Shared conversion helpers (same as cluster_list converter) ──

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
        # Handle GROUP BY tags
        group_tags = [g["params"][0] for g in target.get("groupBy", []) if g["type"] == "tag"]
        group_tag_str = "".join(f', "{tag}"' for tag in group_tags)
        t["rawQuery"] = True
        t["query"] = (f'SELECT {select_expr} FROM "{measurement}" '
                      f'WHERE "cluster" =~ /^$cluster$/ AND $timeFilter '
                      f'GROUP BY time($__interval){group_tag_str} fill(null)')
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

def convert_singlestat(panel, pid, x, y, w=3, h=4):
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
    """Convert a graph panel to a modern timeseries panel."""
    targets = [convert_query(t) for t in panel.get("targets", [])]

    # Y-axes
    yaxes = panel.get("yaxes", [{}, {}])
    ax1 = yaxes[0] if len(yaxes) > 0 else {}
    ax2 = yaxes[1] if len(yaxes) > 1 else {}

    # Null point mode → spanNulls
    npm = panel.get("nullPointMode", "null")
    span_nulls = True if npm == "connected" else False

    # Line/fill/point settings
    fill_opacity = min(panel.get("fill", 1) * 10, 100)
    line_width = panel.get("linewidth", 1)
    show_points = "always" if panel.get("points") else "never"
    point_size = panel.get("pointradius", 5)

    # Draw style
    if panel.get("bars") and not panel.get("lines"):
        draw_style = "bars"
    elif panel.get("steppedLine"):
        draw_style = "line"
        line_interpolation = "stepAfter"
    else:
        draw_style = "line"
        line_interpolation = "linear"

    # Stacking — percentage mode only applies when stack is also true
    if panel.get("stack") and panel.get("percentage"):
        stacking = {"mode": "percent", "group": "A"}
    elif panel.get("stack"):
        stacking = {"mode": "normal", "group": "A"}
    else:
        stacking = {"mode": "none", "group": "A"}

    # Legend
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

    # Tooltip
    tooltip_cfg = panel.get("tooltip", {})
    tooltip_mode = "multi" if tooltip_cfg.get("shared", True) else "single"
    tooltip_sort_map = {0: "none", 1: "asc", 2: "desc"}
    tooltip_sort = tooltip_sort_map.get(tooltip_cfg.get("sort", 0), "none")

    # Field config
    field_config = {
        "defaults": {
            "custom": {
                "drawStyle": draw_style,
                "lineInterpolation": line_interpolation if draw_style == "line" else "linear",
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

    # Series overrides → field config overrides
    for so in panel.get("seriesOverrides", []):
        alias = so.get("alias", "")
        props = []
        if so.get("yaxis") == 2:
            props.append({"id": "custom.axisPlacement", "value": "right"})
            if ax2.get("format"):
                props.append({"id": "unit", "value": ax2["format"]})
            if ax2.get("label"):
                props.append({"id": "custom.axisLabel", "value": ax2["label"]})
            if ax2.get("min") is not None:
                props.append({"id": "min", "value": ax2["min"]})
            if ax2.get("max") is not None:
                props.append({"id": "max", "value": ax2["max"]})
        if "bars" in so:
            if so["bars"]:
                props.append({"id": "custom.drawStyle", "value": "bars"})
            else:
                props.append({"id": "custom.drawStyle", "value": "line"})
        if "fill" in so:
            props.append({"id": "custom.fillOpacity", "value": so["fill"] * 10})
        if "linewidth" in so:
            props.append({"id": "custom.lineWidth", "value": so["linewidth"]})
        if props:
            # Use regex matcher if alias contains regex chars
            if alias.startswith("/") and alias.endswith("/"):
                matcher = {"id": "byRegexp", "options": alias[1:-1]}
            else:
                matcher = {"id": "byName", "options": alias}
            field_config["overrides"].append({"matcher": matcher, "properties": props})

    # Alias colors → field config overrides
    for alias, color in panel.get("aliasColors", {}).items():
        field_config["overrides"].append({
            "matcher": {"id": "byName", "options": alias},
            "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": color}}]
        })

    # Handle mixed bars+lines (e.g., Operations and CPU panel where bars=true globally
    # but CPU override sets bars=false). If bars=true globally but some overrides set
    # bars=false, use bars as default drawStyle.
    if panel.get("bars") and panel.get("lines"):
        field_config["defaults"]["custom"]["drawStyle"] = "bars"
        # Series with bars=false override get line drawStyle (already handled above)

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
    "title": "PowerScale - Protocol Detail",
    "description": "Per-protocol performance analysis for a Dell PowerScale cluster",
    "tags": ["powerscale", "gostats"],
    "schemaVersion": 39, "version": 1,
    "editable": True, "graphTooltip": 1, "timezone": "browser",
    "time": {"from": "now-1h", "to": "now"},
    "timepicker": {"refresh_intervals": ["5s","10s","30s","1m","5m","15m","30m","1h","2h","1d"]},
    "refresh": "", "fiscalYearStartMonth": 0, "liveNow": False,
    "templating": {"list": [
        {
            "name": "cluster", "label": "Cluster", "type": "query",
            "datasource": DS,
            "query": 'SHOW TAG VALUES WITH KEY = "cluster"',
            "definition": 'SHOW TAG VALUES WITH KEY = "cluster"',
            "regex": "", "sort": 1, "multi": False, "includeAll": False,
            "current": {}, "refresh": 1, "hide": 0
        },
        {
            "name": "protocol", "label": "Protocol", "type": "custom",
            "query": "nfs,nfs3,nfs4,cifs,smb,smb1,smb2,hdfs,ftp,siq,lsass_in,lsass_out,papi",
            "current": {"selected": True, "text": "smb2", "value": "smb2"},
            "options": [{"selected": p == "smb2", "text": p, "value": p}
                        for p in ["nfs","nfs3","nfs4","cifs","smb","smb1","smb2","hdfs","ftp","siq","lsass_in","lsass_out","papi"]],
            "multi": False, "includeAll": False, "hide": 0
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

# ── Row 1: Welcome (collapsed) ──
welcome_row = orig["rows"][0]
wp = welcome_row["panels"][0]
dashboard["panels"].append({
    "id": 100, "type": "row",
    "title": "Welcome to the PowerScale Protocol Detail Dashboard",
    "collapsed": True,
    "gridPos": {"h": 1, "w": 24, "x": 0, "y": y},
    "panels": [{
        "id": 101, "type": "text",
        "title": "Welcome to the PowerScale Protocol Detail Dashboard",
        "gridPos": {"h": 6, "w": 24, "x": 0, "y": y + 1},
        "options": {"mode": "markdown",
                    "content": wp.get("content", "").replace("Isilon", "PowerScale"),
                    "code": {"language": "plaintext", "showLineNumbers": False, "showMiniMap": False}}
    }]
})
y += 1

# ── Row 2: Cluster status (singlestat panels) ──
status_row = orig["rows"][1]
status_panels = status_row["panels"]

# Text/link panel
link_panel = status_panels[0]  # id 22
dashboard["panels"].append({
    "id": pid, "type": "text", "title": "$cluster", "transparent": True,
    "gridPos": {"h": 4, "w": 4, "x": 0, "y": y},
    "options": {"mode": "markdown",
                "content": "### $cluster\n\n[Cluster Detail](/d/powerscale-cluster-detail/powerscale-cluster-detail?var-cluster=$cluster) | [WebUI](https://$cluster:8080/)",
                "code": {"language": "plaintext", "showLineNumbers": False, "showMiniMap": False}}
})
pid += 1

# Singlestat panels: Total Nodes, Nodes Down, Alert Status, CPU, Capacity
# Row 1: link(w=4) + 5 stats(w=4 each) = 24, fills the row
x = 4
for old_panel in status_panels[1:6]:  # Total Nodes through Capacity
    p = convert_singlestat(old_panel, pid, x, y, w=4, h=4)
    dashboard["panels"].append(p)
    pid += 1
    x += 4

# Protocol stats on second line, wider
y += 4
x = 0
for old_panel in status_panels[6:9]:  # Proto Throughput, Op/s, Latency
    p = convert_singlestat(old_panel, pid, x, y, w=8, h=4)
    dashboard["panels"].append(p)
    pid += 1
    x += 8
y += 4

# ── Row 3: Client Connections ──
client_row = orig["rows"][2]
client_panel = client_row["panels"][0]  # id 6
p = convert_graph(client_panel, pid, 0, y)
# Fix title to use PowerScale naming
p["title"] = p["title"].replace("Isilon", "PowerScale")
dashboard["panels"].append(p)
pid += 1
y += 8

# ── Row 4: CPU vs Protocol Operations ──
ops_row = orig["rows"][3]

# Panel 1: Operations and CPU
ops_cpu_panel = ops_row["panels"][0]  # id 1
p = convert_graph(ops_cpu_panel, pid, 0, y)
dashboard["panels"].append(p)
pid += 1
y += 8

# Panel 10: Operation Mix
op_mix_panel = ops_row["panels"][1]  # id 10
p = convert_graph(op_mix_panel, pid, 0, y)
dashboard["panels"].append(p)
pid += 1
y += 8

# ── Row 5: Protocol Statistics ──
proto_row = orig["rows"][4]

for gp in proto_row["panels"]:
    p = convert_graph(gp, pid, 0, y)
    dashboard["panels"].append(p)
    pid += 1
    y += 8

# Write output
outpath = os.path.join(PROJ_ROOT, "dashboards/influxdb/cluster_protocol.json")
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
