# Changelog

## v0.32 - Fri Mar 13 2026 -0700

### New features

- Add SIGHUP and config file watch-based config reload
  - On SIGTERM/SIGINT the collector shuts down as before
  - On SIGHUP (Unix) or when the config file is modified on disk (all platforms),
    all running collectors are cancelled and restarted with the new configuration
  - Config reload failures are logged and recovered from; the previous config
    continues to be used until a valid config is available
- Improve Prometheus HTTP SD JSON response
  - Replace manual string-building with a proper struct and json.Marshal,
    making the response correct by construction with proper error handling
- Add optional `instance_label_name` config setting to the `[prometheus]` section
  - Stamps a second copy of the Isilon cluster name under a configurable label name
  - Useful in Kubernetes environments where a `cluster` external label would
    otherwise cause Prometheus to rename the `cluster` metric label to `exported_cluster`

### Bug fixes

- Add missing `ISI_PRIV_STATISTICS` privilege to the recommended role setup
  - The `/platform/10/statistics/summary/workload` endpoint requires this privilege
    in addition to `ISI_PRIV_PERFORMANCE`

## v0.31 - Tue Mar 03 09:14:46 2026 -0800

### New features

- Add context propagation and graceful SIGINT/SIGTERM shutdown
  - All blocking operations (retry sleeps, end-of-cycle sleep) now respect
    context cancellation and exit promptly on signal
  - Prometheus HTTP servers (metrics and SD listener) shut down cleanly
    with a 5-second timeout on SIGTERM/SIGINT

### Bug fixes

- Fix code review issues: error handling, concurrency, naming, and style
- Fix golint issues: comments and naming
- Simplify `isConnectionRefused` to use `errors.Is`

## v0.30 - Wed Feb 25 11:38:50 2026 -0800

### New features

- Add goreleaser support for automated release builds

### Bug fixes

- Fix code review issues: correctness, naming, and error handling
- Move `validateConfigVersion` to `config.go`

## v0.29 - Thu Feb 19 12:42:38 2026 -0800

### New features

- Migrate logging from `op/go-logging` to `log/slog`
  - Custom log levels (CRITICAL, NOTICE, TRACE) preserved
  - Multi-handler fanout via `slog-multi` for simultaneous file and stdout logging
- Add ping check to InfluxDB v1 and v2 `Init` routines
- Add `-version` flag
- Force `SO_REUSEADDR`/`SO_REUSEPORT` on Prometheus listener sockets

### Bug fixes

- Fix Windows build after socket reuseaddr change
- Update dependencies (`golang.org/x/net`, `google.golang.org/protobuf`)

## v0.28 - Fri Jun 28 14:05:48 2024 -0700

### Bug fixes

- Fix NFS export id caching
  - The code checked for an entry in the cache, but would never find one since it didn't actually update the cache after a lookup

## v0.27 - Tue Jun 18 09:45:42 2024 -0700

### Bug fixes

- fix nil dereference in v0.26

## v0.26 - Mon Jun 17 11:06:17 2024 -0700

> [!WARNING]
> The Prometheus collector crashes in this release; use v0.27 instead which contains a fix for this issue

### Bug fixes

- Fix handling of pinned workloads for Prometheus
  - Pinned workloads are a special workload type
  - The Prometheus code did not understand this workload type and so it dropped the stats with an error
  - The fix now retains pinned stats and adds a new tag to all regular stats named "pinned" value "true" or "false"

## v0.25 - Thu Nov 16 17:40:36 2023 -0800

### New features

- Added support for InfluxDBv2 as a backend while retaining support for InfluxDBv1

### Bug fixes

- Fixed build issues with InfluxDBv1 libraries
- Fixed missing config compatibility in v0.24

## v0.24 - Tue Nov 14 19:07:48 2023 -0800

### New features

- Added the ability to preserve the case of cluster names instead of normalizing to lower case
- Added configurable retry interval and count to calls to write to the configured backend database

## v0.23 - Mon Nov 13 12:29:25 2023 -0800

> [!IMPORTANT]
> The config rewrite is a breaking change which will require
> a manual update of the configuration file post-upgrade.

### New features

- Added secret support and log to stdout support
  - Added secret support for sensitive information such as cluster passwords
  - Added logfile configuration to the config file
  - Logging to stdout is enabled via the log_to_stdout parameter
  - Logging to file can be configured in the config file and overridden at the command line

## v0.22 - Tue Nov 7 14:36:27 2023 -0800

### New features

- Added basic http landing page with description and link to "/metrics" endpoint

## v0.21 - Wed Nov 1 14:08:40 2023 -0700

### New features

- Added support for tls-encrypted connections to the Prometheus endpoint

## v0.20 - Tue Oct 31 09:41:21 2023 -0700

> [!IMPORTANT]
> The config rewrite is a breaking change which will require
> a manual update of the configuration file post-upgrade.

### Major changes

- Major config rewrite
  - This config change means older config files must be updated to be compatible
  - Renamed back end names (removed "_plugin")
  - Removed hacky "processor_args" inherited from the Python collector
  - Added config stanzas for InfluxDB and Prometheus
  - Added missing "lookup_export_ids" setting

## v0.19 - Mon Oct 30 15:44:38 2023 -0700

### Major changes

- Added config version checking
  - Upcoming changes will break the config file format.
  - Added a version check to avoid unexplained breakage.

## v0.18 - Sat Oct 28 15:18:39 2023 -0700

### Security

- Updated all dependencies to latest versions

### Bug fixes

- Restored missing "isilon" namespace from stats
  - In the switch to using our own Collector interface rather than the pre-canned gauges, the metric names lost their namespace prefix

## v0.17 - Thu Oct 26 13:26:06 2023 -0700

### Bug fixes

- Reworked Prometheus support
  - The initial Prometheus support had a major issue where stats that had been collected at least once, but which did not appear in the current collection cycle were still exposed via the `/metrics` endpoint
  - Completely rewrote the code. Advantages of the rewritten code include
    - the collector now correctly exports the original metric timestamp for each metric, and
    - the collector now expires metrics based on the metadata that defines how long they are value so stale metrics correctly disappear from the `/metrics` endpoint

## v0.16 - Mon Oct 2 12:56:59 2023 -0700

### New features

- Added support for NFS export id to path lookup
  - Optionally enabled via the config file.
  - If enabled, it is necessary to grant readonly NFS API access to theconfigured stats user.

## v0.15 - Mon Sep 18 14:18:14 2023 -0700

### New features

- Added support for hardcoding the HTTP SD listen addr

### Bug fixes

- Fixed HTTP SD output

## v0.14 - Wed Aug 30 15:53:42 2023 -0700

### New features

- Added support for Prometheus HTTP SD discovery

## v0.13 - Tue Aug 1 16:57:57 2023 -0700

### Bug fixes

 Fixed http routing with multple servers

## v0.12 - Tue Aug 1 16:28:19 2023 -0700

### Bug fixes

- Fixed prometheus plugin argument handling

## v0.11 - Fri Jul 28 08:23:46 2023 -0700

### Major changes

- example configuration filename changed to match tool name

### Bug fixes

- Fixed cluster name breakage introduced by prom work

## v0.10 - Thu Jul 27 10:16:23 2023 -0700

Version bump to sync with the current version of gostats

### New features

- Add Prometheus support
- Add support for authenticated InfluxDB connection

## v0.01 - Thu May 12 08:26:16 2022 -0700

### Initial release of the Golang OneFS stats collector
