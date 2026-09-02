#!/usr/bin/env python3
"""Generate quota detail dashboards for InfluxDB and Prometheus."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dashlib import *

README = """\
## PowerScale - Quota Detail

Usage, limits, and inode history for the selected quota path. If several quota
domains share a path, use quota type and snapshot inclusion to disambiguate
them. Missing lines indicate an unset threshold or a value that OneFS reports
as not ready; they are never converted to zero.
"""


def generate(backend):
    ds = DS_INFLUXDB if backend == "influxdb" else DS_PROMETHEUS
    influx = backend == "influxdb"
    tags = ["powerscale", "goquotas"] + ([] if influx else ["prometheus"])

    if influx:
        # Path is a single-select value and normally contains '/'. Using it as
        # an unescaped InfluxQL regex breaks the regex delimiter (for example,
        # /^/ifs/data$/). Grafana's singlequote formatter safely produces an
        # InfluxQL string literal for each dependent variable.
        where = '"cluster" =~ /^$cluster$/ AND "path" = ${path:singlequote} AND "quota_type" = ${quota_type:singlequote} AND "include_snapshots" = ${include_snapshots:singlequote} AND $timeFilter'
        usage_targets = [
            influx_target(ds, "A", f'SELECT mean("usage_bytes") FROM "quota" WHERE {where} GROUP BY time($__interval), "quota_id" fill(null)', "Usage"),
            influx_target(ds, "B", f'SELECT mean("advisory_bytes") FROM "quota" WHERE {where} GROUP BY time($__interval), "quota_id" fill(null)', "Advisory"),
            influx_target(ds, "C", f'SELECT mean("soft_bytes") FROM "quota" WHERE {where} GROUP BY time($__interval), "quota_id" fill(null)', "Soft"),
            influx_target(ds, "D", f'SELECT mean("hard_bytes") FROM "quota" WHERE {where} GROUP BY time($__interval), "quota_id" fill(null)', "Hard"),
        ]
        inode_targets = [influx_target(ds, "A", f'SELECT mean("usage_inodes") FROM "quota" WHERE {where} GROUP BY time($__interval), "quota_id" fill(null)', "Inodes")]
        physical_targets = [
            influx_target(ds, "A", f'SELECT mean("usage_applogical_bytes") FROM "quota" WHERE {where} GROUP BY time($__interval), "quota_id" fill(null)', "Application logical"),
            influx_target(ds, "B", f'SELECT mean("usage_fslogical_bytes") FROM "quota" WHERE {where} GROUP BY time($__interval), "quota_id" fill(null)', "Filesystem logical"),
            influx_target(ds, "C", f'SELECT mean("usage_physical_bytes") FROM "quota" WHERE {where} GROUP BY time($__interval), "quota_id" fill(null)', "Physical"),
        ]
        variables = [
            var_query(ds, "cluster", "Cluster", 'SHOW TAG VALUES FROM "quota" WITH KEY = "cluster"', sort=1),
            var_query(ds, "path", "Quota Path", 'SHOW TAG VALUES FROM "quota" WITH KEY = "path" WHERE "cluster" =~ /^$cluster$/', sort=1),
            var_query(ds, "quota_type", "Quota Type", 'SHOW TAG VALUES FROM "quota" WITH KEY = "quota_type" WHERE "cluster" =~ /^$cluster$/ AND "path" = ${path:singlequote}', sort=1),
            var_query(ds, "include_snapshots", "Includes Snapshots", 'SHOW TAG VALUES FROM "quota" WITH KEY = "include_snapshots" WHERE "cluster" =~ /^$cluster$/ AND "path" = ${path:singlequote} AND "quota_type" = ${quota_type:singlequote}', sort=1),
        ]
    else:
        labels = 'cluster=~"$cluster",path=~"$path",quota_type=~"$quota_type",include_snapshots=~"$include_snapshots"'
        usage_targets = [
            prom_target(ds, "A", f'isilon_quota_usage_bytes{{{labels}}}', "Usage"),
            prom_target(ds, "B", f'isilon_quota_advisory_bytes{{{labels}}}', "Advisory"),
            prom_target(ds, "C", f'isilon_quota_soft_bytes{{{labels}}}', "Soft"),
            prom_target(ds, "D", f'isilon_quota_hard_bytes{{{labels}}}', "Hard"),
        ]
        inode_targets = [prom_target(ds, "A", f'isilon_quota_usage_inodes{{{labels}}}', "Inodes")]
        physical_targets = [
            prom_target(ds, "A", f'isilon_quota_usage_applogical_bytes{{{labels}}}', "Application logical"),
            prom_target(ds, "B", f'isilon_quota_usage_fslogical_bytes{{{labels}}}', "Filesystem logical"),
            prom_target(ds, "C", f'isilon_quota_usage_physical_bytes{{{labels}}}', "Physical"),
        ]
        variables = [
            var_query(ds, "cluster", "Cluster", "label_values(isilon_quota_present, cluster)", sort=1),
            var_query(ds, "path", "Quota Path", 'label_values(isilon_quota_present{cluster=~"$cluster"}, path)', sort=1),
            var_query(ds, "quota_type", "Quota Type", 'label_values(isilon_quota_present{cluster=~"$cluster",path=~"$path"}, quota_type)', sort=1),
            var_query(ds, "include_snapshots", "Includes Snapshots", 'label_values(isilon_quota_present{cluster=~"$cluster",path=~"$path",quota_type=~"$quota_type"}, include_snapshots)', sort=1),
        ]

    panels = [
        text_panel(1, README, 0, h=4),
        timeseries_panel(ds, 2, "Usage and Thresholds", usage_targets, 4, unit="bytes", h=10),
        timeseries_panel(ds, 3, "Logical and Physical Usage", physical_targets, 14, unit="bytes", h=9),
        timeseries_panel(ds, 4, "Inodes", inode_targets, 23, unit="short", h=8),
    ]
    dashboard = make_dashboard(
        "PowerScale - Quota Detail",
        "Historical usage and thresholds for a selected quota path.",
        tags, variables, panels, time_from="now-30d", refresh="5m")
    write_dashboard(dashboard, outpath(backend, "quota_detail.json"))


if __name__ == "__main__":
    for value in ("influxdb", "prometheus"):
        generate(value)
