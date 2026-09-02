# Quota Collector Implementation Plan

## Status

Implemented as `goquotas`, with the same OneFS 9.0-or-later support baseline as
the rest of the project. Unit, race, build, dashboard-generation, container,
Compose, and non-empty OneFS 9.11 validation are complete. Representative
large quota-set validation remains outstanding.

## Decision

Quota monitoring belongs in PowerScale Data Insights, but it will be an
independent collector rather than part of `gostats` or `goppstats`.

Quotas are sampled configuration and capacity state, not regular performance
statistics or Partitioned Performance data. They also have a substantially
slower collection cadence, separate OneFS privileges and licensing, different
pagination and readiness behavior, and potentially high cardinality. A
separate process keeps those concerns and failures isolated while reusing the
existing API, backend, configuration, logging, and platform packages.

## Scope and Defaults

The collector reads live quota state from the OneFS quotas
collection endpoint and writes snapshots to InfluxDB v1, InfluxDB v2, or
Prometheus. It will also support the discard backend used by the existing
collectors for tests and diagnostics. Importing historical OneFS quota reports
is out of scope for the first release.

Directory quotas are the default and primary use case. The default quota type
selection is:

```toml
quota_types = ["directory", "default-directory"]
```

The collector will issue type-filtered API requests for only the selected
types; it will not fetch every quota and discard unwanted types locally. User
and group quota families are opt-in by adding any of the following values:

```toml
quota_types = [
  "directory",
  "default-directory",
  "user",
  "default-user",
  "group",
  "default-group",
]
```

This default prevents the automatically created linked user and group quotas
common with default quotas from unexpectedly producing large API responses and
high Prometheus cardinality. Opting into those types does not disable any of
the other cardinality guardrails.

Other initial defaults and behavior:

- Collect immediately at startup and once per hour thereafter.
- Make the interval configurable using Go duration syntax.
- Add modest per-cluster scheduling jitter.
- Collect and validate all pages before publishing a snapshot.
- Keep the previous Prometheus snapshot after a partial or failed collection.
- Use API-side quota-type filtering. Collection-side path, recursive-path, and
  access-zone filters are not required for the initial implementation; retain
  them as straightforward follow-up controls if measured scale or deployment
  requirements justify them.
- Keep persona name resolution off by default. It is useful only after user or
  group quota types have been enabled and adds API work and label churn.
- Provide a configurable `max_quotas` safety limit. Exceeding it fails the
  collection visibly instead of silently truncating data.
- Log collected quota and emitted-series counts and export collector health
  metrics.

## OneFS API Contract

The live collection resource is:

```text
GET /platform/<pinned-version>/quota/quotas
```

The implementation must use the `limit` and `resume` collection pattern. A
resume request contains only the resume token, as required by PAPI, so the
selected type and other filters are applied to the initial request for each
type and the returned token drives its remaining pages.

Inspection of a OneFS 9.11 cluster shows quota resource revisions at PAPI
versions 1, 7, 8, 12, 15, and 19. The implementation will not automatically
follow the latest API representation. The discovery phase will compare those
schemas, choose the lowest pinned version that provides the required metrics
across the project's supported OneFS 9.x releases, and retain fixtures for all
supported response shapes.

The v19 schema confirms the following considerations:

- Quota types are `directory`, `user`, `group`, `default-directory`,
  `default-user`, and `default-group`.
- Usage values have individual readiness indicators, and a false readiness
  value means the accounting is waiting for a QuotaScan job.
- Thresholds apply to application logical, file-system logical, or physical
  usage according to `thresholds_on`.
- Threshold and exceeded fields can be null.
- The response contains a nullable `resume` token.
- Some usage and ratio fields require granular quota subprivileges.

The collector must never translate absent, null, or not-ready usage into zero.

The existing OneFS 9.0 minimum means the initial compatibility investigation
must start with the quota representation available to API version 10, compare
it with the later revisions present on OneFS 9.11, and pin the lowest resource
version that satisfies the agreed metric contract.

## Data Model

Write one logical `quota` point for each quota in each successful collection.
Use the collection completion time as the snapshot timestamp unless API schema
research identifies a reliable source timestamp.

Proposed tags or labels:

- `cluster`
- `quota_id`
- `quota_type`
- `path`
- `persona_type`, `persona_id`, and optionally `persona_name`
- `thresholds_on`
- `linked`
- `include_snapshots`

Do not use free-form descriptions as Prometheus labels.

Proposed fields or metrics:

- Raw application-logical, file-system-logical, file-system-physical, and
  physical usage in bytes
- Inode usage
- A canonical `usage_bytes` selected according to `thresholds_on`
- Advisory, soft, and hard threshold bytes
- Advisory, soft, and hard utilization ratios when their thresholds exist
- Advisory, soft, and hard exceeded states
- `ready`, per-value readiness, `enforced`, and `present` state
- Efficiency and reduction ratios where available and permitted
- Soft-grace and last-exceeded timestamps where present

Threshold configuration is repeated in each snapshot so limit changes can be
correlated with usage history.

Quota IDs remain the stable machine identity even though they are not suitable
as the primary user interface. Dashboards will present `path` as the main
human-readable quota selector. Where a path is not unique, quota type and
snapshot inclusion provide secondary selectors or display qualifiers. The
hidden/stable quota ID remains available for exact drill-down and correlation.

## Snapshot and Deletion Semantics

Each selected quota type is paginated independently. A collection is complete
only when all pages for all selected types have succeeded, all objects have
decoded, and the total remains within `max_quotas`.

For Prometheus, build the next complete set away from the active registry and
swap it atomically. Successful snapshots remove disappeared series; failed
snapshots retain the previous data and expose their age through health metrics.

For InfluxDB, preserve history normally. When a quota seen in the prior
in-memory snapshot disappears, write a final `present=false` point using its
known identity. Dashboards must also use a bounded freshness window because a
collector restart loses that in-memory deletion history.

## Prometheus Cardinality Controls

- Directory and default-directory quotas only by default.
- User, default-user, group, and default-group quotas require explicit opt-in.
- Query only enabled types at the API.
- Retain the `max_quotas` hard guardrail after opt-in.
- Avoid description and other free-form labels.
- Make persona name resolution explicit and disabled by default.
- Report the current object count, emitted series count, snapshot age,
  collection duration, and last successful collection time.
- Document expected series-per-quota costs before declaring the Prometheus
  implementation stable.

## Dashboards

Create matching InfluxDB and Prometheus dashboards using the existing unified
generation approach.

### Quota Overview

- Total collected quotas, clearly scoped to enabled quota types
- Counts over advisory, soft, and hard thresholds
- Not-ready quota count
- Top quotas by hard-limit utilization
- Usage and limits by quota type
- Cluster followed by quota path as the primary filters
- Secondary type, snapshot-inclusion, persona, and linked-state filters where
  needed to disambiguate quotas sharing a path
- Collection freshness, duration, failures, and cardinality

### Quota Detail

- Usage versus advisory, soft, and hard thresholds over time
- Current utilization and exceeded state
- Logical and physical usage trends
- Inode trend
- Threshold-exceeded history
- Quota configuration, readiness, and persona metadata

Alert templates are deferred until the metric contract has been validated in
real environments.

TSDB history retention is also outside this collector's scope. As with the
existing collectors, operators configure retention in InfluxDB or Prometheus.
Project-wide retention guidance should be revisited separately rather than
introducing a quota-only policy.

## Implementation Phases

### 1. Schema and scale discovery

- Capture and compare the OneFS quota schemas at resource versions 1, 7, 8,
  12, 15, and 19.
- Capture sanitized live examples for every enabled or potentially enabled
  quota type, including linked, accounting-only, enforcement, snapshot,
  exceeded, null-threshold, and not-ready cases.
- Validate the API version 10-era representation required by the OneFS 9.0
  baseline and choose the pinned PAPI resource version.
- Measure quota counts, page counts, response sizes, collection duration, and
  the cost of persona name resolution on a representative production-scale
  cluster. Customer log measurements may be supplied separately and are not a
  prerequisite for schema and collector development.
- Finalize the metric and configuration contracts.

### 2. Collector core

Add:

```text
cmd/goquotas/
├── main.go
├── config.go
├── isilon_api.go
├── backend.go
├── prometheus.go
└── *_test.go
```

Implement configuration loading and reload, per-cluster loops, immediate and
scheduled collection, API-side type filtering, pagination, tolerant response
decoding, snapshot validation, point conversion, retries, and graceful
shutdown. Reuse InfluxDB v1, InfluxDB v2, and discard backends from
`internal/backend`.

Do not make a broad refactor of the existing collectors a prerequisite. Extract
additional shared lifecycle or backend code only when the third implementation
demonstrates a small, stable common abstraction.

### 3. Prometheus backend

- Implement atomic snapshot replacement and deletion reconciliation.
- Retain the prior snapshot on collection failure.
- Export quota values with a bounded number of metric families.
- Export collector health and cardinality metrics.
- Test concurrent collection and scrape behavior.

### 4. Dashboards

- Add quota overview and quota detail generators.
- Generate regular and importable dashboards for InfluxDB and Prometheus.
- Test empty, directory-only, opted-in identity quota, exceeded, and stale
  states.

### 5. Packaging and documentation

- Add `goquotas` to the Makefile, GoReleaser, CI, install targets, and release
  archives.
- Add a multi-stage Dockerfile, both Compose stacks, Grafana provisioning, a
  systemd unit, and example configurations.
- Update architecture, configuration, deployment, getting-started, dashboard,
  OneFS setup, and migration documentation.
- Document the SmartQuotas license, read-only quota privileges, QuotaScan
  readiness, opt-in identity quota types, cardinality, cadence, and retention.

### 6. Validation

- Unit-test pagination, nullable and missing fields, every quota type, API
  version fixtures, cancellation, partial-page failure, and safety limits.
- Create unusual quota cases on a local OneFS cluster or a provisioned internal
  Duct Tape cluster, including not-ready, exceeded, percent-threshold,
  snapshot-tracking, and linked-directory cases.
- Test conversion and Prometheus atomic replacement/deletion behavior.
- Run end-to-end InfluxDB and Prometheus tests.
- Validate against multiple OneFS 9.x versions where available.
- Run synthetic and representative large-quota scale tests.
- Verify dashboards with accounting-only, limited, exceeded, linked, deleted,
  stale, and not-ready quotas.

## Exit Criteria

- Directory quota collection works without enabling user or group quota
  families.
- Enabling each additional quota type is explicit, documented, and tested.
- No partial API result can replace a previously successful snapshot.
- Null and not-ready values are never reported as zero.
- Prometheus series disappear after a successful snapshot confirms quota
  deletion.
- Both TSDB backends have working overview and detail dashboards.
- Scale and privilege requirements are documented from measured results.
- Builds, tests, packaging, and documentation include the new collector.

## Confirmed Decisions and Remaining Input

Confirmed:

- Support OneFS 9.0 and later.
- Collect `directory` and `default-directory` quotas by default.
- Require explicit opt-in for user and group quota families.
- Support InfluxDB v1, InfluxDB v2, Prometheus, and discard backends.
- Use a configurable collection interval with a one-hour default.
- Use cluster and then quota path as the primary dashboard selection flow;
  retain quota ID for internal identity and exact disambiguation.
- Leave data retention to the configured TSDB, consistent with the existing
  collectors.
- Generate unusual quota configurations during testing on a local or
  provisioned internal Duct Tape cluster.
- Do not require collection-side path or access-zone filtering for the initial
  implementation. Reconsider it if scale measurements establish a need.

The outstanding external input is representative customer scale data:
counts by quota type and linked state, preferably with page counts, response
sizes, or observed API duration from available logs. This is important for
choosing and validating default page and `max_quotas` limits, but it does not
block schema comparison, metric design, or collector implementation.

The read-only `/platform/1/quota/quotas-summary` endpoint can provide total,
directory, user, group, default-user, default-group, and linked counts without
returning paths or personas. It requires `ISI_PRIV_QUOTA_SUMMARY`. A separate
type-filtered count may still be needed to distinguish `default-directory`
from ordinary directory quotas.

## Live OneFS 9.11 Validation

Live validation on September 2, 2026 used a temporary, isolated quota tree on
OneFS 9.11.0.0. The fixture covered all six quota types, default-domain linked
user and group quotas, not-ready accounting followed by QuotaScan completion,
an exceeded hard threshold, percentage thresholds, snapshot inclusion,
container mode, and filesystem-logical, physical, and application-logical
accounting.

The collector successfully exercised API-side type filtering, persona name
resolution, pagination with a page size of two, configuration reload, and the
default directory-only selection. The all-type snapshot contained 11 quotas
and 203 Prometheus quota series; the directory/default-directory snapshot
contained five quotas and no identity-quota series. Collection duration on
this small test set was approximately 0.2–0.8 seconds.

Prometheus replacement was verified across a path rename and a quota deletion.
InfluxDB v1 writes and tombstones were verified against InfluxDB 1.8.10,
including an old path receiving `present=false` after rename and a deleted
quota receiving `present=false`. InfluxDB v2 writes were verified against
InfluxDB 2.7 through the opt-in `TestInfluxDBv2Integration` test. The v1 test
exposed that InfluxDB 1.8 rejects unsigned line-protocol values; quota counters
are consequently normalized to floating-point metric values for consistent
behavior across all backends.

The temporary quotas, filesystem data, role, users, group, API credential, and
InfluxDB container were removed after validation. The cluster again contained
no quotas. Representative customer-scale measurements remain the only external
validation input needed to revisit the provisional `max_quotas = 10000`
default.
