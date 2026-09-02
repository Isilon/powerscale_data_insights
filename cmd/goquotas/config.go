package main

import (
	"fmt"
	"math"
	"os"
	"strings"
	"time"

	"github.com/BurntSushi/toml"
	"github.com/isilon/powerscale_data_insights/internal/config"
	"github.com/isilon/powerscale_data_insights/internal/logging"
)

const (
	configVersion             = "0.1"
	defaultCollectionInterval = time.Hour
	defaultPageLimit          = 1000
	defaultMaxQuotas          = 10000
)

type tomlConfig struct {
	Global     globalConfig
	Logging    logging.LoggingConfig   `toml:"logging"`
	InfluxDB   config.InfluxDBConfig   `toml:"influxdb"`
	InfluxDBv2 config.InfluxDBv2Config `toml:"influxdbv2"`
	Prometheus config.PrometheusConfig `toml:"prometheus"`
	PromSD     config.PromHTTPSDConfig `toml:"prom_http_sd"`
	Clusters   []config.ClusterConfig  `toml:"cluster"`
}

type globalConfig struct {
	Version             string   `toml:"version"`
	Processor           string   `toml:"stats_processor"`
	ProcessorMaxRetries int      `toml:"stats_processor_max_retries"`
	ProcessorRetryIntvl int      `toml:"stats_processor_retry_interval"`
	MaxRetries          int      `toml:"max_retries"`
	PreserveCase        bool     `toml:"preserve_case"`
	CollectionInterval  string   `toml:"collection_interval"`
	PageLimit           int      `toml:"page_limit"`
	MaxQuotas           int      `toml:"max_quotas"`
	QuotaTypes          []string `toml:"quota_types"`
	ResolveNames        bool     `toml:"resolve_names"`

	collectionDuration time.Duration
}

func validateConfigVersion(v string) error {
	v = strings.TrimLeft(v, "vV")
	if v != configVersion {
		return fmt.Errorf("config file version %q is not compatible with collector version %s", v, configVersion)
	}
	return nil
}

func readConfig(configFileName string) (tomlConfig, error) {
	conf := tomlConfig{}
	conf.Global.Processor = influxPluginName
	conf.Global.ProcessorMaxRetries = config.DefaultProcessorMaxRetries
	conf.Global.ProcessorRetryIntvl = config.DefaultProcessorRetryInterval
	conf.Global.MaxRetries = config.DefaultMaxRetries
	conf.Global.PreserveCase = config.DefaultPreserveCase
	conf.Global.CollectionInterval = defaultCollectionInterval.String()
	conf.Global.PageLimit = defaultPageLimit
	conf.Global.MaxQuotas = defaultMaxQuotas
	conf.Global.QuotaTypes = append([]string(nil), defaultQuotaTypes...)
	conf.PromSD.SDport = 9999

	if _, err := toml.DecodeFile(configFileName, &conf); err != nil {
		return tomlConfig{}, fmt.Errorf("failed to read config file %s: %w", configFileName, err)
	}
	if err := validateConfigVersion(conf.Global.Version); err != nil {
		return tomlConfig{}, err
	}
	switch conf.Global.Processor {
	case influxPluginName, influxV2PluginName, promPluginName, discardPluginName:
	default:
		return tomlConfig{}, fmt.Errorf("unsupported stats_processor %q", conf.Global.Processor)
	}

	duration, err := time.ParseDuration(conf.Global.CollectionInterval)
	if err != nil || duration <= 0 {
		return tomlConfig{}, fmt.Errorf("collection_interval must be a positive Go duration: %q", conf.Global.CollectionInterval)
	}
	conf.Global.collectionDuration = duration
	if conf.Global.PageLimit <= 0 {
		return tomlConfig{}, fmt.Errorf("page_limit must be greater than zero")
	}
	if conf.Global.MaxQuotas <= 0 {
		return tomlConfig{}, fmt.Errorf("max_quotas must be greater than zero")
	}
	if conf.Global.ProcessorRetryIntvl <= 0 {
		return tomlConfig{}, fmt.Errorf("stats_processor_retry_interval must be greater than zero")
	}
	if len(conf.Global.QuotaTypes) == 0 {
		return tomlConfig{}, fmt.Errorf("quota_types must contain at least one quota type")
	}
	seen := make(map[string]struct{}, len(conf.Global.QuotaTypes))
	for _, quotaType := range conf.Global.QuotaTypes {
		if _, ok := validQuotaTypes[quotaType]; !ok {
			return tomlConfig{}, fmt.Errorf("unsupported quota type %q", quotaType)
		}
		if _, ok := seen[quotaType]; ok {
			return tomlConfig{}, fmt.Errorf("duplicate quota type %q", quotaType)
		}
		seen[quotaType] = struct{}{}
	}
	if conf.Global.MaxRetries <= 0 {
		conf.Global.MaxRetries = math.MaxInt
	}
	if conf.Global.ProcessorMaxRetries <= 0 {
		conf.Global.ProcessorMaxRetries = math.MaxInt
	}
	return conf, nil
}

func mustReadConfig(configFileName string) tomlConfig {
	conf, err := readConfig(configFileName)
	if err != nil {
		fmt.Fprintf(os.Stderr, "%s: %v\nExiting\n", os.Args[0], err)
		os.Exit(1)
	}
	return conf
}
