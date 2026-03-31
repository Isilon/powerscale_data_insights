package main

import (
	"os"
	"testing"
)

// TestMain initializes the global logger before any tests run.
// Many functions in this package use the package-level log variable.
func TestMain(m *testing.M) {
	setupEarlyLogging()
	os.Exit(m.Run())
}

func TestGetDBWriter(t *testing.T) {
	tests := []struct {
		name      string
		processor string
		wantErr   bool
	}{
		{"discard", discardPluginName, false},
		{"influxdb", influxPluginName, false},
		{"influxdbv2", influxV2PluginName, false},
		{"prometheus", promPluginName, false},
		{"unknown", "bogus", true},
		{"empty", "", true},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			w, err := getDBWriter(tt.processor)
			if tt.wantErr {
				if err == nil {
					t.Errorf("getDBWriter(%q) expected error, got nil", tt.processor)
				}
				return
			}
			if err != nil {
				t.Errorf("getDBWriter(%q) unexpected error: %v", tt.processor, err)
			}
			if w == nil {
				t.Errorf("getDBWriter(%q) returned nil writer", tt.processor)
			}
		})
	}
}
