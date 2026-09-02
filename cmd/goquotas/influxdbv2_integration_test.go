package main

import (
	"context"
	"os"
	"testing"
	"time"

	"github.com/isilon/powerscale_data_insights/internal/backend"
	"github.com/isilon/powerscale_data_insights/internal/config"
)

// TestInfluxDBv2Integration is opt-in because it requires a live InfluxDB v2
// bucket. It verifies that quota point field types are accepted by the real
// write API, complementing the always-on conversion tests.
func TestInfluxDBv2Integration(t *testing.T) {
	if os.Getenv("PDI_INFLUXDBV2_INTEGRATION") == "" {
		t.Skip("set PDI_INFLUXDBV2_INTEGRATION to run against InfluxDB v2")
	}
	token := os.Getenv("PDI_INFLUXDBV2_TOKEN")
	if token == "" {
		t.Fatal("PDI_INFLUXDBV2_TOKEN is required")
	}

	writer, err := backend.NewInfluxDBv2(context.Background(), "integration-cluster", config.InfluxDBv2Config{
		Host:   envOrDefault("PDI_INFLUXDBV2_HOST", "127.0.0.1"),
		Port:   envOrDefault("PDI_INFLUXDBV2_PORT", "8086"),
		Org:    envOrDefault("PDI_INFLUXDBV2_ORG", "pdi_test"),
		Bucket: envOrDefault("PDI_INFLUXDBV2_BUCKET", "pdi_quota_test"),
		Token:  token,
	})
	if err != nil {
		t.Fatal(err)
	}

	point := quotaToPoint("integration-cluster", quota{
		ID: "influxdbv2-integration", Type: quotaTypeDirectory,
		Path: "/ifs/influxdbv2-integration", Ready: true,
		ThresholdsOn: "fslogicalsize",
		Usage: quotaUsage{
			FSLogical: pointer(uint64(2 << 20)), FSLogicalReady: pointer(true),
			Inodes: pointer(uint64(2)), InodesReady: pointer(true),
		},
		Thresholds: quotaThresholds{Hard: pointer(uint64(4 << 20))},
	}, time.Now())
	if err := writer.WritePoints(context.Background(), []backend.Point{point}); err != nil {
		t.Fatal(err)
	}
}

func envOrDefault(name, fallback string) string {
	if value := os.Getenv(name); value != "" {
		return value
	}
	return fallback
}
