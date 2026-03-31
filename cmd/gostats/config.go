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
	Logging      logging.LoggingConfig    `toml:"logging"`
	InfluxDB     config.InfluxDBConfig    `toml:"influxdb"`
	InfluxDBv2   config.InfluxDBv2Config  `toml:"influxdbv2"`
	Prometheus   config.PrometheusConfig  `toml:"prometheus"`
	PromSD       config.PromHTTPSDConfig  `toml:"prom_http_sd"`
	Clusters     []config.ClusterConfig   `toml:"cluster"`
	SummaryStats summaryStatConfig        `toml:"summary_stats"`
	StatGroups   []statGroupConf          `toml:"statgroup"`
}

// globalConfig defines the global settings in the config file
type globalConfig struct {
	Version             string   `toml:"version"`
	Processor           string   `toml:"stats_processor"`
	ProcessorMaxRetries int      `toml:"stats_processor_max_retries"`
	ProcessorRetryIntvl int      `toml:"stats_processor_retry_interval"`
	MinUpdateInvtl      int      `toml:"min_update_interval_override"`
	MaxRetries          int      `toml:"max_retries"`
	ActiveStatGroups    []string `toml:"active_stat_groups"`
	PreserveCase        bool     `toml:"preserve_case"`       // enable/disable normalization of Cluster Names
	IncludeDegraded     bool     `toml:"include_degraded"`    // include degraded status tag in metrics
	FetchByStatgroup    bool     `toml:"fetch_by_statgroup"`  // fetch stats one stat group at a time
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
	case "0.31", "0.32", "0.33", "0.34", "0.35", "0.36", "0.37", "0.38", "0.39":
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
