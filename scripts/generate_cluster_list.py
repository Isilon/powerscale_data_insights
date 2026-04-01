#!/usr/bin/env python3
"""Generate the PowerScale - Cluster List dashboard.

Multi-cluster overview with a repeating row per cluster showing node
count, health status, CPU utilisation, storage capacity, and NFS/SMB
protocol statistics.

Generates both InfluxDB and Prometheus variants.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dashlib import *

README = """\
## PowerScale - Cluster List

Multi-cluster overview for Dell PowerScale clusters. Each cluster \
shows node count, health status, CPU utilisation, storage capacity, \
and NFS/SMB protocol statistics.

* Use the **Cluster** dropdown to select one or more clusters.
* Click a cluster name to navigate to the \
[Cluster Detail](/d/powerscale-cluster-detail/powerscale-cluster-detail) \
dashboard.
* Click **WebUI** to open the cluster management interface."""

CLUSTER_LINK = (
    "### [$cluster](/d/powerscale-cluster-detail/"
    "powerscale-cluster-detail?var-cluster=$cluster)\n\n"
    "[WebUI](https://$cluster:8080/)"
)

# Shared thresholds
TH_GOR = {"mode": "absolute", "steps": [
    {"color": GREEN_ORANGE_RED[0], "value": None},
    {"color": GREEN_ORANGE_RED[1], "value": 1},
    {"color": GREEN_ORANGE_RED[2], "value": 2},
]}
TH_ALERT = {"mode": "absolute", "steps": [
    {"color": GREEN_ORANGE_RED[0], "value": None},
    {"color": GREEN_ORANGE_RED[1], "value": 0.0001},
    {"color": GREEN_ORANGE_RED[2], "value": 2},
]}
TH_CPU = {"mode": "absolute", "steps": [
    {"color": GREEN_ORANGE_RED[0], "value": None},
    {"color": GREEN_ORANGE_RED[1], "value": 0.8},
    {"color": GREEN_ORANGE_RED[2], "value": 0.95},
]}
TH_CAP = {"mode": "absolute", "steps": [
    {"color": GREEN_ORANGE_RED[0], "value": None},
    {"color": GREEN_ORANGE_RED[1], "value": 80},
    {"color": GREEN_ORANGE_RED[2], "value": 90},
]}
TH_LATENCY = {"mode": "absolute", "steps": [
    {"color": GREEN_ORANGE_RED[0], "value": None},
    {"color": GREEN_ORANGE_RED[1], "value": 10},
    {"color": GREEN_ORANGE_RED[2], "value": 25},
]}
TH_RED = {"mode": "absolute", "steps": [
    {"color": GREEN_ORANGE_RED[2], "value": None},
]}

ALERT_MAPPINGS = [
    {"type": "range", "options": {
        "from": 0.0, "to": 0.0,
        "result": {"text": "Healthy", "index": 0},
    }},
    {"type": "range", "options": {
        "from": 0.0001, "to": 1.999,
        "result": {"text": "Attention", "index": 1},
    }},
    {"type": "range", "options": {
        "from": 2.0, "to": 5.0,
        "result": {"text": "Down", "index": 2},
    }},
    {"type": "value", "options": {
        "0": {"text": "Healthy", "index": 0},
        "1": {"text": "Attention", "index": 1},
        "2": {"text": "Down", "index": 2},
    }},
]

# InfluxDB query helpers
_W = '"cluster" =~ /^$cluster$/ AND $timeFilter GROUP BY time($__interval) fill(null)'

def _iq(meas, agg, field):
    return f'SELECT {agg}("{field}") FROM "{meas}" WHERE {_W}'

def _iq_expr(expr, meas):
    return f'SELECT {expr} FROM "{meas}" WHERE {_W}'


def generate(backend):
    ds = DS_INFLUXDB if backend == "influxdb" else DS_PROMETHEUS
    influx = (backend == "influxdb")
    tags = ["powerscale", "gostats"] + (["prometheus"] if not influx else [])

    C = '{cluster=~"$cluster"}'

    def T(refId, iq, pq, alias=None, legend=None):
        if influx:
            return influx_target(ds, refId, iq, alias=alias)
        return prom_target(ds, refId, pq, legend=legend)

    panels = []; pid = 1; y = 0

    # README panel
    panels.append(text_panel(pid, README, y, h=5)); pid += 1; y += 5

    # Repeating row per cluster
    panels.append(row_panel(200, "Cluster: $cluster", y, repeat="cluster"))
    y += 1

    # Row 1: cluster link + core status
    panels.append(text_panel(pid, CLUSTER_LINK, y, h=4, w=4, x=0,
                             title="$cluster", transparent=True))
    pid += 1

    panels.append(stat_panel(ds, pid, "Total Nodes",
        T("A", _iq("cluster.node.count.all", "mean", "value"),
               f'isilon_stat_cluster_node_count_all{C}'),
        y=y, x=4, w=4, h=4, unit="none",
        thresholds=TH_GOR, graph_mode="none"))
    pid += 1

    panels.append(stat_panel(ds, pid, "Nodes Down",
        T("A", _iq("cluster.node.count.down", "max", "value"),
               f'isilon_stat_cluster_node_count_down{C}'),
        y=y, x=8, w=4, h=4, unit="none",
        color_mode="background", graph_mode="none", thresholds=TH_GOR))
    pid += 1

    panels.append(stat_panel(ds, pid, "Alert Status",
        T("A", _iq("cluster.health", "max", "value"),
               f'isilon_stat_cluster_health{C}'),
        y=y, x=12, w=4, h=4, unit="none",
        color_mode="background", graph_mode="none", calc="mean",
        thresholds=TH_ALERT, mappings=ALERT_MAPPINGS))
    pid += 1

    panels.append(gauge_panel(ds, pid, "Cluster CPU",
        T("A", _iq_expr('1.0 - mean("value") / 1000', "cluster.cpu.idle.avg"),
               f'1 - isilon_stat_cluster_cpu_idle_avg{C} / 1000'),
        y=y, x=16, w=4, h=4, unit="percentunit",
        min_val=0, max_val=1, thresholds=TH_CPU))
    pid += 1

    panels.append(gauge_panel(ds, pid, "Cluster Capacity",
        T("A", _iq_expr('100.0 - mean("value")', "ifs.percent.avail"),
               f'100 - isilon_stat_ifs_percent_avail{C}'),
        y=y, x=20, w=4, h=4, unit="percent",
        min_val=0, max_val=100, thresholds=TH_CAP))
    pid += 1
    y += 4

    # Row 2: protocol stat panels
    _pnfs = "isilon_stat_cluster_protostats_nfs_total"
    _psmb = "isilon_stat_cluster_protostats_smb2_total"

    proto_panels = [
        ("NFSv3 Throughput",
         _iq_expr('mean("in_rate") + mean("out_rate")', "cluster.protostats.nfs.total"),
         f'{_pnfs}_in_rate{C} + {_pnfs}_out_rate{C}',
         "Bps", None, "value", TH_RED),
        ("NFSv3 Op/s",
         _iq("cluster.protostats.nfs.total", "mean", "op_rate"),
         f'{_pnfs}_op_rate{C}',
         "ops", None, "value", TH_RED),
        ("NFSv3 Latency",
         _iq_expr('mean("time_avg") / 1000', "cluster.protostats.nfs.total"),
         f'{_pnfs}_time_avg{C} / 1000',
         "ms", None, "background", TH_LATENCY),
        ("SMB2 Throughput",
         _iq_expr('mean("in_rate") + mean("out_rate")', "cluster.protostats.smb2.total"),
         f'{_psmb}_in_rate{C} + {_psmb}_out_rate{C}',
         "Bps", None, "value", TH_RED),
        ("SMB2 Op/s",
         _iq("cluster.protostats.smb2.total", "mean", "op_rate"),
         f'{_psmb}_op_rate{C}',
         "ops", None, "value", TH_RED),
        ("SMB2 Latency",
         _iq_expr('mean("time_avg") / 1000', "cluster.protostats.smb2.total"),
         f'{_psmb}_time_avg{C} / 1000',
         "ms", None, "background", TH_LATENCY),
    ]

    for i, (title, iq, pq, unit, dec, cm, th) in enumerate(proto_panels):
        panels.append(stat_panel(ds, pid, title, T("A", iq, pq),
                                 y=y, x=i*4, w=4, h=4, unit=unit,
                                 decimals=dec, color_mode=cm, thresholds=th))
        pid += 1
    y += 4

    # Template variables
    if influx:
        variables = [
            var_query(ds, "cluster", "Cluster",
                      'SHOW TAG VALUES WITH KEY = "cluster"',
                      multi=True, include_all=True, sort=1),
        ]
    else:
        variables = [
            var_query(ds, "cluster", "Cluster",
                      'label_values(isilon_stat_cluster_health, cluster)',
                      multi=True, include_all=True),
        ]

    dash = make_dashboard(
        title="PowerScale - Cluster List",
        description="Multi-cluster overview for Dell PowerScale clusters",
        tags=tags,
        variables=variables,
        panels=panels,
        time_from="now-15m",
        tooltip=0,
    )
    write_dashboard(dash, outpath(backend, "cluster_list.json"))


if __name__ == "__main__":
    for b in ("influxdb", "prometheus"):
        print(f"\n=== {b} ===")
        generate(b)
