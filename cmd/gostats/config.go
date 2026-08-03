package main

// stats project config handling

import (
	"fmt"
	"math"
	"os"
	"strings"

	"github.com/BurntSushi/toml"
	"github.com/isilon/powerscale_data_insights/internal/config"
	"github.com/isilon/powerscale_data_insights/internal/logging"
)

// tomlConfig defines the top-level structure of the config file
type tomlConfig struct {
	Global       globalConfig
	Logging      logging.LoggingConfig   `toml:"logging"`
	InfluxDB     config.InfluxDBConfig   `toml:"influxdb"`
	InfluxDBv2   config.InfluxDBv2Config `toml:"influxdbv2"`
	Prometheus   config.PrometheusConfig `toml:"prometheus"`
	PromSD       config.PromHTTPSDConfig `toml:"prom_http_sd"`
	Clusters     []config.ClusterConfig  `toml:"cluster"`
	SummaryStats summaryStatConfig       `toml:"summary_stats"`
	StatGroups   []statGroupConf         `toml:"statgroup"`
}

// globalConfig defines the global settings in the config file
type globalConfig struct {
	// Version identifies the config format version.
	Version string `toml:"version"`
	// Processor selects the metric backend.
	Processor string `toml:"stats_processor"`
	// ProcessorMaxRetries limits retries when writing to the backend.
	ProcessorMaxRetries int `toml:"stats_processor_max_retries"`
	// ProcessorRetryIntvl is the initial backend-write retry delay in seconds.
	ProcessorRetryIntvl int `toml:"stats_processor_retry_interval"`
	// MinUpdateInvtl is the minimum collection interval in seconds.
	MinUpdateInvtl int `toml:"min_update_interval_override"`
	// MaxRetries limits retries for transport-level PAPI failures.
	MaxRetries int `toml:"max_retries"`
	// ActiveStatGroups lists the enabled stat groups.
	ActiveStatGroups []string `toml:"active_stat_groups"`
	// PreserveCase disables normalization of cluster names when true.
	PreserveCase bool `toml:"preserve_case"`
	// IncludeDegraded adds the OneFS degraded status to metric tags.
	IncludeDegraded bool `toml:"include_degraded"`
	// FetchByStatgroup fetches one stat group at a time when true.
	FetchByStatgroup bool `toml:"fetch_by_statgroup"`
	// StatTimeout is passed as the "timeout" parameter on the statistics/current
	// request, bounding how long the cluster waits for results from remote nodes.
	// 0 (the default) omits the parameter and uses the cluster default.
	StatTimeout int `toml:"stat_timeout"`
	// StatRetries is the number of extra attempts, within a single collection
	// cycle, to re-query stats that returned transient (timeout/stale) per-stat
	// errors. 0 disables per-stat retry.
	StatRetries int `toml:"stat_retries"`
	// StatRetryIntvl is the initial delay in seconds before per-stat transient
	// retries within a cycle (exponential backoff).
	StatRetryIntvl int `toml:"stat_retry_interval"`
}

// summaryStatConfig defines whether protocol and/or client summary stats are collected
type summaryStatConfig struct {
	Protocol bool // protocol summary stats enabled?
	Client   bool // client summary stats enabled?
	Drive    bool // drive summary stats enabled?
}

// The collector partitions the stats to be collected into two tiers.
// At the top level, there are named groups and each group consists of a subset of stats.
// This facilitates grouping related stats and enabling/disabling collection
// by simply adding/removing the group name to the top-level set.
type statGroupConf struct {
	Name        string
	UpdateIntvl string `toml:"update_interval"`
	Stats       []string
}

// validateConfigVersion checks the version of the config file to ensure that it is
// compatible with this version of the collector. Returns an error if not compatible.
func validateConfigVersion(confVersion string) error {
	if confVersion == "" {
		return fmt.Errorf("the collector requires a versioned config file (see the example config)")
	}
	v := strings.TrimLeft(confVersion, "vV")
	switch v {
	// last breaking change was the major logging rewrite in v0.31
	case "0.31", "0.32", "0.33", "0.34", "0.35", "0.36", "0.37", "0.38", "0.39", "0.40":
		return nil
	}
	return fmt.Errorf("config file version %q is not compatible with collector version %s", confVersion, Version)
}

// readConfig reads and validates the config file, returning an error if it fails.
// This is used for config reloads (SIGHUP) where a failure should be logged and
// recovered from rather than causing the process to exit.
func readConfig(configFileName string) (tomlConfig, error) {
	var conf tomlConfig
	conf.Global.MaxRetries = config.DefaultMaxRetries
	conf.Global.ProcessorMaxRetries = config.DefaultProcessorMaxRetries
	conf.Global.ProcessorRetryIntvl = config.DefaultProcessorRetryInterval
	conf.Global.MinUpdateInvtl = config.DefaultMinUpdateInterval
	conf.Global.PreserveCase = config.DefaultPreserveCase
	conf.Global.StatTimeout = config.DefaultStatTimeout
	conf.Global.StatRetries = config.DefaultStatRetries
	conf.Global.StatRetryIntvl = config.DefaultStatRetryInterval

	_, err := toml.DecodeFile(configFileName, &conf)
	if err != nil {
		return tomlConfig{}, fmt.Errorf("failed to read config file %s: %w", configFileName, err)
	}
	if err := validateConfigVersion(conf.Global.Version); err != nil {
		return tomlConfig{}, err
	}

	// If retries is 0 or negative, make it effectively infinite
	if conf.Global.MaxRetries <= 0 {
		conf.Global.MaxRetries = math.MaxInt
	}
	if conf.Global.ProcessorMaxRetries <= 0 {
		conf.Global.ProcessorMaxRetries = math.MaxInt
	}
	// Negative values are meaningless; treat them as "disabled"/default.
	if conf.Global.StatRetries < 0 {
		conf.Global.StatRetries = 0
	}
	if conf.Global.StatRetryIntvl < 1 {
		conf.Global.StatRetryIntvl = config.DefaultStatRetryInterval
	}
	if conf.Global.StatTimeout < 0 {
		conf.Global.StatTimeout = 0
	}

	return conf, nil
}

// mustReadConfig reads the config file or exits the program if this fails.
// Used at startup where a bad config is unrecoverable.
func mustReadConfig(configFileName string) tomlConfig {
	conf, err := readConfig(configFileName)
	if err != nil {
		fmt.Fprintf(os.Stderr, "%s: %v\nExiting\n", os.Args[0], err)
		os.Exit(1)
	}
	return conf
}
