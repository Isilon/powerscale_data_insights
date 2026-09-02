#!/usr/bin/env python3
"""Generate all PowerScale Grafana dashboards (InfluxDB + Prometheus).

Runs each dashboard generator to produce both backend variants.
Output goes to dashboards/influxdb/ and dashboards/prometheus/.
"""
import importlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

GENERATORS = [
    "generate_cluster_capacity",
    "generate_cluster_list",
    "generate_cluster_detail",
    "generate_cluster_protocol",
    "generate_drive_stats",
    "generate_drive_summary",
    "generate_protocol_summary",
    "generate_client_summary",
    "generate_system_workload",
    "generate_quota_overview",
    "generate_quota_detail",
]


def main():
    for name in GENERATORS:
        print(f"\n{'='*60}")
        print(f"  {name}")
        print(f"{'='*60}")
        mod = importlib.import_module(name)
        for backend in ("influxdb", "prometheus"):
            mod.generate(backend)

    print(f"\n{'='*60}")
    print(f"  All dashboards generated ({len(GENERATORS)} x 2 = "
          f"{len(GENERATORS) * 2} files)")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
