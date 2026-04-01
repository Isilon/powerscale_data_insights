#!/usr/bin/env python3
"""Generate the Cluster Detail dashboard.

Single-cluster deep-dive with capacity, CPU breakdown, protocol operations,
client connections, open files, network traffic, disk throughput, network
errors, job engine activity, file system events, and cache stats.

Generates both InfluxDB and Prometheus variants.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dashlib import *

README = """\
## PowerScale - Cluster Detail

Detailed performance dashboard for a single Dell PowerScale cluster. \
Select the cluster using the dropdown above.

Shows CPU breakdown, protocol operations, client connections, network \
traffic, file system events, cache hit ratios, and more."""


def _gor(v1, v2):
    return {"mode": "absolute", "steps": [
        {"color": GREEN_ORANGE_RED[0], "value": None},
        {"color": GREEN_ORANGE_RED[1], "value": v1},
        {"color": GREEN_ORANGE_RED[2], "value": v2},
    ]}

ALERT_MAPPINGS = [
    {"type": "range", "options": {"from": 0.0, "to": 0.0,
        "result": {"text": "Healthy", "index": 0}}},
    {"type": "range", "options": {"from": 0.0001, "to": 1.999,
        "result": {"text": "Attention", "index": 1}}},
    {"type": "range", "options": {"from": 2.0, "to": 5.0,
        "result": {"text": "Down", "index": 2}}},
    {"type": "value", "options": {
        "0": {"text": "Healthy", "index": 0},
        "1": {"text": "Attention", "index": 1},
        "2": {"text": "Down", "index": 2}}},
]


def generate(backend):
    ds = DS_INFLUXDB if backend == "influxdb" else DS_PROMETHEUS
    influx = (backend == "influxdb")
    tags = ["powerscale", "gostats"] + (["prometheus"] if not influx else [])

    def T(refId, iq, pq, alias=None, legend=None, hide=False):
        if influx:
            t = influx_target(ds, refId, iq, alias=alias)
        else:
            t = prom_target(ds, refId, pq, legend=legend)
        if hide:
            t["hide"] = True
        return t

    W = '"cluster" =~ /^$cluster$/'
    C = '{cluster=~"$cluster"}'

    def iq(sel, meas, where=None, group="time($__interval)"):
        w = where or W
        return (f'SELECT {sel} FROM "{meas}" WHERE {w} AND $timeFilter '
                f'GROUP BY {group} fill(null)')

    panels = []; pid = 1; y = 0

    # README
    panels.append(text_panel(pid, README, y, h=4)); pid += 1; y += 4

    # $cluster link
    panels.append(text_panel(pid,
        "### $cluster\n\n[WebUI](https://$cluster:8080/)",
        y, h=4, w=4, x=0, title="$cluster", transparent=True))
    pid += 1

    # Stat/gauge row
    panels.append(stat_panel(ds, pid, "Total Nodes",
        T("A", iq('mean("value")', "cluster.node.count.all"),
               f'isilon_stat_cluster_node_count_all{C}'),
        y=y, x=4, w=4, h=4, unit="none", thresholds=_gor(1, 2),
        graph_mode="none", calc="mean"))
    pid += 1

    panels.append(stat_panel(ds, pid, "Nodes Down",
        T("A", iq('mean("value")', "cluster.node.count.down"),
               f'isilon_stat_cluster_node_count_down{C}'),
        y=y, x=8, w=4, h=4, unit="none", thresholds=_gor(1, 2),
        color_mode="background", calc="mean"))
    pid += 1

    panels.append(stat_panel(ds, pid, "Alert Status",
        T("A", iq('max("value")', "cluster.health"),
               f'isilon_stat_cluster_health{C}'),
        y=y, x=12, w=4, h=4, unit="none", thresholds=_gor(0.0001, 2),
        color_mode="background", graph_mode="none", calc="mean",
        mappings=ALERT_MAPPINGS))
    pid += 1

    panels.append(gauge_panel(ds, pid, "Cluster CPU",
        T("A", iq('1.0 - mean("value")  / 1000', "cluster.cpu.idle.avg"),
               f'1 - isilon_stat_cluster_cpu_idle_avg{C} / 1000'),
        y=y, x=16, w=4, h=4, unit="percentunit",
        thresholds=_gor(0.8, 0.95), min_val=0, max_val=1))
    pid += 1

    panels.append(gauge_panel(ds, pid, "Cluster Capacity Utilization",
        T("A", iq('100.0 - mean("value")', "ifs.percent.avail"),
               f'100 - isilon_stat_ifs_percent_avail{C}'),
        y=y, x=20, w=4, h=4, unit="percent",
        thresholds=_gor(80, 90), min_val=0, max_val=100))
    pid += 1
    y += 4

    # Protocol stat panels (6 x 4-wide)
    proto_th = _gor(10, 25)
    proto_stats = [
        ("NFSv3 Throughput",
         iq('mean("in_rate") + mean("out_rate")', "cluster.protostats.nfs.total"),
         f'isilon_stat_cluster_protostats_nfs_total_in_rate{C} + isilon_stat_cluster_protostats_nfs_total_out_rate{C}',
         "Bps", "value", "area"),
        ("NFSv3 Op/s",
         iq('mean("op_rate")', "cluster.protostats.nfs.total"),
         f'isilon_stat_cluster_protostats_nfs_total_op_rate{C}',
         "ops", "value", "area"),
        ("NFSv3 Latency",
         iq('mean("time_avg") /1000', "cluster.protostats.nfs.total"),
         f'isilon_stat_cluster_protostats_nfs_total_time_avg{C} / 1000',
         "ms", "background", "area"),
        ("SMB2 Throughput",
         iq('mean("in_rate") + mean("out_rate")', "cluster.protostats.smb2.total"),
         f'isilon_stat_cluster_protostats_smb2_total_in_rate{C} + isilon_stat_cluster_protostats_smb2_total_out_rate{C}',
         "Bps", "value", "area"),
        ("SMB2 Op/s",
         iq('mean("op_rate")', "cluster.protostats.smb2.total"),
         f'isilon_stat_cluster_protostats_smb2_total_op_rate{C}',
         "ops", "value", "area"),
        ("SMB2 Latency",
         iq('mean("time_avg") /1000', "cluster.protostats.smb2.total"),
         f'isilon_stat_cluster_protostats_smb2_total_time_avg{C} / 1000',
         "ms", "background", "area"),
    ]
    for i, (title, _iq, _pq, unit, cm, gm) in enumerate(proto_stats):
        panels.append(stat_panel(ds, pid, title, T("A", _iq, _pq),
            y=y, x=i*4, w=4, h=4, unit=unit, thresholds=proto_th,
            color_mode=cm, graph_mode=gm))
        pid += 1
    y += 4

    # Capacity Utilization
    panels.append(timeseries_panel(ds, pid, "Cluster Capacity Utilization", [
        T("A", iq('100.0 - mean("value")', "ifs.percent.avail"),
               f'100 - isilon_stat_ifs_percent_avail{C}',
               alias="Cluster Capacity Utilization", legend="Cluster Capacity Utilization"),
    ], y=y, unit="percent", axis_min=0, tooltip_sort="none"))
    pid += 1; y += 8

    # CPU Breakdown (stacked bars)
    panels.append(timeseries_panel(ds, pid, "Cluster CPU for $cluster", [
        T("D", iq('mean("value") / 1000', "cluster.cpu.intr.avg"),
               f'isilon_stat_cluster_cpu_intr_avg{C} / 1000',
               alias="Interrupt", legend="Interrupt"),
        T("A", iq('mean("value") / 1000', "cluster.cpu.sys.avg"),
               f'isilon_stat_cluster_cpu_sys_avg{C} / 1000',
               alias="System", legend="System"),
        T("B", iq('mean("value") / 1000', "cluster.cpu.user.avg"),
               f'isilon_stat_cluster_cpu_user_avg{C} / 1000',
               alias="User", legend="User"),
        T("C", iq('mean("value") / 1000', "cluster.cpu.idle.avg"),
               f'isilon_stat_cluster_cpu_idle_avg{C} / 1000',
               alias="Idle", legend="Idle"),
    ], y=y, unit="percentunit", axis_min=0, axis_max=1,
       draw_style="bars", fill_opacity=40,
       stacking={"mode": "normal", "group": "A"}, tooltip_sort="none",
       overrides=[
           {"matcher": {"id": "byName", "options": "Idle"}, "properties": [
               {"id": "color", "value": {"mode": "fixed", "fixedColor": "#508642"}}]},
           {"matcher": {"id": "byName", "options": "System"}, "properties": [
               {"id": "color", "value": {"mode": "fixed", "fixedColor": "#BF1B00"}}]},
           {"matcher": {"id": "byName", "options": "User"}, "properties": [
               {"id": "color", "value": {"mode": "fixed", "fixedColor": "#EAB839"}}]},
       ]))
    pid += 1; y += 8

    # Protocol Ops + CPU overlay
    if influx:
        proto_ops_targets = [
            T("A", f'SELECT 1.0 - mean("value") / 1000.0 FROM "cluster.cpu.idle.avg" WHERE "cluster" =~ /$cluster$/ AND $timeFilter GROUP BY time($__interval) fill(null)',
              "", alias="CPU", hide=True),
            T("E", f'SELECT mean("op_rate") FROM /cluster\\.protostats\\.(.*)\\.total/ WHERE "cluster" =~ /$cluster$/ AND $timeFilter GROUP BY time($__interval) fill(null)',
              "", alias="$2 ops"),
        ]
    else:
        proto_ops_targets = [
            T("A", "", f'1 - isilon_stat_cluster_cpu_idle_avg{C} / 1000', legend="CPU"),
            T("B", "", 'label_replace({__name__=~"isilon_stat_cluster_protostats_.*_total_op_rate",cluster=~"$cluster"}, "protocol", "$1", "__name__", "isilon_stat_cluster_protostats_(.*)_total_op_rate")',
              legend="{{protocol}} ops"),
        ]
    panels.append(timeseries_panel(ds, pid,
        "Cluster Protocol Operations and CPU for $cluster",
        proto_ops_targets, y=y, unit="ops", axis_min=0, tooltip_sort="none",
        overrides=[
            {"matcher": {"id": "byName", "options": "CPU"}, "properties": [
                {"id": "custom.drawStyle", "value": "line"},
                {"id": "custom.fillOpacity", "value": 0},
                {"id": "custom.axisPlacement", "value": "right"},
                {"id": "unit", "value": "percentunit"},
                {"id": "min", "value": 0}, {"id": "max", "value": 1},
                {"id": "color", "value": {"mode": "fixed", "fixedColor": "#7EB26D"}}]},
        ]))
    pid += 1; y += 8

    # Client Connections (stepAfter)
    if influx:
        conn_targets = [T("A", f'SELECT sum("value") FROM /node.clientstats.active.(.*)/ WHERE {W} AND $timeFilter GROUP BY time(30s) fill(null)', "", alias="$3 connections")]
    else:
        conn_targets = [T("A", "", f'label_replace(sum by (__name__) ({{__name__=~"isilon_stat_node_clientstats_active_.*",cluster=~"$cluster"}}), "protocol", "$1", "__name__", "isilon_stat_node_clientstats_active_(.*)")', legend="{{protocol}} connections")]
    panels.append(timeseries_panel(ds, pid,
        "Active Client Connections by Protocol for $cluster",
        conn_targets, y=y, unit="short",
        line_interpolation="stepAfter", tooltip_sort="desc"))
    pid += 1; y += 8

    # Open Files (bars)
    panels.append(timeseries_panel(ds, pid, "Open Files for $cluster", [
        T("A", f'SELECT mean("value") FROM "node.open.files" WHERE {W} AND $timeFilter GROUP BY time(30s) fill(null)',
               f'sum(isilon_stat_node_open_files{C})',
               alias="Open files", legend="Open files"),
    ], y=y, unit="short", axis_min=0, draw_style="bars"))
    pid += 1; y += 8

    # Network Traffic (negative-Y for inbound)
    if influx:
        net_targets = [
            T("A", iq('(mean("value")) * -1', "cluster.net.ext.packets.in.rate"), "", alias="Packets In:", hide=True),
            T("C", iq('(mean("value")) * -1', "cluster.net.ext.bytes.in.rate"), "", alias="Bytes In:"),
            T("B", iq('mean("value")', "cluster.net.ext.packets.out.rate"), "", alias="Packets Out:", hide=True),
            T("D", iq('mean("value")', "cluster.net.ext.bytes.out.rate"), "", alias="Bytes Out:"),
        ]
        net_overrides = [{"matcher": {"id": "byRegexp", "options": "Packets"}, "properties": [
            {"id": "custom.axisPlacement", "value": "right"}, {"id": "unit", "value": "short"}]}]
    else:
        net_targets = [
            T("A", "", f'-isilon_stat_cluster_net_ext_bytes_in_rate{C}', legend="Bytes In"),
            T("B", "", f'isilon_stat_cluster_net_ext_bytes_out_rate{C}', legend="Bytes Out"),
        ]
        net_overrides = []
    panels.append(timeseries_panel(ds, pid,
        "Cluster Network Traffic for $cluster",
        net_targets, y=y, unit="Bps", draw_style="bars", line_width=1,
        axis_label="Read (+) / Write (-)",
        tooltip_sort="none", overrides=net_overrides))
    pid += 1; y += 8

    # Net/FS/Disk Throughput (negative-Y for writes)
    panels.append(timeseries_panel(ds, pid,
        "Cluster Network, File System and Disk Throughput for $cluster", [
        T("D", iq('mean("value")', "cluster.net.ext.bytes.out.rate"), f'isilon_stat_cluster_net_ext_bytes_out_rate{C}', alias="Network Read", legend="Network Read"),
        T("B", iq('mean("value")', "ifs.bytes.out.rate"), f'isilon_stat_ifs_bytes_out_rate{C}', alias="IFS Read", legend="IFS Read"),
        T("E", iq('mean("value")', "cluster.disk.bytes.out.rate"), f'isilon_stat_cluster_disk_bytes_out_rate{C}', alias="Disk Read", legend="Disk Read"),
        T("C", iq('(mean("value")) * -1', "cluster.net.ext.bytes.in.rate"), f'-isilon_stat_cluster_net_ext_bytes_in_rate{C}', alias="Network Write", legend="Network Write"),
        T("A", iq('(mean("value")) * -1', "ifs.bytes.in.rate"), f'-isilon_stat_ifs_bytes_in_rate{C}', alias="IFS Write", legend="IFS Write"),
        T("F", iq('(mean("value")) * -1', "cluster.disk.bytes.in.rate"), f'-isilon_stat_cluster_disk_bytes_in_rate{C}', alias="Disk Write", legend="Disk Write"),
    ], y=y, unit="Bps", draw_style="bars", line_width=1,
       axis_label="Read (+) / Write (-)", tooltip_sort="none"))
    pid += 1; y += 8

    # Network Errors
    panels.append(timeseries_panel(ds, pid,
        "Cluster Network Errors for $cluster", [
        T("A", iq('mean("value")', "cluster.net.ext.errors.in.rate"), f'isilon_stat_cluster_net_ext_errors_in_rate{C}', alias="Inbound Errors", legend="Inbound Errors"),
        T("B", iq('mean("value")', "cluster.net.ext.errors.out.rate"), f'isilon_stat_cluster_net_ext_errors_out_rate{C}', alias="Outbound Errors", legend="Outbound Errors"),
    ], y=y, unit="short", axis_min=0, draw_style="bars",
       legend_calcs=["min", "max"], tooltip_sort="none",
       overrides=[
           {"matcher": {"id": "byName", "options": "Inbound Errors"}, "properties": [
               {"id": "color", "value": {"mode": "fixed", "fixedColor": "#890F02"}}]},
           {"matcher": {"id": "byName", "options": "Outbound Errors"}, "properties": [
               {"id": "color", "value": {"mode": "fixed", "fixedColor": "#962D82"}}]},
       ]))
    pid += 1; y += 8

    # Job Engine (bars, spanNulls=false)
    panels.append(timeseries_panel(ds, pid,
        "Job Engine Activity for $cluster", [
        T("D", iq('mean("op_rate")', "cluster.protostats.jobd.total"),
               f'isilon_stat_cluster_protostats_jobd_total_op_rate{C}',
               alias="Job Engine", legend="Job Engine"),
    ], y=y, unit="ops", axis_min=0, draw_style="bars", span_nulls=False))
    pid += 1; y += 8

    # FS Events
    if influx:
        fs_targets = [T("A", f'SELECT sum("value") FROM /node.ifs.heat.(.*).total/ WHERE {W} AND $timeFilter GROUP BY time($__interval) fill(null)', "", alias="$3")]
    else:
        fs_targets = [T("A", "", f'label_replace(sum by (__name__) ({{__name__=~"isilon_stat_node_ifs_heat_.*_total",cluster=~"$cluster"}}), "event", "$1", "__name__", "isilon_stat_node_ifs_heat_(.*)_total")', legend="{{event}}")]
    panels.append(timeseries_panel(ds, pid, "OneFS File System Events",
        fs_targets, y=y, unit="short", tooltip_sort="none"))
    pid += 1; y += 8

    # Cache Stats (9 ratio targets + oldest page age on right axis)
    CM = "node.ifs.cache"
    PM = "isilon_stat_node_ifs_cache"
    if influx:
        cache_targets = [
            T("A", iq('max("l1_data_prefetch_hit") / max("l1_data_prefetch_start")', CM), "", alias="L1 Data Prefetch Hit Ratio"),
            T("F", iq('mean("l1_meta_prefetch_hit") / mean("l1_meta_prefetch_start")', CM), "", alias="L1 Meta-Data Prefetch Hit Ratio"),
            T("B", iq('mean("l1_data_read_hit") / mean("l1_data_read_start")', CM), "", alias="L1 Data Read Hit Ratio"),
            T("G", iq('mean("l1_meta_read_hit") / mean("l1_meta_read_start")', CM), "", alias="L1 Meta-Data Read Hit Ratio"),
            T("C", iq('mean("l2_data_read_hit") / mean("l2_data_read_start")', CM), "", alias="L2 Data Read Hit Ratio"),
            T("D", iq('mean("l2_meta_read_hit") / mean("l2_meta_read_start")', CM), "", alias="L2 Meta-Data Read Hit Ratio"),
            T("H", iq('mean("l3_data_read_hit") / mean("l3_data_read_start")', CM), "", alias="L3 Data Read Hit Ratio"),
            T("I", iq('mean("l3_meta_read_hit") / mean("l3_meta_read_start")', CM), "", alias="L3 Meta-Data Read Hit Ratio"),
            T("E", iq('mean("oldest_page_age")', CM), "", alias="Oldest Page Age"),
        ]
    else:
        cache_targets = [
            T("A", "", f'sum({PM}_l1_data_prefetch_hit{C}) / sum({PM}_l1_data_prefetch_start{C})', legend="L1 Data Prefetch Hit Ratio"),
            T("B", "", f'sum({PM}_l1_meta_prefetch_hit{C}) / sum({PM}_l1_meta_prefetch_start{C})', legend="L1 Meta-Data Prefetch Hit Ratio"),
            T("C", "", f'sum({PM}_l1_data_read_hit{C}) / sum({PM}_l1_data_read_start{C})', legend="L1 Data Read Hit Ratio"),
            T("D", "", f'sum({PM}_l1_meta_read_hit{C}) / sum({PM}_l1_meta_read_start{C})', legend="L1 Meta-Data Read Hit Ratio"),
            T("E", "", f'sum({PM}_l2_data_read_hit{C}) / sum({PM}_l2_data_read_start{C})', legend="L2 Data Read Hit Ratio"),
            T("F", "", f'sum({PM}_l2_meta_read_hit{C}) / sum({PM}_l2_meta_read_start{C})', legend="L2 Meta-Data Read Hit Ratio"),
            T("G", "", f'sum({PM}_l3_data_read_hit{C}) / sum({PM}_l3_data_read_start{C})', legend="L3 Data Read Hit Ratio"),
            T("H", "", f'sum({PM}_l3_meta_read_hit{C}) / sum({PM}_l3_meta_read_start{C})', legend="L3 Meta-Data Read Hit Ratio"),
            T("I", "", f'avg({PM}_oldest_page_age{C})', legend="Oldest Page Age"),
        ]
    panels.append(timeseries_panel(ds, pid, "Cache Stats for $cluster",
        cache_targets, y=y, unit="percentunit", axis_min=0, tooltip_sort="none",
        overrides=[
            {"matcher": {"id": "byName", "options": "Oldest Page Age"}, "properties": [
                {"id": "custom.axisPlacement", "value": "right"},
                {"id": "unit", "value": "ms"}]},
        ]))
    pid += 1; y += 8

    # Template variables
    if influx:
        variables = [var_query(ds, "cluster", "Cluster",
                               'SHOW TAG VALUES WITH KEY = "cluster"', sort=1)]
    else:
        variables = [var_query(ds, "cluster", "Cluster",
                               'label_values(isilon_stat_cluster_health, cluster)')]

    dash = make_dashboard(
        title="PowerScale - Cluster Detail",
        description="Detailed performance metrics for a single Dell PowerScale cluster",
        tags=tags, variables=variables, panels=panels,
    )
    write_dashboard(dash, outpath(backend, "cluster_detail.json"))


if __name__ == "__main__":
    for b in ("influxdb", "prometheus"):
        print(f"\n=== {b} ===")
        generate(b)
