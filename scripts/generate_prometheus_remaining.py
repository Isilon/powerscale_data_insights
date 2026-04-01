#!/usr/bin/env python3
"""Generate remaining 6 Prometheus dashboards (protocol detail through system workload).

Imports helpers from generate_prometheus_dashboards.py.
"""
import json, os, sys

# Import from the main generator
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# We need the helpers but not the generation calls, so exec just the definitions
PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
main_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "generate_prometheus_dashboards.py")
with open(main_file) as f:
    code = f.read()
# Execute only up to the "Generate all" section to get helper functions
gen_idx = code.index("# Generate all")
exec(compile(code[:gen_idx], main_file, "exec"))

# Now DS, prom_target, timeseries_panel, stat_panel, gauge_panel, make_dashboard,
# cluster_var, node_var, write_dashboard, GREEN_ORANGE_RED are all available

# ══════════════════════════════════════════════════════════════════
# 4. Protocol Detail
# ══════════════════════════════════════════════════════════════════

def gen_protocol_detail():
    pid = 1; y = 0; panels = []
    C = '{cluster=~"$cluster"}'
    PROTO_LIST = "nfs,nfs3,nfs4,cifs,smb,smb1,smb2,hdfs,ftp,siq,lsass_in,lsass_out,papi"

    panels.append({
        "id": pid, "type": "text", "title": "$cluster", "transparent": True,
        "gridPos": {"h": 4, "w": 4, "x": 0, "y": y},
        "options": {"mode": "markdown",
                    "content": "### $cluster\n\n[Cluster Detail](/d/powerscale-cluster-detail/powerscale-cluster-detail?var-cluster=$cluster) | [WebUI](https://$cluster:8080/)",
                    "code": {"language": "plaintext", "showLineNumbers": False, "showMiniMap": False}}
    }); pid += 1

    core = [
        ("Total Nodes", f'isilon_stat_cluster_node_count_all{C}', "none", 0, False, "none", None, None),
        ("Nodes Down", f'isilon_stat_cluster_node_count_down{C}', "none", 0, True, "none",
         {"mode": "absolute", "steps": [{"color": GREEN_ORANGE_RED[0], "value": None}, {"color": GREEN_ORANGE_RED[1], "value": 1}, {"color": GREEN_ORANGE_RED[2], "value": 2}]}, None),
        ("Alert Status", f'isilon_stat_cluster_health{C}', "none", None, True, "none",
         {"mode": "absolute", "steps": [{"color": GREEN_ORANGE_RED[0], "value": None}, {"color": GREEN_ORANGE_RED[1], "value": 0.0001}, {"color": GREEN_ORANGE_RED[2], "value": 2}]},
         [{"type": "value", "options": {"0": {"text": "Healthy"}, "1": {"text": "Attention"}, "2": {"text": "Down"}}}]),
    ]
    x = 4
    for title, expr, unit, dec, bg, gm, th, maps in core:
        panels.append(stat_panel(pid, title, prom_target("A", expr), y=y, x=x, w=4, h=4, unit=unit,
                                 decimals=dec, color_mode="background" if bg else "value", graph_mode=gm, thresholds=th, mappings=maps))
        pid += 1; x += 4

    panels.append(gauge_panel(pid, "Cluster CPU",
        prom_target("A", f'1 - isilon_stat_cluster_cpu_idle_avg{C} / 1000'),
        y=y, x=16, w=4, h=4, unit="percentunit", min_val=0, max_val=1,
        thresholds={"mode": "absolute", "steps": [{"color": GREEN_ORANGE_RED[0], "value": None}, {"color": GREEN_ORANGE_RED[1], "value": 0.80}, {"color": GREEN_ORANGE_RED[2], "value": 0.95}]}))
    pid += 1
    panels.append(gauge_panel(pid, "Cluster Capacity",
        prom_target("A", f'100 - isilon_stat_ifs_percent_avail{C}'),
        y=y, x=20, w=4, h=4, unit="percent", min_val=0, max_val=100,
        thresholds={"mode": "absolute", "steps": [{"color": GREEN_ORANGE_RED[0], "value": None}, {"color": GREEN_ORANGE_RED[1], "value": 80}, {"color": GREEN_ORANGE_RED[2], "value": 90}]}))
    pid += 1; y += 4

    ps = [
        ("$protocol Throughput", f'isilon_stat_cluster_protostats_${{protocol}}_total_in_rate{C} + isilon_stat_cluster_protostats_${{protocol}}_total_out_rate{C}', "Bps", None, False, None),
        ("$protocol Op/s", f'isilon_stat_cluster_protostats_${{protocol}}_total_op_rate{C}', "ops", 0, False, None),
        ("$protocol Latency", f'isilon_stat_cluster_protostats_${{protocol}}_total_time_avg{C} / 1000', "ms", 1, True,
         {"mode": "absolute", "steps": [{"color": GREEN_ORANGE_RED[0], "value": None}, {"color": GREEN_ORANGE_RED[1], "value": 10}, {"color": GREEN_ORANGE_RED[2], "value": 25}]}),
    ]
    for i, (title, expr, unit, dec, bg, th) in enumerate(ps):
        panels.append(stat_panel(pid, title, prom_target("A", expr), y=y, x=i*8, w=8, h=4, unit=unit,
                                 decimals=dec, color_mode="background" if bg else "value", thresholds=th))
        pid += 1
    y += 4

    graph_panels = [
        ("$protocol Client Connections for $cluster", [
            prom_target("A", f'sum(isilon_stat_node_clientstats_connected_${{protocol}}{C})', "Established"),
            prom_target("B", f'sum(isilon_stat_node_clientstats_active_${{protocol}}{C})', "Active"),
        ], "short", "Connections", 0, None, None),
        ("Cluster $protocol Operations and CPU for $cluster", [
            prom_target("A", f'1 - isilon_stat_cluster_cpu_idle_avg{C} / 1000', "CPU"),
            prom_target("B", f'isilon_stat_cluster_protostats_${{protocol}}_total_op_rate{C}', "$protocol ops"),
        ], "ops", "Ops/s", 0,
         [{"matcher": {"id": "byName", "options": "CPU"}, "properties": [
             {"id": "custom.drawStyle", "value": "line"}, {"id": "custom.fillOpacity", "value": 0},
             {"id": "custom.axisPlacement", "value": "right"}, {"id": "unit", "value": "percentunit"},
             {"id": "min", "value": 0}, {"id": "max", "value": 1},
             {"id": "color", "value": {"mode": "fixed", "fixedColor": "#7EB26D"}}]}], None),
        ("$protocol Operations Mix for $cluster", [
            prom_target("A", f'isilon_stat_cluster_protostats_${{protocol}}_op_rate{C}', "{{op_name}} ({{class_name}})"),
            prom_target("B", f'sum(isilon_stat_cluster_protostats_${{protocol}}_op_rate{C})', "Total"),
        ], "ops", None, 0, None, None),
        ("$protocol Throughput for $cluster", [
            prom_target("A", f'isilon_stat_cluster_protostats_${{protocol}}_total_in_rate{C}', "Write"),
            prom_target("B", f'isilon_stat_cluster_protostats_${{protocol}}_total_out_rate{C}', "Read"),
            prom_target("C", f'isilon_stat_cluster_protostats_${{protocol}}_total_in_rate{C} + isilon_stat_cluster_protostats_${{protocol}}_total_out_rate{C}', "Total"),
        ], "Bps", "Throughput", 0, None, None),
        ("$protocol Throughput by Operation for $cluster", [
            prom_target("A", f'isilon_stat_cluster_protostats_${{protocol}}_in_rate{C}', "{{op_name}} write"),
            prom_target("B", f'isilon_stat_cluster_protostats_${{protocol}}_out_rate{C}', "{{op_name}} read"),
        ], "Bps", "Throughput", 0, None, None),
        ("Average Latency for all $protocol Operations for $cluster", [
            prom_target("A", f'isilon_stat_cluster_protostats_${{protocol}}_total_time_avg{C}', "$protocol avg"),
            prom_target("B", f'isilon_stat_cluster_protostats_${{protocol}}_total_time_max{C}', "$protocol max"),
            prom_target("C", f'isilon_stat_cluster_protostats_${{protocol}}_total_time_min{C}', "$protocol min"),
        ], "µs", "Latency", 0, None, None),
        ("Average Latency by $protocol Operation for $cluster", [
            prom_target("A", f'isilon_stat_cluster_protostats_${{protocol}}_time_avg{C} / 1000', "{{op_name}} ({{class_name}})"),
        ], "ms", "Latency", 0, None, None),
        ("Maximum Latency by $protocol Operation for $cluster", [
            prom_target("A", f'isilon_stat_cluster_protostats_${{protocol}}_time_max{C} / 1000', "{{op_name}} ({{class_name}})"),
        ], "ms", "Latency", 0, None, None),
    ]
    for title, targets, unit, label, minv, overrides, _ in graph_panels:
        panels.append(timeseries_panel(pid, title, targets, y=y, unit=unit,
                                       axis_label=label, axis_min=minv, overrides=overrides))
        pid += 1; y += 8

    proto_var = {"name": "protocol", "label": "Protocol", "type": "custom",
                 "query": PROTO_LIST,
                 "current": {"selected": True, "text": "nfs", "value": "nfs"},
                 "options": [{"selected": p == "nfs", "text": p, "value": p} for p in PROTO_LIST.split(",")],
                 "multi": False, "includeAll": False, "hide": 0}

    d = make_dashboard("PowerScale - Protocol Detail",
        "Per-protocol performance analysis for a Dell PowerScale cluster",
        ["powerscale", "gostats", "prometheus"], "now-1h", "30s",
        [cluster_var(multi=False, include_all=False), proto_var], panels)
    write_dashboard(d, "cluster_protocol.json")

# ══════════════════════════════════════════════════════════════════
# 5. Drive Statistics
# ══════════════════════════════════════════════════════════════════

def gen_drive_stats():
    pid = 1; y = 0; panels = []
    C = '{cluster=~"$cluster",node=~"$node"}'

    for i, (title, expr, unit, dec, w) in enumerate([
        ("Total Disk IOPS", f'sum(isilon_stat_node_disk_xfers_in_rate_avg{C}) + sum(isilon_stat_node_disk_xfers_out_rate_avg{C})', "ops", 0, 8),
        ("Disk Read IOPS", f'sum(isilon_stat_node_disk_xfers_out_rate_avg{C})', "ops", 0, 8),
        ("Disk Write IOPS", f'sum(isilon_stat_node_disk_xfers_in_rate_avg{C})', "ops", 0, 8),
    ]):
        panels.append(stat_panel(pid, title, prom_target("A", expr), y=y, x=i*8, w=w, h=4, unit=unit, decimals=dec))
        pid += 1
    y += 4
    for i, (title, expr, unit) in enumerate([
        ("Disk Read Throughput", f'sum(isilon_stat_node_disk_bytes_out_rate_avg{C})', "Bps"),
        ("Disk Write Throughput", f'sum(isilon_stat_node_disk_bytes_in_rate_avg{C})', "Bps"),
    ]):
        panels.append(stat_panel(pid, title, prom_target("A", expr), y=y, x=i*12, w=12, h=4, unit=unit, decimals=1))
        pid += 1
    y += 4

    for title, expr, legend, unit, label, minv in [
        ("Disk Access Latency by Node", f'isilon_stat_node_disk_access_latency_avg{C} * 1000', "Node {{node}}", "ms", "Latency", 0),
        ("I/O Scheduler Latency by Node", f'isilon_stat_node_disk_iosched_latency_avg{C} * 1000', "Node {{node}}", "ms", "Latency", 0),
        ("I/O Scheduler Queue Depth by Node", f'isilon_stat_node_disk_iosched_queue_avg{C}', "Node {{node}}", "short", "Queue Depth", 0),
        ("Disk Busy % by Node", f'isilon_stat_node_disk_busy_avg{C} / 10', "Node {{node}}", "percent", "Busy %", 0),
        ("Disk Read Throughput by Node", f'isilon_stat_node_disk_bytes_out_rate_avg{C}', "Node {{node}}", "Bps", "Throughput", 0),
        ("Disk Write Throughput by Node", f'isilon_stat_node_disk_bytes_in_rate_avg{C}', "Node {{node}}", "Bps", "Throughput", 0),
        ("Disk Read IOPS by Node", f'isilon_stat_node_disk_xfers_out_rate_avg{C}', "Node {{node}}", "ops", "IOPS", 0),
        ("Disk Write IOPS by Node", f'isilon_stat_node_disk_xfers_in_rate_avg{C}', "Node {{node}}", "ops", "IOPS", 0),
        ("Average I/O Size by Node (Read)", f'isilon_stat_node_disk_xfer_size_out_avg{C}', "Node {{node}}", "bytes", "I/O Size", 0),
        ("Average I/O Size by Node (Write)", f'isilon_stat_node_disk_xfer_size_in_avg{C}', "Node {{node}}", "bytes", "I/O Size", 0),
        ("Slow Disk Accesses by Node", f'isilon_stat_node_disk_access_slow_avg{C}', "Node {{node}}", "ops", "Slow/s", 0),
    ]:
        panels.append(timeseries_panel(pid, title, [prom_target("A", expr, legend)], y=y, unit=unit, axis_label=label, axis_min=minv))
        pid += 1; y += 8

    d = make_dashboard("PowerScale - Drive Statistics",
        "Per-node disk performance: latency, queue depth, utilization, throughput, and IOPS",
        ["powerscale", "gostats", "prometheus"], "now-1h", "30s",
        [cluster_var(), node_var()], panels)
    write_dashboard(d, "drive_stats.json")

# ══════════════════════════════════════════════════════════════════
# 6. Protocol Summary Stats
# ══════════════════════════════════════════════════════════════════

def gen_protocol_summary():
    pid = 1; y = 0; panels = []
    C = '{cluster=~"$cluster",node=~"$node",protocol=~"$protocol"}'

    for i, (title, expr, unit, dec) in enumerate([
        ("$protocol Ops/s", f'sum(isilon_stat_node_summary_protocol_operation_rate{C})', "ops", 0),
        ("$protocol Avg Latency", f'avg(isilon_stat_node_summary_protocol_time_avg{C}) / 1000', "ms", 2),
        ("$protocol Inbound", f'sum(isilon_stat_node_summary_protocol_in{C})', "Bps", None),
        ("$protocol Outbound", f'sum(isilon_stat_node_summary_protocol_out{C})', "Bps", None),
    ]):
        panels.append(stat_panel(pid, title, prom_target("A", expr), y=y, x=i*6, w=6, h=4, unit=unit, decimals=dec))
        pid += 1
    y += 4

    for title, targets, unit in [
        ("$protocol Operation Rate by Class", [prom_target("A", f'sum by (class) (isilon_stat_node_summary_protocol_operation_rate{C})', "{{class}}")], "ops"),
        ("$protocol Operation Rate by Operation", [prom_target("A", f'sum by (operation) (isilon_stat_node_summary_protocol_operation_rate{C})', "{{operation}}")], "ops"),
        ("$protocol Average Latency by Class", [prom_target("A", f'avg by (class) (isilon_stat_node_summary_protocol_time_avg{C}) / 1000', "{{class}}")], "ms"),
        ("$protocol Average Latency by Operation", [prom_target("A", f'avg by (operation) (isilon_stat_node_summary_protocol_time_avg{C}) / 1000', "{{operation}}")], "ms"),
        ("$protocol Latency Distribution (Avg / Max / Min / StdDev)", [
            prom_target("A", f'avg(isilon_stat_node_summary_protocol_time_avg{C}) / 1000', "Average"),
            prom_target("B", f'avg(isilon_stat_node_summary_protocol_time_max{C}) / 1000', "Maximum"),
            prom_target("C", f'avg(isilon_stat_node_summary_protocol_time_min{C}) / 1000', "Minimum"),
            prom_target("D", f'avg(isilon_stat_node_summary_protocol_time_standard_dev{C}) / 1000', "Std Dev"),
        ], "ms"),
        ("$protocol Inbound Throughput by Operation", [prom_target("A", f'sum by (operation) (isilon_stat_node_summary_protocol_in{C})', "{{operation}}")], "Bps"),
        ("$protocol Outbound Throughput by Operation", [prom_target("A", f'sum by (operation) (isilon_stat_node_summary_protocol_out{C})', "{{operation}}")], "Bps"),
        ("$protocol Operation Rate by Node", [prom_target("A", f'sum by (node) (isilon_stat_node_summary_protocol_operation_rate{C})', "Node {{node}}")], "ops"),
        ("$protocol Average Latency by Node", [prom_target("A", f'avg by (node) (isilon_stat_node_summary_protocol_time_avg{C}) / 1000', "Node {{node}}")], "ms"),
    ]:
        panels.append(timeseries_panel(pid, title, targets, y=y, unit=unit, axis_min=0))
        pid += 1; y += 8

    prot_var = {"name": "protocol", "label": "Protocol", "type": "query", "datasource": DS,
                "query": 'label_values(isilon_stat_node_summary_protocol_operation_rate{cluster=~"$cluster"}, protocol)',
                "definition": 'label_values(isilon_stat_node_summary_protocol_operation_rate{cluster=~"$cluster"}, protocol)',
                "sort": 1, "multi": False, "includeAll": False, "current": {}, "refresh": 1, "hide": 0}

    d = make_dashboard("PowerScale - Protocol Summary Stats",
        "Per-node, per-operation protocol statistics with latency distribution",
        ["powerscale", "gostats", "summary", "prometheus"], "now-1h", "30s",
        [cluster_var(), node_var(), prot_var], panels)
    write_dashboard(d, "protocol_summary.json")

# ══════════════════════════════════════════════════════════════════
# 7. Client Summary Stats
# ══════════════════════════════════════════════════════════════════

def gen_client_summary():
    pid = 1; y = 0; panels = []
    C = '{cluster=~"$cluster",node=~"$node",protocol=~"$protocol"}'

    for i, (title, expr, unit, dec) in enumerate([
        ("Total Client Ops/s", f'sum(isilon_stat_node_summary_client_operation_rate{C})', "ops", 0),
        ("Average Latency", f'avg(isilon_stat_node_summary_client_time_avg{C}) / 1000', "ms", 2),
        ("Inbound Throughput", f'sum(isilon_stat_node_summary_client_in{C})', "Bps", None),
        ("Outbound Throughput", f'sum(isilon_stat_node_summary_client_out{C})', "Bps", None),
    ]):
        panels.append(stat_panel(pid, title, prom_target("A", expr), y=y, x=i*6, w=6, h=4, unit=unit, decimals=dec))
        pid += 1
    y += 4

    for title, targets, unit in [
        ("Operation Rate by Client", [prom_target("A", f'sum by (remote_addr) (isilon_stat_node_summary_client_operation_rate{C})', "{{remote_addr}}")], "ops"),
        ("Average Latency by Client", [prom_target("A", f'avg by (remote_addr) (isilon_stat_node_summary_client_time_avg{C}) / 1000', "{{remote_addr}}")], "ms"),
        ("Operation Rate by Protocol", [prom_target("A", f'sum by (protocol) (isilon_stat_node_summary_client_operation_rate{C})', "{{protocol}}")], "ops"),
        ("Average Latency by Protocol", [prom_target("A", f'avg by (protocol) (isilon_stat_node_summary_client_time_avg{C}) / 1000', "{{protocol}}")], "ms"),
        ("Operation Rate by Class", [prom_target("A", f'sum by (class) (isilon_stat_node_summary_client_operation_rate{C})', "{{class}}")], "ops"),
        ("Average Latency by Class", [prom_target("A", f'avg by (class) (isilon_stat_node_summary_client_time_avg{C}) / 1000', "{{class}}")], "ms"),
        ("Operation Rate by Node", [prom_target("A", f'sum by (node) (isilon_stat_node_summary_client_operation_rate{C})', "Node {{node}}")], "ops"),
        ("Average Latency by Node", [prom_target("A", f'avg by (node) (isilon_stat_node_summary_client_time_avg{C}) / 1000', "Node {{node}}")], "ms"),
    ]:
        panels.append(timeseries_panel(pid, title, targets, y=y, unit=unit, axis_min=0))
        pid += 1; y += 8

    prot_var = {"name": "protocol", "label": "Protocol", "type": "query", "datasource": DS,
                "query": 'label_values(isilon_stat_node_summary_client_operation_rate{cluster=~"$cluster"}, protocol)',
                "definition": 'label_values(isilon_stat_node_summary_client_operation_rate{cluster=~"$cluster"}, protocol)',
                "sort": 3, "multi": True, "includeAll": True, "allValue": ".*", "current": {}, "refresh": 1, "hide": 0}

    d = make_dashboard("PowerScale - Client Summary Stats",
        "Per-client protocol activity, throughput, and latency",
        ["powerscale", "gostats", "summary", "prometheus"], "now-1h", "30s",
        [cluster_var(), node_var(), prot_var], panels)
    write_dashboard(d, "client_summary.json")

# ══════════════════════════════════════════════════════════════════
# 8. Drive Summary Stats
# ══════════════════════════════════════════════════════════════════

def gen_drive_summary():
    pid = 1; y = 0; panels = []
    C = '{cluster=~"$cluster",type=~"$type",drive_id=~"$drive_id",type!="UNKNOWN"}'

    for i, (title, expr, unit, dec) in enumerate([
        ("Total Drive IOPS", f'sum(isilon_stat_node_summary_drive_xfers_in{C}) + sum(isilon_stat_node_summary_drive_xfers_out{C})', "ops", 0),
        ("Avg Access Latency", f'avg(isilon_stat_node_summary_drive_access_latency{{cluster=~"$cluster",type=~"$type",drive_id=~"$drive_id",type!="UNKNOWN"}} > 0)', "ms", 2),
        ("Avg IOSched Latency", f'avg(isilon_stat_node_summary_drive_iosched_latency{{cluster=~"$cluster",type=~"$type",drive_id=~"$drive_id",type!="UNKNOWN"}} > 0)', "ms", 2),
        ("Avg Busy %", f'avg(isilon_stat_node_summary_drive_busy{{cluster=~"$cluster",type=~"$type",drive_id=~"$drive_id",type!="UNKNOWN"}} > 0)', "percent", 1),
    ]):
        panels.append(stat_panel(pid, title, prom_target("A", expr), y=y, x=i*6, w=6, h=4, unit=unit, decimals=dec))
        pid += 1
    y += 4

    for title, expr, legend, unit in [
        ("Access Latency by Drive", f'isilon_stat_node_summary_drive_access_latency{C}', "{{drive_id}}", "ms"),
        ("I/O Scheduler Latency by Drive", f'isilon_stat_node_summary_drive_iosched_latency{C}', "{{drive_id}}", "ms"),
        ("I/O Scheduler Queue Depth by Drive", f'isilon_stat_node_summary_drive_iosched_queue{C}', "{{drive_id}}", "short"),
        ("Drive Busy % by Drive", f'isilon_stat_node_summary_drive_busy{C}', "{{drive_id}}", "percent"),
        ("Drive Read Throughput by Drive", f'isilon_stat_node_summary_drive_bytes_out{C}', "{{drive_id}}", "Bps"),
        ("Drive Write Throughput by Drive", f'isilon_stat_node_summary_drive_bytes_in{C}', "{{drive_id}}", "Bps"),
        ("Drive Read IOPS by Drive", f'isilon_stat_node_summary_drive_xfers_out{C}', "{{drive_id}}", "ops"),
        ("Drive Write IOPS by Drive", f'isilon_stat_node_summary_drive_xfers_in{C}', "{{drive_id}}", "ops"),
        ("Average I/O Size by Drive (Read)", f'isilon_stat_node_summary_drive_xfer_size_out{C}', "{{drive_id}}", "bytes"),
        ("Average I/O Size by Drive (Write)", f'isilon_stat_node_summary_drive_xfer_size_in{C}', "{{drive_id}}", "bytes"),
        ("Slow Accesses by Drive", f'isilon_stat_node_summary_drive_access_slow{C}', "{{drive_id}}", "ops"),
        ("Drive Capacity Used %", f'isilon_stat_node_summary_drive_used_bytes_percent{C}', "{{drive_id}}", "percent"),
    ]:
        panels.append(timeseries_panel(pid, title, [prom_target("A", expr, legend)], y=y, unit=unit, axis_min=0))
        pid += 1; y += 8

    type_var = {"name": "type", "label": "Drive Type", "type": "query", "datasource": DS,
                "query": 'label_values(isilon_stat_node_summary_drive_busy{cluster=~"$cluster",type!="UNKNOWN"}, type)',
                "definition": 'label_values(isilon_stat_node_summary_drive_busy{cluster=~"$cluster",type!="UNKNOWN"}, type)',
                "sort": 1, "multi": True, "includeAll": True, "allValue": ".*", "current": {}, "refresh": 1, "hide": 0}
    driveid_var = {"name": "drive_id", "label": "Drive", "type": "query", "datasource": DS,
                   "query": 'label_values(isilon_stat_node_summary_drive_busy{cluster=~"$cluster",type=~"$type"}, drive_id)',
                   "definition": 'label_values(isilon_stat_node_summary_drive_busy{cluster=~"$cluster",type=~"$type"}, drive_id)',
                   "sort": 3, "multi": True, "includeAll": True, "allValue": ".*", "current": {}, "refresh": 1, "hide": 0}

    d = make_dashboard("PowerScale - Drive Summary Stats",
        "Per-physical-drive performance and capacity statistics",
        ["powerscale", "gostats", "summary", "prometheus"], "now-1h", "30s",
        [cluster_var(), type_var, driveid_var], panels)
    write_dashboard(d, "drive_summary.json")

# ══════════════════════════════════════════════════════════════════
# 9. System Workload (PP Dataset 0)
# ══════════════════════════════════════════════════════════════════

def gen_system_workload():
    pid = 1; y = 0; panels = []
    C = '{cluster=~"$cluster",node=~"$node"}'
    M = "isilon_ppstat_job_type_system_name"

    for i, (title, expr, unit, dec) in enumerate([
        ("Total CPU", f'sum({M}_cpu{C}) / 1000', "ms", 0),
        ("Total Ops", f'sum({M}_ops{C})', "ops", 0),
        ("Total Bytes In", f'sum({M}_bytes_in{C})', "Bps", None),
        ("Total Bytes Out", f'sum({M}_bytes_out{C})', "Bps", None),
    ]):
        panels.append(stat_panel(pid, title, prom_target("A", expr), y=y, x=i*6, w=6, h=4, unit=unit, decimals=dec))
        pid += 1
    y += 4

    for title, targets, unit in [
        ("CPU by System Process", [prom_target("A", f'sum by (system_name) ({M}_cpu{C}) / 1000', "{{system_name}}")], "ms"),
        ("Operations by System Process", [prom_target("A", f'sum by (system_name) ({M}_ops{C})', "{{system_name}}")], "ops"),
        ("Reads and Writes by System Process", [
            prom_target("A", f'sum by (system_name) ({M}_reads{C})', "{{system_name}} reads"),
            prom_target("B", f'sum by (system_name) ({M}_writes{C})', "{{system_name}} writes"),
        ], "short"),
        ("Bytes In (Write) by System Process", [prom_target("A", f'sum by (system_name) ({M}_bytes_in{C})', "{{system_name}}")], "Bps"),
        ("Bytes Out (Read) by System Process", [prom_target("A", f'sum by (system_name) ({M}_bytes_out{C})', "{{system_name}}")], "Bps"),
        ("Read Latency by System Process", [prom_target("A", f'avg by (system_name) ({M}_latency_read{C}) / 1000', "{{system_name}}")], "ms"),
        ("Write Latency by System Process", [prom_target("A", f'avg by (system_name) ({M}_latency_write{C}) / 1000', "{{system_name}}")], "ms"),
        ("Other Latency by System Process", [prom_target("A", f'avg by (system_name) ({M}_latency_other{C}) / 1000', "{{system_name}}")], "ms"),
        ("L2 Cache Hits by System Process", [prom_target("A", f'sum by (system_name) ({M}_l2{C})', "{{system_name}}")], "ops"),
        ("L3 Cache Hits by System Process", [prom_target("A", f'sum by (system_name) ({M}_l3{C})', "{{system_name}}")], "ops"),
        ("Total CPU by Node", [prom_target("A", f'sum by (node) ({M}_cpu{C}) / 1000', "Node {{node}}")], "ms"),
    ]:
        panels.append(timeseries_panel(pid, title, targets, y=y, unit=unit, axis_min=0))
        pid += 1; y += 8

    pp_node_var = {"name": "node", "label": "Node", "type": "query", "datasource": DS,
                   "query": f'label_values({M}_cpu{{cluster=~"$cluster"}}, node)',
                   "definition": f'label_values({M}_cpu{{cluster=~"$cluster"}}, node)',
                   "sort": 3, "multi": True, "includeAll": True, "allValue": ".*", "current": {}, "refresh": 1, "hide": 0}

    d = make_dashboard("PowerScale - System Workload (PP Dataset 0)",
        "OneFS system process resource consumption from PP Dataset 0",
        ["powerscale", "goppstats", "prometheus"], "now-1h", "30s",
        [cluster_var(), pp_node_var], panels)
    write_dashboard(d, "system_workload.json")

# ══════════════════════════════════════════════════════════════════
# Generate all remaining
# ══════════════════════════════════════════════════════════════════

print("Generating remaining Prometheus dashboards...")
gen_protocol_detail()
gen_drive_stats()
gen_protocol_summary()
gen_client_summary()
gen_drive_summary()
gen_system_workload()
print("Done!")
