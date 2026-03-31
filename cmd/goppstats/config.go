package main

// stats project config handling

import (
	"fmt"
	"math"
	"os"
	"strings"

	"github.com/BurntSushi/toml"
)

// If not overridden, we will only poll every minUpdateInterval seconds
const defaultMinUpdateInterval = 30

// Default retry limit
const defaultMaxRetries = 8
const processorDefaultMaxRetries = 8
const processorDefaultRetryIntvl = 5

// Default Normalizaion of ClusterNames
const defaultPreserveCase = false

// config file structures
type tomlConfig struct {
	Global     globalConfig
	Logging    loggingConfig    `toml:"logging"`
	InfluxDB   influxDBConfig   `toml:"influxdb"`
	InfluxDBv2 influxDBv2Config `toml:"influxdbv2"`
	Prometheus prometheusConfig `toml:"prometheus"`
	PromSD     promSdConf       `toml:"prom_http_sd"`
	Clusters   []clusterConf    `toml:"cluster"`
}

type loggingConfig struct {
	LogFile       *string `toml:"logfile"`
	LogFileFormat *string `toml:"log_file_format"`
	LogLevel      *string `toml:"log_level"`
	LogToStdout   bool    `toml:"log_to_stdout"`
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

type influxDBConfig struct {
	Host          string `toml:"host"`
	Port          string `toml:"port"`
	Database      string `toml:"database"`
	Authenticated bool   `toml:"authenticated"`
	Username      string `toml:"username"`
	Password      string `toml:"password"`
}

type influxDBv2Config struct {
	Host   string `toml:"host"`
	Port   string `toml:"port"`
	Org    string `toml:"org"`
	Bucket string `toml:"bucket"`
	Token  string `toml:"access_token"`
}

type prometheusConfig struct {
	Authenticated     bool    `toml:"authenticated"`
	Username          string  `toml:"username"`
	Password          string  `toml:"password"`
	TLSCert           string  `toml:"tls_cert"`
	TLSKey            string  `toml:"tls_key"`
	InstanceLabelName *string `toml:"instance_label_name"`
}

type promSdConf struct {
	Enabled    bool
	ListenAddr string `toml:"listen_addr"`
	SDport     uint64 `toml:"sd_port"`
}

type clusterConf struct {
	Hostname       string  // cluster name/ip; ideally use a SmartConnect name
	Username       string  // account with the appropriate PAPI roles
	Password       string  // password for the account
	AuthType       string  // authentication type: "session" or "basic-auth"
	SSLCheck       bool    `toml:"verify-ssl"` // turn on/off SSL cert checking to handle self-signed certificates
	Disabled       bool    // if set, disable collection for this cluster
	PrometheusPort *uint64 `toml:"prometheus_port"` // If using the Prometheus collector, define the listener port for the metrics handler
	PreserveCase   *bool   `toml:"preserve_case"`   // Overwrite normalization of Cluster Name
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
	conf.Global.MaxRetries = defaultMaxRetries
	conf.Global.ProcessorMaxRetries = processorDefaultMaxRetries
	conf.Global.ProcessorRetryIntvl = processorDefaultRetryIntvl
	conf.Global.MinUpdateInvtl = defaultMinUpdateInterval
	conf.Global.PreserveCase = defaultPreserveCase
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

const envPrefix = "$env:"

func secretFromEnv(s string) (string, error) {
	if !strings.HasPrefix(s, envPrefix) {
		return s, nil
	}
	envvar := strings.TrimPrefix(s, envPrefix)
	secret, ok := os.LookupEnv(envvar)
	if !ok {
		return "", fmt.Errorf("environment variable %q is not set", envvar)
	}
	return secret, nil
}
