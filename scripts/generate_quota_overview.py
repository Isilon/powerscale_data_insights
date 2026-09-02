#!/usr/bin/env python3
"""Generate quota overview dashboards for InfluxDB and Prometheus."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dashlib import *

README = """\
## PowerScale - Quota Overview

Current directory quota usage and threshold state from **goquotas**. Directory
and default-directory quotas are collected by default; totals reflect the quota
types enabled in the collector. Use the path selector to open the detail view.

Quota IDs remain available in the data for stable identity, while paths are
used as the human-facing selector. InfluxDB current-state panels use a
three-hour freshness window, sized for the default one-hour collection cadence.
"""


def generate(backend):
    ds = DS_INFLUXDB if backend == "influxdb" else DS_PROMETHEUS
    influx = backend == "influxdb"
    tags = ["powerscale", "goquotas"] + ([] if influx else ["prometheus"])
    panels = [text_panel(1, README, 0, h=5)]

    if influx:
        total = influx_target(ds, "A", 'SELECT count("present") FROM '
            '(SELECT last("present") AS "present" FROM "quota" '
            'WHERE "cluster" =~ /^$cluster$/ AND time > now() - 3h GROUP BY "quota_id") '
            'WHERE "present" = true')
        hard = influx_target(ds, "A", 'SELECT count("hard_exceeded") FROM '
            '(SELECT last("hard_exceeded") AS "hard_exceeded" FROM "quota" '
            'WHERE "cluster" =~ /^$cluster$/ AND time > now() - 3h GROUP BY "quota_id") '
            'WHERE "hard_exceeded" = true')
        not_ready = influx_target(ds, "A", 'SELECT count("ready") FROM '
            '(SELECT last("ready") AS "ready" FROM "quota" '
            'WHERE "cluster" =~ /^$cluster$/ AND time > now() - 3h GROUP BY "quota_id") '
            'WHERE "ready" = false')
        top_targets = [influx_target(ds, "A",
            'SELECT last("hard_utilization_ratio") * 100 AS "Hard utilization" '
            'FROM "quota" WHERE "cluster" =~ /^$cluster$/ AND time > now() - 3h '
            'GROUP BY "quota_id", "path", "quota_type", "include_snapshots"',
            fmt="table")]
        variables = [
            var_query(ds, "cluster", "Cluster", 'SHOW TAG VALUES FROM "quota" WITH KEY = "cluster"', multi=True, include_all=True, sort=1),
        ]
    else:
        total = prom_target(ds, "A", 'count(isilon_quota_present{cluster=~"$cluster"} == 1)')
        hard = prom_target(ds, "A", 'sum(isilon_quota_hard_exceeded{cluster=~"$cluster"} == 1) or vector(0)')
        not_ready = prom_target(ds, "A", 'sum(isilon_quota_ready{cluster=~"$cluster"} == 0) or vector(0)')
        top_targets = [{**prom_target(ds, "A", 'isilon_quota_hard_utilization_ratio{cluster=~"$cluster"} * 100', "{{path}} ({{quota_type}})"), "instant": True, "format": "table"}]
        variables = [
            var_query(ds, "cluster", "Cluster", "label_values(isilon_quota_present, cluster)", multi=True, include_all=True),
        ]

    panels.extend([
        stat_panel(ds, 2, "Collected Quotas", total, 5, x=0, w=8, h=4, no_value="0"),
        stat_panel(ds, 3, "Hard Threshold Exceeded", hard, 5, x=8, w=8, h=4,
                   thresholds={"mode": "absolute", "steps": [{"color": "green", "value": None}, {"color": "red", "value": 1}]}, no_value="0"),
        stat_panel(ds, 4, "Accounting Not Ready", not_ready, 5, x=16, w=8, h=4,
                   thresholds={"mode": "absolute", "steps": [{"color": "green", "value": None}, {"color": "orange", "value": 1}]}, no_value="0"),
        table_panel(ds, 5, "Quotas by Hard-Limit Utilization", top_targets, y=9, h=16,
                    sort_by=[{"displayName": "Hard utilization", "desc": True}]),
    ])

    if not influx:
        freshness = prom_target(ds, "A", 'time() - isilon_quota_collector_last_success_timestamp_seconds{cluster=~"$cluster"}')
        panels.append(stat_panel(ds, 6, "Snapshot Age", freshness, 25, x=0, w=8, h=4,
                                 unit="s", thresholds={"mode": "absolute", "steps": [{"color": "green", "value": None}, {"color": "orange", "value": 5400}, {"color": "red", "value": 9000}]}))

    dashboard = make_dashboard(
        "PowerScale - Quota Overview",
        "Current quota inventory, readiness, and threshold utilization.",
        tags, variables, panels, time_from="now-7d", refresh="5m")
    write_dashboard(dashboard, outpath(backend, "quota_overview.json"))


if __name__ == "__main__":
    for value in ("influxdb", "prometheus"):
        generate(value)
