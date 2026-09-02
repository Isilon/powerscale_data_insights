package main

import (
	"context"
	"testing"
	"time"

	"github.com/isilon/powerscale_data_insights/internal/backend"
	"github.com/prometheus/client_golang/prometheus"
)

func testPrometheusSink(t *testing.T) *PrometheusSink {
	t.Helper()
	sink := newPrometheusSink()
	sink.clusterName = "cluster-a"
	sink.registry = prometheus.NewRegistry()
	if err := sink.registry.Register(sink); err != nil {
		t.Fatal(err)
	}
	return sink
}

func TestPrometheusSnapshotReplacement(t *testing.T) {
	sink := testPrometheusSink(t)
	point := quotaToPoint("cluster-a", quota{
		ID: "id", Type: quotaTypeDirectory, Path: "/ifs/data", Ready: true,
		Usage: quotaUsage{FSLogical: pointer(uint64(50)), FSLogicalReady: pointer(true)},
	}, time.Unix(123, 0))
	if err := sink.WritePoints(context.Background(), []backend.Point{point}); err != nil {
		t.Fatal(err)
	}
	if sink.snapshot.count != 1 || sink.snapshot.series == 0 {
		t.Fatalf("unexpected snapshot: %#v", sink.snapshot)
	}
	if _, err := sink.registry.Gather(); err != nil {
		t.Fatalf("gather populated snapshot: %v", err)
	}
	if err := sink.WritePoints(context.Background(), nil); err != nil {
		t.Fatal(err)
	}
	if sink.snapshot.count != 0 || sink.snapshot.series != 0 {
		t.Fatalf("old quota series were not removed: %#v", sink.snapshot)
	}
}

func TestPrometheusFailedReplacementKeepsSnapshot(t *testing.T) {
	sink := testPrometheusSink(t)
	valid := backend.Point{
		Name: quotaMeasurement, Time: 123,
		Tags:   []backend.Tags{{"cluster": "cluster-a", "quota_id": "id"}},
		Fields: []backend.Fields{{"present": true}},
	}
	if err := sink.WritePoints(context.Background(), []backend.Point{valid}); err != nil {
		t.Fatal(err)
	}
	oldSeries := sink.snapshot.series
	invalid := backend.Point{
		Name: quotaMeasurement, Time: 124,
		Tags:   []backend.Tags{{"cluster": "cluster-a", "quota_id": "id"}},
		Fields: []backend.Fields{{"bad": "not numeric"}},
	}
	if err := sink.WritePoints(context.Background(), []backend.Point{invalid}); err == nil {
		t.Fatal("expected unsupported value error")
	}
	if sink.snapshot.series != oldSeries {
		t.Fatalf("failed write replaced snapshot: got %d series, want %d", sink.snapshot.series, oldSeries)
	}
}

func TestNumericValue(t *testing.T) {
	if got, ok := numericValue(true); !ok || got != 1 {
		t.Fatalf("true = %v, %v", got, ok)
	}
	if _, ok := numericValue("bad"); ok {
		t.Fatal("string unexpectedly accepted")
	}
}
