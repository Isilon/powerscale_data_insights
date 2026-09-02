package main

import (
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

func writeTestConfig(t *testing.T, global string) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "goquotas.toml")
	contents := "[global]\nversion = \"v0.1\"\n" + global + `
[[cluster]]
hostname = "cluster.example.com"
username = "reader"
password = "secret"
`
	if err := os.WriteFile(path, []byte(contents), 0o600); err != nil {
		t.Fatal(err)
	}
	return path
}

func TestReadConfigDefaults(t *testing.T) {
	conf, err := readConfig(writeTestConfig(t, ""))
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(conf.Global.QuotaTypes, defaultQuotaTypes) {
		t.Fatalf("quota types = %#v, want %#v", conf.Global.QuotaTypes, defaultQuotaTypes)
	}
	if conf.Global.collectionDuration != defaultCollectionInterval {
		t.Fatalf("collection duration = %s", conf.Global.collectionDuration)
	}
	if conf.Global.PageLimit != defaultPageLimit || conf.Global.MaxQuotas != defaultMaxQuotas {
		t.Fatalf("unexpected limits: page=%d max=%d", conf.Global.PageLimit, conf.Global.MaxQuotas)
	}
	if conf.Global.Processor != influxPluginName {
		t.Fatalf("processor = %q", conf.Global.Processor)
	}
}

func TestReadConfigOptInQuotaTypes(t *testing.T) {
	conf, err := readConfig(writeTestConfig(t, `quota_types = ["directory", "user", "group"]
collection_interval = "15m"
resolve_names = true
`))
	if err != nil {
		t.Fatal(err)
	}
	want := []string{"directory", "user", "group"}
	if !reflect.DeepEqual(conf.Global.QuotaTypes, want) {
		t.Fatalf("quota types = %#v, want %#v", conf.Global.QuotaTypes, want)
	}
	if conf.Global.collectionDuration.String() != "15m0s" || !conf.Global.ResolveNames {
		t.Fatalf("unexpected opt-in config: %#v", conf.Global)
	}
}

func TestReadConfigRejectsUnsafeValues(t *testing.T) {
	tests := []struct {
		name    string
		global  string
		wantErr string
	}{
		{"invalid type", `quota_types = ["directory", "bogus"]`, "unsupported quota type"},
		{"duplicate type", `quota_types = ["directory", "directory"]`, "duplicate quota type"},
		{"empty types", `quota_types = []`, "at least one"},
		{"bad duration", `collection_interval = "hourly"`, "positive Go duration"},
		{"zero limit", `max_quotas = 0`, "max_quotas"},
		{"bad processor", `stats_processor = "unknown"`, "stats_processor"},
		{"zero retry interval", `stats_processor_retry_interval = 0`, "retry_interval"},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			_, err := readConfig(writeTestConfig(t, test.global+"\n"))
			if err == nil || !strings.Contains(err.Error(), test.wantErr) {
				t.Fatalf("error = %v, want substring %q", err, test.wantErr)
			}
		})
	}
}
