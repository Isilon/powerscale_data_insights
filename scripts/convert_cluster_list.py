#!/usr/bin/env python3
"""Convert cluster list dashboard from Grafana 3.x to modern format (schemaVersion 39).

Maps every non-default setting from the original singlestat/text panels to
modern stat/gauge/text panels, preserving queries, thresholds, colors, links,
sparklines, gauges, value maps, and the row-repeat mechanism.
"""
import json

DS = {"type": "influxdb", "uid": "DS_INFLUXDB"}

with open("/home/timw/work/isilon/projects/isilon_data_insights_v2/isilon_data_insights_connector/grafana_cluster_list_dashboard.json") as f:
    orig = json.load(f)

def convert_query(target):
    """Convert old query-builder target to raw InfluxQL target."""
    t = {"refId": target.get("refId", "A"), "datasource": DS, "resultFormat": target.get("resultFormat", "time_series")}
    if target.get("rawQuery"):
        t["rawQuery"] = True
        t["query"] = target["query"].replace("$interval", "$__interval")
    else:
        # Build raw query from query-builder fields
        measurement = target["measurement"]
        selects = target.get("select", [[]])[0]
        field = next((s["params"][0] for s in selects if s["type"] == "field"), "value")
        agg = next((s["type"] for s in selects if s["type"] in ("mean", "max", "min", "last", "sum")), "mean")
        math = next((s["params"][0] for s in selects if s["type"] == "math"), None)
        
        select_expr = f'{agg}("{field}")'
        if math:
            select_expr += f" {math.strip()}"
        
        t["rawQuery"] = True
        t["query"] = f'SELECT {select_expr} FROM "{measurement}" WHERE "cluster" =~ /^$cluster$/ AND $timeFilter GROUP BY time($__interval) fill(null)'
    return t

def make_thresholds(threshold_str, colors):
    """Convert old threshold string + colors to modern threshold steps."""
    steps = [{"color": colors[0] if colors else "green", "value": None}]
    if threshold_str:
        parts = [p.strip() for p in threshold_str.split(",") if p.strip()]
        for i, val in enumerate(parts):
            color = colors[i + 1] if i + 1 < len(colors) else "red"
            steps.append({"color": color, "value": float(val)})
    return {"mode": "absolute", "steps": steps}

def convert_mappings(panel):
    """Convert old valueMaps/rangeMaps to modern mappings."""
    mappings = []
    mapping_type = panel.get("mappingType", 1)
    
    if mapping_type == 2:  # range to text
        for rm in panel.get("rangeMaps", []):
            if rm.get("from") == "null":
                continue
            mappings.append({
                "type": "range",
                "options": {
                    "from": float(rm["from"]),
                    "to": float(rm["to"]),
                    "result": {"text": rm["text"], "index": len(mappings)}
                }
            })
    
    # Also check valueMaps for explicit value mappings
    value_opts = {}
    for vm in panel.get("valueMaps", []):
        if vm.get("value") and vm.get("text") and vm["value"] not in ("", "null"):
            value_opts[vm["value"]] = {"text": vm["text"], "index": len(value_opts)}
    if value_opts:
        mappings.append({"type": "value", "options": value_opts})
    
    return mappings if mappings else []

def calc_from_valuename(vn):
    """Map old valueName to modern reduce calc."""
    return {
        "current": "lastNotNull",
        "avg": "mean",
        "max": "max",
        "min": "min",
        "total": "sum",
    }.get(vn, "lastNotNull")

def convert_singlestat(panel, panel_id, x, y, w=2, h=4):
    """Convert singlestat to modern stat or gauge panel."""
    colors = panel.get("colors", [])
    threshold_str = panel.get("thresholds", "")
    use_gauge = panel.get("gauge", {}).get("show", False)
    has_sparkline = panel.get("sparkline", {}).get("show", False)
    
    # Determine panel type and graphMode
    if use_gauge:
        panel_type = "gauge"
    else:
        panel_type = "stat"
    
    # Color mode
    if panel.get("colorBackground"):
        color_mode = "background"
    elif panel.get("colorValue"):
        color_mode = "value"
    else:
        color_mode = "value"
    
    # Build target
    targets = [convert_query(t) for t in panel.get("targets", [])]
    
    # Build field config
    thresholds = make_thresholds(threshold_str, colors)
    mappings = convert_mappings(panel)
    
    field_config = {
        "defaults": {
            "thresholds": thresholds,
            "unit": panel.get("format", "none"),
        },
        "overrides": []
    }
    if mappings:
        field_config["defaults"]["mappings"] = mappings
    
    # Gauge-specific: min/max
    if use_gauge:
        gauge = panel.get("gauge", {})
        field_config["defaults"]["min"] = gauge.get("minValue", 0)
        field_config["defaults"]["max"] = gauge.get("maxValue", 100)
    
    result = {
        "id": panel_id,
        "type": panel_type,
        "title": panel.get("title", ""),
        "datasource": DS,
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "targets": targets,
        "fieldConfig": field_config,
        "options": {
            "reduceOptions": {
                "calcs": [calc_from_valuename(panel.get("valueName", "current"))],
                "fields": "",
                "values": False
            },
            "colorMode": color_mode,
            "orientation": "auto",
        }
    }
    
    if panel_type == "stat":
        result["options"]["graphMode"] = "area" if has_sparkline else "none"
        result["options"]["textMode"] = "auto"
        result["options"]["wideLayout"] = True
    
    if panel_type == "gauge":
        result["options"]["showThresholdLabels"] = panel.get("gauge", {}).get("thresholdLabels", False)
        result["options"]["showThresholdMarkers"] = panel.get("gauge", {}).get("thresholdMarkers", True)
    
    # Don't add per-panel links -- links live on the cluster name text panel only
    
    return result

# Build dashboard
dashboard = {
    "id": None,
    "uid": None,
    "title": "PowerScale - Cluster List",
    "description": "Multi-cluster overview for Dell PowerScale clusters",
    "tags": ["powerscale", "gostats"],
    "schemaVersion": 39,
    "version": 1,
    "editable": True,
    "graphTooltip": 0,
    "timezone": "browser",
    "time": {"from": "now-15m", "to": "now"},
    "timepicker": {
        "refresh_intervals": ["5s", "10s", "30s", "1m", "5m", "15m", "30m", "1h", "2h", "1d"]
    },
    "refresh": "30s",
    "fiscalYearStartMonth": 0,
    "liveNow": False,
    "templating": {
        "list": [
            {
                "name": "cluster",
                "label": "Cluster",
                "type": "query",
                "datasource": DS,
                "query": 'SHOW TAG VALUES WITH KEY = "cluster"',
                "definition": 'SHOW TAG VALUES WITH KEY = "cluster"',
                "regex": "",
                "sort": 1,
                "multi": True,
                "includeAll": True,
                "allValue": "",
                "current": {},
                "refresh": 1,
                "hide": 0
            }
        ]
    },
    "annotations": {
        "list": [{
            "builtIn": 1,
            "datasource": {"type": "grafana", "uid": "-- Grafana --"},
            "enable": True,
            "hide": True,
            "iconColor": "rgba(0, 211, 255, 1)",
            "name": "Annotations & Alerts",
            "type": "dashboard"
        }]
    },
    "panels": [],
    "links": []
}

# Row 1: Welcome (collapsed)
welcome_row = orig["rows"][0]
welcome_panel = welcome_row["panels"][0]
dashboard["panels"].append({
    "id": 100,
    "type": "row",
    "title": "Welcome to the PowerScale Cluster Summary Dashboard",
    "collapsed": True,
    "gridPos": {"h": 1, "w": 24, "x": 0, "y": 0},
    "panels": [{
        "id": 101,
        "type": "text",
        "title": "Welcome to the PowerScale Cluster Summary Dashboard",
        "gridPos": {"h": 6, "w": 24, "x": 0, "y": 1},
        "options": {
            "mode": "markdown",
            "content": welcome_panel["content"].replace("Isilon", "PowerScale"),
            "code": {"language": "plaintext", "showLineNumbers": False, "showMiniMap": False}
        }
    }]
})

# Row 2: Cluster metrics (repeating)
metrics_row = orig["rows"][1]
panels_in_row = metrics_row["panels"]

# Repeating row header
dashboard["panels"].append({
    "id": 200,
    "type": "row",
    "title": "Cluster: $cluster",
    "collapsed": False,
    "repeat": "cluster",
    "repeatDirection": "h",
    "gridPos": {"h": 1, "w": 24, "x": 0, "y": 1},
    "panels": []
})

# Layout: 2 rows per cluster, wider panels for readable titles
# Row 1: Cluster Name (w=4) + Total Nodes (w=4) + Nodes Down (w=4) + Alert Status (w=4) + CPU (w=4) + Capacity (w=4)
# Row 2: NFS Throughput (w=4) + NFS Op/s (w=4) + NFS Latency (w=4) + SMB2 Throughput (w=4) + SMB2 Op/s (w=4) + SMB2 Latency (w=4)
pid = 1
y = 2  # after row header
h = 4  # panel height
w = 4  # panel width

# Panel 1: Cluster name/link (text) -- links live here only
text_panel = panels_in_row[0]  # id 35
dashboard["panels"].append({
    "id": pid,
    "type": "text",
    "title": "$cluster",
    "transparent": True,
    "gridPos": {"h": h, "w": w, "x": 0, "y": y},
    "options": {
        "mode": "markdown",
        "content": "### [$cluster](/d/powerscale-cluster-detail/powerscale-cluster-detail?var-cluster=$cluster)\n\n[WebUI](https://$cluster:8080/)",
        "code": {"language": "plaintext", "showLineNumbers": False, "showMiniMap": False}
    }
})
pid += 1

# Row 1 stat panels: Total Nodes, Nodes Down, Alert Status, CPU, Capacity
# (indices 1-5 in panels_in_row)
for i, old_panel in enumerate(panels_in_row[1:6]):
    x = (i + 1) * w
    new_panel = convert_singlestat(old_panel, pid, x, y, w=w, h=h)
    dashboard["panels"].append(new_panel)
    pid += 1

# Row 2 stat panels: NFS Throughput, NFS Op/s, NFS Latency, SMB2 Throughput, SMB2 Op/s, SMB2 Latency
# (indices 6-11 in panels_in_row)
y2 = y + h
for i, old_panel in enumerate(panels_in_row[6:12]):
    x = i * w
    new_panel = convert_singlestat(old_panel, pid, x, y2, w=w, h=h)
    dashboard["panels"].append(new_panel)
    pid += 1

# Write output
outpath = "/home/timw/work/isilon/projects/isilon_data_insights_v2/powerscale_data_insights/dashboards/influxdb/cluster_list.json"
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
