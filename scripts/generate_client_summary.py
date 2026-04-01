#!/usr/bin/env python3
"""Generate the Client Summary Stats dashboard.

Uses node.summary.client data which provides per-client, per-protocol,
per-class breakdowns with latency statistics (avg/min/max).

Generates both InfluxDB and Prometheus variants.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dashlib import *

README = """\
## PowerScale - Client Summary Stats

Per-client protocol activity, throughput, and latency from OneFS client \
summary statistics. Identifies busiest or highest-latency clients on \
the cluster.

Requires `client = true` in the `[summary_stats]` section of the \
gostats collector configuration.

**Cardinality warning:** Client summary stats have high tag/label \
cardinality (remote_addr x protocol x class x node). On large clusters \
with many clients this can impact database performance."""

MEAS = "node.summary.client"
M    = "isilon_stat_node_summary_client"


def generate(backend):
    ds = DS_INFLUXDB if backend == "influxdb" else DS_PROMETHEUS
    influx = (backend == "influxdb")
    tags = ["powerscale", "gostats", "summary"] + (["prometheus"] if not influx else [])

    def T(refId, iq, pq, alias=None, legend=None, **kw):
        if influx:
            return influx_target(ds, refId, iq, alias=alias, **kw)
        return prom_target(ds, refId, pq, legend=legend)

    W = ('"cluster" =~ /^$cluster$/ AND "node" =~ /^$node$/ '
         'AND "protocol" =~ /^$protocol$/') if influx else ""
    C = '{cluster=~"$cluster",node=~"$node",protocol=~"$protocol"}'

    panels = []; pid = 1; y = 0

    # ── README panel ──
    panels.append(text_panel(pid, README, y, h=5)); pid += 1; y += 5

    # ── Overview stats ──
    for i, (title, iq, pq, unit, dec) in enumerate([
        ("Total Client Ops/s",
         f'SELECT sum("operation_rate") FROM "{MEAS}" WHERE {W} AND $timeFilter GROUP BY time($__interval) fill(null)' if influx else "",
         f'sum({M}_operation_rate{C})', "ops", 0),
        ("Average Latency",
         f'SELECT mean("time_avg") / 1000 FROM "{MEAS}" WHERE {W} AND $timeFilter GROUP BY time($__interval) fill(null)' if influx else "",
         f'avg({M}_time_avg{C}) / 1000', "ms", 2),
        ("Inbound Throughput",
         f'SELECT sum("in") FROM "{MEAS}" WHERE {W} AND $timeFilter GROUP BY time($__interval) fill(null)' if influx else "",
         f'sum({M}_in{C})', "Bps", None),
        ("Outbound Throughput",
         f'SELECT sum("out") FROM "{MEAS}" WHERE {W} AND $timeFilter GROUP BY time($__interval) fill(null)' if influx else "",
         f'sum({M}_out{C})', "Bps", None),
    ]):
        panels.append(stat_panel(ds, pid, title, T("A", iq, pq),
                                 y=y, x=i*6, w=6, h=4, unit=unit, decimals=dec))
        pid += 1
    y += 4

    # ── Top Clients Table ──
    def TT(refId, iq, pq):
        if influx:
            return influx_target(ds, refId, iq, fmt="table")
        t = prom_target(ds, refId, pq)
        t["instant"] = True
        t["format"] = "table"
        return t

    table_targets = [
        TT("A",
           f'SELECT sum("operation_rate") AS "Ops/s" FROM "{MEAS}" WHERE {W} AND $timeFilter GROUP BY "remote_addr"',
           f'sum by (remote_addr) ({M}_operation_rate{C})'),
        TT("B",
           f'SELECT mean("time_avg") / 1000 AS "Avg Latency (ms)" FROM "{MEAS}" WHERE {W} AND $timeFilter GROUP BY "remote_addr"',
           f'avg by (remote_addr) ({M}_time_avg{C}) / 1000'),
        TT("C",
           f'SELECT mean("time_max") / 1000 AS "Max Latency (ms)" FROM "{MEAS}" WHERE {W} AND $timeFilter GROUP BY "remote_addr"',
           f'avg by (remote_addr) ({M}_time_max{C}) / 1000'),
        TT("D",
           f'SELECT sum("in") AS "Inbound (B/s)" FROM "{MEAS}" WHERE {W} AND $timeFilter GROUP BY "remote_addr"',
           f'sum by (remote_addr) ({M}_in{C})'),
        TT("E",
           f'SELECT sum("out") AS "Outbound (B/s)" FROM "{MEAS}" WHERE {W} AND $timeFilter GROUP BY "remote_addr"',
           f'sum by (remote_addr) ({M}_out{C})'),
    ]

    avg_lat_th = {"mode": "absolute", "steps": [
        {"color": "green", "value": None}, {"color": "orange", "value": 10}, {"color": "red", "value": 50}]}
    max_lat_th = {"mode": "absolute", "steps": [
        {"color": "green", "value": None}, {"color": "orange", "value": 50}, {"color": "red", "value": 200}]}
    lat_cell = {"type": "color-background", "mode": "gradient"}

    tbl_overrides = [
        {"matcher": {"id": "byName", "options": "Time"}, "properties": [
            {"id": "custom.hidden", "value": True}]},
        {"matcher": {"id": "byName", "options": "remote_addr"}, "properties": [
            {"id": "displayName", "value": "Client"}, {"id": "custom.width", "value": 150}]},
    ]

    if influx:
        tbl_overrides += [
            {"matcher": {"id": "byName", "options": "Ops/s"}, "properties": [
                {"id": "unit", "value": "ops"}, {"id": "decimals", "value": 1}]},
            {"matcher": {"id": "byName", "options": "Avg Latency (ms)"}, "properties": [
                {"id": "unit", "value": "ms"}, {"id": "decimals", "value": 2},
                {"id": "thresholds", "value": avg_lat_th},
                {"id": "custom.cellOptions", "value": lat_cell}]},
            {"matcher": {"id": "byName", "options": "Max Latency (ms)"}, "properties": [
                {"id": "unit", "value": "ms"}, {"id": "decimals", "value": 1},
                {"id": "thresholds", "value": max_lat_th},
                {"id": "custom.cellOptions", "value": lat_cell}]},
            {"matcher": {"id": "byName", "options": "Inbound (B/s)"}, "properties": [
                {"id": "unit", "value": "Bps"}, {"id": "decimals", "value": 1}]},
            {"matcher": {"id": "byName", "options": "Outbound (B/s)"}, "properties": [
                {"id": "unit", "value": "Bps"}, {"id": "decimals", "value": 1}]},
        ]
    else:
        tbl_overrides += [
            {"matcher": {"id": "byName", "options": "Value #A"}, "properties": [
                {"id": "displayName", "value": "Ops/s"},
                {"id": "unit", "value": "ops"}, {"id": "decimals", "value": 1}]},
            {"matcher": {"id": "byName", "options": "Value #B"}, "properties": [
                {"id": "displayName", "value": "Avg Latency (ms)"},
                {"id": "unit", "value": "ms"}, {"id": "decimals", "value": 2},
                {"id": "thresholds", "value": avg_lat_th},
                {"id": "custom.cellOptions", "value": lat_cell}]},
            {"matcher": {"id": "byName", "options": "Value #C"}, "properties": [
                {"id": "displayName", "value": "Max Latency (ms)"},
                {"id": "unit", "value": "ms"}, {"id": "decimals", "value": 1},
                {"id": "thresholds", "value": max_lat_th},
                {"id": "custom.cellOptions", "value": lat_cell}]},
            {"matcher": {"id": "byName", "options": "Value #D"}, "properties": [
                {"id": "displayName", "value": "Inbound (B/s)"},
                {"id": "unit", "value": "Bps"}, {"id": "decimals", "value": 1}]},
            {"matcher": {"id": "byName", "options": "Value #E"}, "properties": [
                {"id": "displayName", "value": "Outbound (B/s)"},
                {"id": "unit", "value": "Bps"}, {"id": "decimals", "value": 1}]},
        ]

    panels.append(table_panel(ds, pid, "Top Clients", table_targets, y=y, h=10,
                              overrides=tbl_overrides,
                              sort_by=[{"displayName": "Ops/s", "desc": True}],
                              transformations=[{"id": "merge", "options": {}}]))
    pid += 1; y += 10

    # ── Timeseries panels ──
    def _iq(agg, field, scale="", group_tag="remote_addr"):
        return (f'SELECT {agg}("{field}"){scale} FROM "{MEAS}" '
                f'WHERE {W} AND $timeFilter '
                f'GROUP BY time($__interval), "{group_tag}" fill(null)')

    ts_panels = [
        ("Operation Rate by Client",
         [T("A", _iq("sum", "operation_rate") if influx else "",
                 f'sum by (remote_addr) ({M}_operation_rate{C})',
                 alias="$tag_remote_addr", legend="{{remote_addr}}")],
         "ops", "Ops/s"),
        ("Average Latency by Client",
         [T("A", _iq("mean", "time_avg", " / 1000") if influx else "",
                 f'avg by (remote_addr) ({M}_time_avg{C}) / 1000',
                 alias="$tag_remote_addr", legend="{{remote_addr}}")],
         "ms", "Latency"),
        ("Operation Rate by Protocol",
         [T("A", _iq("sum", "operation_rate", group_tag="protocol") if influx else "",
                 f'sum by (protocol) ({M}_operation_rate{C})',
                 alias="$tag_protocol", legend="{{protocol}}")],
         "ops", "Ops/s"),
        ("Average Latency by Protocol",
         [T("A", _iq("mean", "time_avg", " / 1000", group_tag="protocol") if influx else "",
                 f'avg by (protocol) ({M}_time_avg{C}) / 1000',
                 alias="$tag_protocol", legend="{{protocol}}")],
         "ms", "Latency"),
        ("Operation Rate by Class",
         [T("A", _iq("sum", "operation_rate", group_tag="class") if influx else "",
                 f'sum by (class) ({M}_operation_rate{C})',
                 alias="$tag_class", legend="{{class}}")],
         "ops", "Ops/s"),
        ("Average Latency by Class",
         [T("A", _iq("mean", "time_avg", " / 1000", group_tag="class") if influx else "",
                 f'avg by (class) ({M}_time_avg{C}) / 1000',
                 alias="$tag_class", legend="{{class}}")],
         "ms", "Latency"),
        ("Operation Rate by Node",
         [T("A", _iq("sum", "operation_rate", group_tag="node") if influx else "",
                 f'sum by (node) ({M}_operation_rate{C})',
                 alias="Node $tag_node", legend="Node {{node}}")],
         "ops", "Ops/s"),
        ("Average Latency by Node",
         [T("A", _iq("mean", "time_avg", " / 1000", group_tag="node") if influx else "",
                 f'avg by (node) ({M}_time_avg{C}) / 1000',
                 alias="Node $tag_node", legend="Node {{node}}")],
         "ms", "Latency"),
    ]

    for title, targets, unit, axis_lbl in ts_panels:
        panels.append(timeseries_panel(ds, pid, title, targets,
                                       y=y, unit=unit, axis_label=axis_lbl, axis_min=0))
        pid += 1; y += 8

    # ── Template variables ──
    if influx:
        variables = [
            var_query(ds, "cluster", "Cluster",
                      'SHOW TAG VALUES WITH KEY = "cluster"'),
            var_query(ds, "node", "Node",
                      f'SHOW TAG VALUES FROM "{MEAS}" WITH KEY = "node" WHERE "cluster" =~ /^$cluster$/',
                      multi=True, include_all=True),
            var_query(ds, "protocol", "Protocol",
                      f'SHOW TAG VALUES FROM "{MEAS}" WITH KEY = "protocol" WHERE "cluster" =~ /^$cluster$/',
                      multi=True, include_all=True),
        ]
    else:
        variables = [
            var_query(ds, "cluster", "Cluster",
                      f'label_values({M}_operation_rate, cluster)'),
            var_query(ds, "node", "Node",
                      f'label_values({M}_operation_rate{{cluster=~"$cluster"}}, node)',
                      multi=True, include_all=True),
            var_query(ds, "protocol", "Protocol",
                      f'label_values({M}_operation_rate{{cluster=~"$cluster"}}, protocol)',
                      multi=True, include_all=True),
        ]

    dash = make_dashboard(
        title="PowerScale - Client Summary Stats",
        description="Per-client protocol activity, throughput, and latency. "
                    "Uses OneFS client summary statistics to identify busiest "
                    "or highest-latency clients.",
        tags=tags,
        variables=variables,
        panels=panels,
    )
    write_dashboard(dash, outpath(backend, "client_summary.json"))


if __name__ == "__main__":
    for b in ("influxdb", "prometheus"):
        print(f"\n=== {b} ===")
        generate(b)
