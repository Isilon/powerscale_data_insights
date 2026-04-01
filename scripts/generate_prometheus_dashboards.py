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
# 2. Cluster List
# ══════════════════════════════════════════════════════════════════

def gen_cluster_list():
    pid = 1
    y = 0
    panels = []
    C = '{cluster=~"$cluster"}'  # common label filter

    # Repeating row
    panels.append({
        "id": 200, "type": "row",
        "title": "Cluster: $cluster",
        "collapsed": False,
        "repeat": "cluster", "repeatDirection": "h",
        "gridPos": {"h": 1, "w": 24, "x": 0, "y": y},
        "panels": []
    })
    y += 1

    # Row 1: Link + core stats (w=4 each)
    panels.append({
        "id": pid, "type": "text", "title": "$cluster", "transparent": True,
        "gridPos": {"h": 4, "w": 4, "x": 0, "y": y},
        "options": {"mode": "markdown",
                    "content": "### [$cluster](/d/powerscale-cluster-detail/powerscale-cluster-detail?var-cluster=$cluster)\n\n[WebUI](https://$cluster:8080/)",
                    "code": {"language": "plaintext", "showLineNumbers": False, "showMiniMap": False}}
    })
    pid += 1

    # Total Nodes
    panels.append(stat_panel(pid, "Total Nodes",
        prom_target("A", f'isilon_stat_cluster_node_count_all{C}', "{{{{cluster}}}}"),
        y=y, x=4, w=4, h=4, unit="none", decimals=0, graph_mode="none"))
    pid += 1

    # Nodes Down
    panels.append(stat_panel(pid, "Nodes Down",
        prom_target("A", f'isilon_stat_cluster_node_count_down{C}', "{{{{cluster}}}}"),
        y=y, x=8, w=4, h=4, unit="none", decimals=0, color_mode="background",
        graph_mode="none",
        thresholds={"mode": "absolute", "steps": [
            {"color": GREEN_ORANGE_RED[0], "value": None},
            {"color": GREEN_ORANGE_RED[1], "value": 1},
            {"color": GREEN_ORANGE_RED[2], "value": 2}
        ]}))
    pid += 1

    # Alert Status
    panels.append(stat_panel(pid, "Alert Status",
        prom_target("A", f'isilon_stat_cluster_health{C}', "{{{{cluster}}}}"),
        y=y, x=12, w=4, h=4, unit="none", color_mode="background",
        graph_mode="none", calc="mean",
        thresholds={"mode": "absolute", "steps": [
            {"color": GREEN_ORANGE_RED[0], "value": None},
            {"color": GREEN_ORANGE_RED[1], "value": 0.0001},
            {"color": GREEN_ORANGE_RED[2], "value": 2}
        ]},
        mappings=[{"type": "value", "options": {
            "0": {"text": "Healthy", "index": 0},
            "1": {"text": "Attention", "index": 1},
            "2": {"text": "Down", "index": 2}
        }}]))
    pid += 1

    # CPU (gauge)
    panels.append(gauge_panel(pid, "Cluster CPU",
        prom_target("A", f'1 - isilon_stat_cluster_cpu_idle_avg{C} / 1000', "{{{{cluster}}}}"),
        y=y, x=16, w=4, h=4, unit="percentunit", min_val=0, max_val=1,
        thresholds={"mode": "absolute", "steps": [
            {"color": GREEN_ORANGE_RED[0], "value": None},
            {"color": GREEN_ORANGE_RED[1], "value": 0.80},
            {"color": GREEN_ORANGE_RED[2], "value": 0.95}
        ]}))
    pid += 1

    # Capacity (gauge)
    panels.append(gauge_panel(pid, "Cluster Capacity",
        prom_target("A", f'100 - isilon_stat_ifs_percent_avail{C}', "{{{{cluster}}}}"),
        y=y, x=20, w=4, h=4, unit="percent", min_val=0, max_val=100,
        thresholds={"mode": "absolute", "steps": [
            {"color": GREEN_ORANGE_RED[0], "value": None},
            {"color": GREEN_ORANGE_RED[1], "value": 80},
            {"color": GREEN_ORANGE_RED[2], "value": 90}
        ]}))
    pid += 1
    y += 4

    # Row 2: Protocol stats (w=4 each)
    proto_panels = [
        ("NFSv3 Throughput", f'isilon_stat_cluster_protostats_nfs_total_in_rate{C} + isilon_stat_cluster_protostats_nfs_total_out_rate{C}', "Bps", None, False, None),
        ("NFSv3 Op/s", f'isilon_stat_cluster_protostats_nfs_total_op_rate{C}', "ops", 0, False, None),
        ("NFSv3 Latency", f'isilon_stat_cluster_protostats_nfs_total_time_avg{C} / 1000', "ms", 1, True,
         {"mode": "absolute", "steps": [
            {"color": GREEN_ORANGE_RED[0], "value": None},
            {"color": GREEN_ORANGE_RED[1], "value": 10},
            {"color": GREEN_ORANGE_RED[2], "value": 25}]}),
        ("SMB2 Throughput", f'isilon_stat_cluster_protostats_smb2_total_in_rate{C} + isilon_stat_cluster_protostats_smb2_total_out_rate{C}', "Bps", None, False, None),
        ("SMB2 Op/s", f'isilon_stat_cluster_protostats_smb2_total_op_rate{C}', "ops", 0, False, None),
        ("SMB2 Latency", f'isilon_stat_cluster_protostats_smb2_total_time_avg{C} / 1000', "ms", 1, True,
         {"mode": "absolute", "steps": [
            {"color": GREEN_ORANGE_RED[0], "value": None},
            {"color": GREEN_ORANGE_RED[1], "value": 10},
            {"color": GREEN_ORANGE_RED[2], "value": 25}]}),
    ]
    for i, (title, expr, unit, dec, bg, th) in enumerate(proto_panels):
        p = stat_panel(pid, title,
            prom_target("A", expr, "{{cluster}}"),
            y=y, x=i*4, w=4, h=4, unit=unit, decimals=dec,
            color_mode="background" if bg else "value",
            thresholds=th)
        panels.append(p)
        pid += 1
    y += 4

    d = make_dashboard(
        "PowerScale - Cluster List",
        "Multi-cluster overview for Dell PowerScale clusters",
        ["powerscale", "gostats", "prometheus"],
        "now-15m", "30s",
        [cluster_var(multi=True, include_all=True)],
        panels
    )
    write_dashboard(d, "cluster_list.json")

# ══════════════════════════════════════════════════════════════════
# 3. Cluster Detail
# ══════════════════════════════════════════════════════════════════

def gen_cluster_detail():
    pid = 1
    y = 0
    panels = []
    C = '{cluster=~"$cluster"}'

    # ── Welcome row (collapsed) ──
    panels.append({
        "id": 100, "type": "row",
        "title": "Welcome to the PowerScale Cluster Detail Dashboard",
        "collapsed": True,
        "gridPos": {"h": 1, "w": 24, "x": 0, "y": y},
        "panels": [{
            "id": 101, "type": "text",
            "title": "Welcome to the PowerScale Cluster Detail Dashboard",
            "gridPos": {"h": 6, "w": 24, "x": 0, "y": y + 1},
            "options": {"mode": "markdown",
                        "content": "Use the cluster dropdown to select a cluster. All panels show data for the selected cluster.",
                        "code": {"language": "plaintext", "showLineNumbers": False, "showMiniMap": False}}
        }]
    })
    y += 1

    # ── Status panels: 2 rows like cluster list ──
    panels.append({
        "id": pid, "type": "text", "title": "$cluster", "transparent": True,
        "gridPos": {"h": 4, "w": 4, "x": 0, "y": y},
        "options": {"mode": "markdown",
                    "content": "### $cluster\n\n[WebUI](https://$cluster:8080/)",
                    "code": {"language": "plaintext", "showLineNumbers": False, "showMiniMap": False}}
    })
    pid += 1

    stat_defs = [
        ("Total Nodes", f'isilon_stat_cluster_node_count_all{C}', "none", 0, False, "none", "lastNotNull", None, None),
        ("Nodes Down", f'isilon_stat_cluster_node_count_down{C}', "none", 0, True, "none", "lastNotNull",
         {"mode": "absolute", "steps": [{"color": GREEN_ORANGE_RED[0], "value": None}, {"color": GREEN_ORANGE_RED[1], "value": 1}, {"color": GREEN_ORANGE_RED[2], "value": 2}]}, None),
        ("Alert Status", f'isilon_stat_cluster_health{C}', "none", None, True, "none", "mean",
         {"mode": "absolute", "steps": [{"color": GREEN_ORANGE_RED[0], "value": None}, {"color": GREEN_ORANGE_RED[1], "value": 0.0001}, {"color": GREEN_ORANGE_RED[2], "value": 2}]},
         [{"type": "value", "options": {"0": {"text": "Healthy"}, "1": {"text": "Attention"}, "2": {"text": "Down"}}}]),
    ]
    x = 4
    for title, expr, unit, dec, bg, gm, calc, th, maps in stat_defs:
        p = stat_panel(pid, title, prom_target("A", expr), y=y, x=x, w=4, h=4, unit=unit, decimals=dec,
                       color_mode="background" if bg else "value", graph_mode=gm, calc=calc, thresholds=th, mappings=maps)
        panels.append(p)
        pid += 1
        x += 4

    # CPU and Capacity as gauges
    panels.append(gauge_panel(pid, "Cluster CPU",
        prom_target("A", f'1 - isilon_stat_cluster_cpu_idle_avg{C} / 1000'),
        y=y, x=16, w=4, h=4, unit="percentunit", min_val=0, max_val=1,
        thresholds={"mode": "absolute", "steps": [{"color": GREEN_ORANGE_RED[0], "value": None}, {"color": GREEN_ORANGE_RED[1], "value": 0.80}, {"color": GREEN_ORANGE_RED[2], "value": 0.95}]}))
    pid += 1
    panels.append(gauge_panel(pid, "Cluster Capacity",
        prom_target("A", f'100 - isilon_stat_ifs_percent_avail{C}'),
        y=y, x=20, w=4, h=4, unit="percent", min_val=0, max_val=100,
        thresholds={"mode": "absolute", "steps": [{"color": GREEN_ORANGE_RED[0], "value": None}, {"color": GREEN_ORANGE_RED[1], "value": 80}, {"color": GREEN_ORANGE_RED[2], "value": 90}]}))
    pid += 1
    y += 4

    # Protocol stats row
    proto_panels = [
        ("NFSv3 Throughput", f'isilon_stat_cluster_protostats_nfs_total_in_rate{C} + isilon_stat_cluster_protostats_nfs_total_out_rate{C}', "Bps", None, False, None),
        ("NFSv3 Op/s", f'isilon_stat_cluster_protostats_nfs_total_op_rate{C}', "ops", 0, False, None),
        ("NFSv3 Latency", f'isilon_stat_cluster_protostats_nfs_total_time_avg{C} / 1000', "ms", 1, True,
         {"mode": "absolute", "steps": [{"color": GREEN_ORANGE_RED[0], "value": None}, {"color": GREEN_ORANGE_RED[1], "value": 10}, {"color": GREEN_ORANGE_RED[2], "value": 25}]}),
        ("SMB2 Throughput", f'isilon_stat_cluster_protostats_smb2_total_in_rate{C} + isilon_stat_cluster_protostats_smb2_total_out_rate{C}', "Bps", None, False, None),
        ("SMB2 Op/s", f'isilon_stat_cluster_protostats_smb2_total_op_rate{C}', "ops", 0, False, None),
        ("SMB2 Latency", f'isilon_stat_cluster_protostats_smb2_total_time_avg{C} / 1000', "ms", 1, True,
         {"mode": "absolute", "steps": [{"color": GREEN_ORANGE_RED[0], "value": None}, {"color": GREEN_ORANGE_RED[1], "value": 10}, {"color": GREEN_ORANGE_RED[2], "value": 25}]}),
    ]
    for i, (title, expr, unit, dec, bg, th) in enumerate(proto_panels):
        panels.append(stat_panel(pid, title, prom_target("A", expr), y=y, x=i*4, w=4, h=4, unit=unit,
                                 decimals=dec, color_mode="background" if bg else "value", thresholds=th))
        pid += 1
    y += 4

    # ── Graph panels ──

    # Capacity Utilization
    panels.append(timeseries_panel(pid, "Cluster Capacity Utilization", [
        prom_target("A", f'100 - isilon_stat_ifs_percent_avail{C}', "Cluster Capacity Utilization")
    ], y=y, unit="percent", axis_label="Cluster Capacity Utilization", axis_min=0))
    pid += 1; y += 8

    # CPU (stacked)
    panels.append(timeseries_panel(pid, "Cluster CPU for $cluster", [
        prom_target("A", f'isilon_stat_cluster_cpu_intr_avg{C} / 1000', "Interrupt"),
        prom_target("B", f'isilon_stat_cluster_cpu_sys_avg{C} / 1000', "System"),
        prom_target("C", f'isilon_stat_cluster_cpu_user_avg{C} / 1000', "User"),
        prom_target("D", f'isilon_stat_cluster_cpu_idle_avg{C} / 1000', "Idle"),
    ], y=y, unit="percentunit", axis_min=0, axis_max=1, fill_opacity=40,
       stacking={"mode": "normal", "group": "A"},
       overrides=[
           {"matcher": {"id": "byName", "options": "Idle"}, "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": "#508642"}}]},
           {"matcher": {"id": "byName", "options": "System"}, "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": "#BF1B00"}}]},
           {"matcher": {"id": "byName", "options": "User"}, "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": "#EAB839"}}]},
       ]))
    pid += 1; y += 8

    # Protocol Operations and CPU
    panels.append(timeseries_panel(pid, "Cluster Protocol Operations and CPU for $cluster", [
        prom_target("A", f'1 - isilon_stat_cluster_cpu_idle_avg{C} / 1000', "CPU"),
        prom_target("B",
            f'label_replace({{__name__=~"isilon_stat_cluster_protostats_.*_total_op_rate",cluster=~"$cluster"}}, "protocol", "$1", "__name__", "isilon_stat_cluster_protostats_(.*)_total_op_rate")',
            "{{protocol}} ops"),
    ], y=y, unit="ops", axis_label="Protocol Operations per Second", axis_min=0,
       overrides=[
           {"matcher": {"id": "byName", "options": "CPU"}, "properties": [
               {"id": "custom.drawStyle", "value": "line"}, {"id": "custom.fillOpacity", "value": 0},
               {"id": "custom.axisPlacement", "value": "right"}, {"id": "unit", "value": "percentunit"},
               {"id": "min", "value": 0}, {"id": "max", "value": 1},
               {"id": "color", "value": {"mode": "fixed", "fixedColor": "#7EB26D"}}
           ]},
       ]))
    pid += 1; y += 8

    # Client Connections (stepped line)
    panels.append(timeseries_panel(pid, "Active Client Connections by Protocol for $cluster", [
        prom_target("A",
            f'label_replace(sum by (__name__) ({{__name__=~"isilon_stat_node_clientstats_active_.*",cluster=~"$cluster"}}), "protocol", "$1", "__name__", "isilon_stat_node_clientstats_active_(.*)")',
            "{{protocol}} connections"),
    ], y=y, unit="short", axis_label="Connections",
       overrides=[{"matcher": {"id": "byFrameRefID", "options": "A"}, "properties": [
           {"id": "custom.lineInterpolation", "value": "stepAfter"}
       ]}]))
    pid += 1; y += 8

    # Open Files
    panels.append(timeseries_panel(pid, "Open Files for $cluster", [
        prom_target("A", f'sum(isilon_stat_node_open_files{C})', "Open files"),
    ], y=y, unit="short", axis_label="Open File Count", axis_min=0,
       overrides=[{"matcher": {"id": "byFrameRefID", "options": "A"}, "properties": [
           {"id": "custom.drawStyle", "value": "bars"}
       ]}]))
    pid += 1; y += 8

    # Network Traffic (negative-Y for inbound)
    panels.append(timeseries_panel(pid, "Cluster Network Traffic for $cluster", [
        prom_target("A", f'-isilon_stat_cluster_net_ext_bytes_in_rate{C}', "Bytes In"),
        prom_target("B", f'isilon_stat_cluster_net_ext_bytes_out_rate{C}', "Bytes Out"),
    ], y=y, unit="Bps", axis_label="Throughput"))
    pid += 1; y += 8

    # Network/IFS/Disk Throughput (negative-Y for writes)
    panels.append(timeseries_panel(pid, "Cluster Network, File System and Disk Throughput for $cluster", [
        prom_target("A", f'isilon_stat_cluster_net_ext_bytes_out_rate{C}', "Network Read"),
        prom_target("B", f'isilon_stat_ifs_bytes_out_rate{C}', "IFS Read"),
        prom_target("C", f'isilon_stat_cluster_disk_bytes_out_rate{C}', "Disk Read"),
        prom_target("D", f'-isilon_stat_cluster_net_ext_bytes_in_rate{C}', "Network Write"),
        prom_target("E", f'-isilon_stat_ifs_bytes_in_rate{C}', "IFS Write"),
        prom_target("F", f'-isilon_stat_cluster_disk_bytes_in_rate{C}', "Disk Write"),
    ], y=y, unit="Bps", axis_label="Throughput"))
    pid += 1; y += 8

    # Network Errors
    panels.append(timeseries_panel(pid, "Cluster Network Errors for $cluster", [
        prom_target("A", f'isilon_stat_cluster_net_ext_errors_in_rate{C}', "Inbound Errors"),
        prom_target("B", f'isilon_stat_cluster_net_ext_errors_out_rate{C}', "Outbound Errors"),
    ], y=y, unit="short", axis_label="Errors per Second", axis_min=0,
       overrides=[
           {"matcher": {"id": "byName", "options": "Inbound Errors"}, "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": "#890F02"}}]},
           {"matcher": {"id": "byName", "options": "Outbound Errors"}, "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": "#962D82"}}]},
       ]))
    pid += 1; y += 8

    # Job Engine Activity
    panels.append(timeseries_panel(pid, "Job Engine Activity for $cluster", [
        prom_target("A", f'isilon_stat_cluster_protostats_jobd_total_op_rate{C}', "Job Engine"),
    ], y=y, unit="ops", axis_label="Job Engine Operations per Second", axis_min=0, span_nulls=False))
    pid += 1; y += 8

    # OneFS File System Events
    panels.append(timeseries_panel(pid, "OneFS File System Events", [
        prom_target("A",
            f'label_replace(sum by (__name__) ({{__name__=~"isilon_stat_node_ifs_heat_.*_total",cluster=~"$cluster"}}), "event", "$1", "__name__", "isilon_stat_node_ifs_heat_(.*)_total")',
            "{{event}}"),
    ], y=y, unit="short"))
    pid += 1; y += 8

    # Cache Stats (9 queries + dual axis for Oldest Page Age)
    panels.append(timeseries_panel(pid, "Cache Stats for $cluster", [
        prom_target("A", f'sum(isilon_stat_node_ifs_cache_l1_data_prefetch_hit{C}) / sum(isilon_stat_node_ifs_cache_l1_data_prefetch_start{C})', "L1 Data Prefetch Hit Ratio"),
        prom_target("B", f'sum(isilon_stat_node_ifs_cache_l1_meta_prefetch_hit{C}) / sum(isilon_stat_node_ifs_cache_l1_meta_prefetch_start{C})', "L1 Meta-Data Prefetch Hit Ratio"),
        prom_target("C", f'sum(isilon_stat_node_ifs_cache_l1_data_read_hit{C}) / sum(isilon_stat_node_ifs_cache_l1_data_read_start{C})', "L1 Data Read Hit Ratio"),
        prom_target("D", f'sum(isilon_stat_node_ifs_cache_l1_meta_read_hit{C}) / sum(isilon_stat_node_ifs_cache_l1_meta_read_start{C})', "L1 Meta-Data Read Hit Ratio"),
        prom_target("E", f'sum(isilon_stat_node_ifs_cache_l2_data_read_hit{C}) / sum(isilon_stat_node_ifs_cache_l2_data_read_start{C})', "L2 Data Read Hit Ratio"),
        prom_target("F", f'sum(isilon_stat_node_ifs_cache_l2_meta_read_hit{C}) / sum(isilon_stat_node_ifs_cache_l2_meta_read_start{C})', "L2 Meta-Data Read Hit Ratio"),
        prom_target("G", f'sum(isilon_stat_node_ifs_cache_l3_data_read_hit{C}) / sum(isilon_stat_node_ifs_cache_l3_data_read_start{C})', "L3 Data Read Hit Ratio"),
        prom_target("H", f'sum(isilon_stat_node_ifs_cache_l3_meta_read_hit{C}) / sum(isilon_stat_node_ifs_cache_l3_meta_read_start{C})', "L3 Meta-Data Read Hit Ratio"),
        prom_target("I", f'avg(isilon_stat_node_ifs_cache_oldest_page_age{C})', "Oldest Page Age"),
    ], y=y, unit="percentunit", axis_min=0,
       overrides=[
           {"matcher": {"id": "byName", "options": "Oldest Page Age"}, "properties": [
               {"id": "custom.axisPlacement", "value": "right"}, {"id": "unit", "value": "ms"}
           ]},
       ]))
    pid += 1; y += 8

    d = make_dashboard(
        "PowerScale - Cluster Detail",
        "Detailed performance metrics for a single Dell PowerScale cluster",
        ["powerscale", "gostats", "prometheus"],
        "now-1h", "30s",
        [cluster_var(multi=False, include_all=False)],
        panels
    )
    write_dashboard(d, "cluster_detail.json")

# ══════════════════════════════════════════════════════════════════
# Generate all
# ══════════════════════════════════════════════════════════════════

print("Generating Prometheus dashboards...")
gen_cluster_capacity()
gen_cluster_list()
gen_cluster_detail()
print("Done! (remaining dashboards in generate_prometheus_remaining.py)")
