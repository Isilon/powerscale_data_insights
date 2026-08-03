package main

import (
	"os"
	"path/filepath"
	"testing"

	sharedconfig "github.com/isilon/powerscale_data_insights/internal/config"
)

func writeTestConfig(t *testing.T, contents string) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "gostats.toml")
	if err := os.WriteFile(path, []byte(contents), 0o600); err != nil {
		t.Fatalf("write config: %v", err)
	}
	return path
}

func TestReadConfigStatRetryDefaults(t *testing.T) {
	conf, err := readConfig(writeTestConfig(t, `
[global]
version = "v0.40"
`))
	if err != nil {
		t.Fatalf("readConfig returned an error: %v", err)
	}

	if conf.Global.StatTimeout != sharedconfig.DefaultStatTimeout {
		t.Errorf("StatTimeout = %d, want %d", conf.Global.StatTimeout, sharedconfig.DefaultStatTimeout)
	}
	if conf.Global.StatRetries != sharedconfig.DefaultStatRetries {
		t.Errorf("StatRetries = %d, want %d", conf.Global.StatRetries, sharedconfig.DefaultStatRetries)
	}
	if conf.Global.StatRetryIntvl != sharedconfig.DefaultStatRetryInterval {
		t.Errorf("StatRetryIntvl = %d, want %d", conf.Global.StatRetryIntvl, sharedconfig.DefaultStatRetryInterval)
	}
}

func TestReadConfigNormalizesInvalidStatRetryValues(t *testing.T) {
	conf, err := readConfig(writeTestConfig(t, `
[global]
version = "v0.40"
stat_timeout = -1
stat_retries = -2
stat_retry_interval = 0
`))
	if err != nil {
		t.Fatalf("readConfig returned an error: %v", err)
	}

	if conf.Global.StatTimeout != 0 {
		t.Errorf("StatTimeout = %d, want 0", conf.Global.StatTimeout)
	}
	if conf.Global.StatRetries != 0 {
		t.Errorf("StatRetries = %d, want 0", conf.Global.StatRetries)
	}
	if conf.Global.StatRetryIntvl != sharedconfig.DefaultStatRetryInterval {
		t.Errorf("StatRetryIntvl = %d, want %d", conf.Global.StatRetryIntvl, sharedconfig.DefaultStatRetryInterval)
	}
}
