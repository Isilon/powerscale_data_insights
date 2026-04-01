#!/usr/bin/env python3
"""Generate the Cluster Capacity dashboard.

Simple dashboard with a README text panel and a color-coded capacity
utilization table.  Generates both InfluxDB and Prometheus variants.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dashlib import *

README = """\
## PowerScale - Cluster Capacity

Storage capacity utilization across clusters. Color-coded thresholds: \
green (<85%), orange (85-90%), red (>90%)."""


def generate(backend):
    ds = DS_INFLUXDB if backend == "influxdb" else DS_PROMETHEUS
    influx = (backend == "influxdb")
    tags = ["powerscale", "gostats"] + (["prometheus"] if not influx else [])

    panels = []; pid = 1; y = 0

    # ── README panel ──
    panels.append(text_panel(pid, README, y, h=4)); pid += 1; y += 4

    # ── Capacity utilization table ──
    capacity_thresholds = {
        "mode": "absolute",
        "steps": [
            {"color": GREEN_ORANGE_RED[0], "value": None},
            {"color": GREEN_ORANGE_RED[1], "value": 85},
            {"color": GREEN_ORANGE_RED[2], "value": 90},
        ],
    }

    if influx:
        targets = [
            influx_target(ds, "A",
                'SELECT 100.0 - last("value") as utilization '
                'FROM "ifs.percent.avail" '
                'WHERE "cluster" =~ /^$cluster$/ AND $timeFilter '
                'GROUP BY time($__interval), "cluster" fill(none)',
                fmt="table"),
        ]
        overrides = [
            {
                "matcher": {"id": "byName", "options": "Time"},
                "properties": [
                    {"id": "custom.width", "value": 200},
                    {"id": "unit", "value": "dateTimeAsIso"},
                ],
            },
            {
                "matcher": {"id": "byName", "options": "cluster"},
                "properties": [
                    {"id": "displayName", "value": "Cluster"},
                    {"id": "custom.width", "value": 250},
                ],
            },
            {
                "matcher": {"id": "byName", "options": "utilization"},
                "properties": [
                    {"id": "displayName", "value": "Capacity Utilization %"},
                    {"id": "unit", "value": "percent"},
                    {"id": "decimals", "value": 2},
                    {"id": "thresholds", "value": capacity_thresholds},
                    {
                        "id": "custom.cellOptions",
                        "value": {"type": "color-background", "mode": "row"},
                    },
                ],
            },
        ]
        transformations = None
        interval = "200d"
    else:
        targets = [{
            "refId": "A",
            "datasource": dict(ds),
            "expr": '100 - isilon_stat_ifs_percent_avail{cluster=~"$cluster"}',
            "legendFormat": "{{cluster}}",
            "instant": True,
            "format": "table",
            "editorMode": "code",
        }]
        overrides = [
            {
                "matcher": {"id": "byName", "options": "Cluster"},
                "properties": [
                    {"id": "custom.width", "value": 250},
                ],
            },
            {
                "matcher": {"id": "byName", "options": "Capacity Utilization %"},
                "properties": [
                    {"id": "unit", "value": "percent"},
                    {"id": "decimals", "value": 2},
                    {"id": "thresholds", "value": capacity_thresholds},
                ],
            },
        ]
        transformations = [
            {"id": "labelsToFields", "options": {"mode": "columns"}},
            {"id": "organize", "options": {
                "excludeByName": {"Time": True, "instance": True, "job": True},
                "renameByName": {
                    "cluster": "Cluster",
                    "Value": "Capacity Utilization %",
                },
            }},
        ]
        interval = None

    table = table_panel(
        ds, pid, "Cluster Capacity Utilization", targets,
        y=y, h=20, w=24,
        overrides=overrides,
        sort_by=[{"displayName": "Capacity Utilization %", "desc": True}],
        transformations=transformations,
        interval=interval,
    )

    # Prometheus: default cell options live in fieldConfig.defaults
    if not influx:
        table["fieldConfig"]["defaults"]["custom"] = {
            "cellOptions": {"type": "color-background", "mode": "row"},
        }

    panels.append(table); pid += 1; y += 20

    # ── Template variables ──
    if influx:
        variables = [
            var_query(ds, "cluster", "Cluster",
                      'SHOW TAG VALUES WITH KEY = "cluster"',
                      multi=True, include_all=True, sort=1),
        ]
    else:
        variables = [
            var_query(ds, "cluster", "Cluster",
                      "label_values(isilon_stat_cluster_health, cluster)",
                      multi=True, include_all=True),
        ]

    dash = make_dashboard(
        title="PowerScale - Cluster Capacity",
        description="Color coded table showing cluster capacity utilization. "
                    "Good to see the clusters with the highest capacity "
                    "utilization.",
        tags=tags,
        variables=variables,
        panels=panels,
        time_from="now-7d",
        refresh="",
    )
    write_dashboard(dash, outpath(backend, "cluster_capacity.json"))


if __name__ == "__main__":
    for b in ("influxdb", "prometheus"):
        print(f"\n=== {b} ===")
        generate(b)
