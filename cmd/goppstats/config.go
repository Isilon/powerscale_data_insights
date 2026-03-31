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

// config file structures
type tomlConfig struct {
	Global     globalConfig
	Logging    logging.LoggingConfig    `toml:"logging"`
	InfluxDB   config.InfluxDBConfig    `toml:"influxdb"`
	InfluxDBv2 config.InfluxDBv2Config  `toml:"influxdbv2"`
	Prometheus config.PrometheusConfig  `toml:"prometheus"`
	PromSD     config.PromHTTPSDConfig  `toml:"prom_http_sd"`
	Clusters   []config.ClusterConfig   `toml:"cluster"`
}

type globalConfig struct {
	Version             string  `toml:"version"`
	Processor           string  `toml:"stats_processor"`
	ProcessorMaxRetries int     `toml:"stats_processor_max_retries"`
	ProcessorRetryIntvl int     `toml:"stats_processor_retry_interval"`
	MinUpdateInvtl      int     `toml:"min_update_interval_override"`
	MaxRetries          int     `toml:"max_retries"`
	LookupExportIDs     bool    `toml:"lookup_export_ids"`
	PreserveCase        bool    `toml:"preserve_case"` // enable/disable normalization of Cluster Names
}

// validateConfigVersion checks the version of the config file to ensure that it is
// compatible with this version of the collector. Returns an error if not compatible.
func validateConfigVersion(confVersion string) error {
	if confVersion == "" {
		return fmt.Errorf("the collector requires a versioned config file (see the example config)")
	}
	v := strings.TrimLeft(confVersion, "vV")
	switch v {
	// last breaking change was moving logging config from [global] to [logging] in v0.29
	case "0.29", "0.30", "0.31", "0.32":
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
