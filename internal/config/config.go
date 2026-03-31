// Package config provides shared configuration primitives and structs
// used by both the gostats and goppstats collectors.
package config

import (
	"fmt"
	"os"
	"strings"
)

// Default configuration values shared by both collectors.
const (
	DefaultMinUpdateInterval     = 30
	DefaultMaxRetries            = 8
	DefaultProcessorMaxRetries   = 8
	DefaultProcessorRetryInterval = 5
	DefaultPreserveCase          = false
)

// InfluxDBConfig defines the InfluxDB v1 settings in the config file.
type InfluxDBConfig struct {
	Host               string `toml:"host"`
	Port               string `toml:"port"`
	Database           string `toml:"database"`
	Authenticated      bool   `toml:"authenticated"`
	Username           string `toml:"username"`
	Password           string `toml:"password"`
	UseSSL             bool   `toml:"use_ssl"`         // connect via https instead of http
	InsecureSkipVerify bool   `toml:"skip_ssl_verify"` // skip TLS certificate verification
}

// InfluxDBv2Config defines the InfluxDB v2 settings in the config file.
type InfluxDBv2Config struct {
	Host               string `toml:"host"`
	Port               string `toml:"port"`
	Org                string `toml:"org"`
	Bucket             string `toml:"bucket"`
	Token              string `toml:"access_token"`
	UseSSL             bool   `toml:"use_ssl"`         // connect via https instead of http
	InsecureSkipVerify bool   `toml:"skip_ssl_verify"` // skip TLS certificate verification
}

// PrometheusConfig defines the Prometheus settings in the config file.
type PrometheusConfig struct {
	Authenticated     bool    `toml:"authenticated"`
	Username          string  `toml:"username"`
	Password          string  `toml:"password"`
	TLSCert           string  `toml:"tls_cert"`
	TLSKey            string  `toml:"tls_key"`
	InstanceLabelName *string `toml:"instance_label_name"`
}

// PromHTTPSDConfig defines the Prometheus HTTP Service Discovery settings.
type PromHTTPSDConfig struct {
	Enabled    bool
	ListenAddr string `toml:"listen_addr"`
	SDport     uint64 `toml:"sd_port"`
}

// ClusterConfig defines the per-cluster settings in the config file.
type ClusterConfig struct {
	Hostname       string  // cluster name/ip; ideally use a SmartConnect name
	Username       string  // account with the appropriate PAPI roles
	Password       string  // password for the account
	AuthType       string  // authentication type: "session" or "basic-auth"
	SSLCheck       bool    `toml:"verify-ssl"` // turn on/off SSL cert checking to handle self-signed certificates
	Disabled       bool    // if set, disable collection for this cluster
	PrometheusPort *uint64 `toml:"prometheus_port"` // If using the Prometheus collector, define the listener port for the metrics handler
	PreserveCase   *bool   `toml:"preserve_case"`   // Overwrite normalization of Cluster Name
}

const envPrefix = "$env:"

// SecretFromEnv checks if the string starts with $env: and if so, looks up
// the rest of the string as an environment variable and returns its value.
// If the env var is not set, an error is returned.
// If the string does not start with $env:, it is returned unchanged.
func SecretFromEnv(s string) (string, error) {
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
