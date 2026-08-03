package main

import (
	"context"
	"math"
	"testing"
	"time"

	"github.com/isilon/powerscale_data_insights/internal/backend"
	sharedconfig "github.com/isilon/powerscale_data_insights/internal/config"
)

func TestPrometheusExpiryMultiplier(t *testing.T) {
	valid := 3.5
	zero := 0.0
	nan := math.NaN()
	tests := []struct {
		name       string
		configured *float64
		want       float64
	}{
		{name: "default", want: sharedconfig.DefaultPromExpiryMultiplier},
		{name: "configured", configured: &valid, want: valid},
		{name: "below minimum", configured: &zero, want: 1},
		{name: "not a number", configured: &nan, want: 1},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			if got := prometheusExpiryMultiplier(test.configured); got != test.want {
				t.Errorf("prometheusExpiryMultiplier() = %v, want %v", got, test.want)
			}
		})
	}
}

func TestPrometheusWritePointsAppliesExpiryMultiplier(t *testing.T) {
	sink := &PrometheusSink{
		metricMap: map[string]*statDetail{
			"node.test.stat": {
				valid:       true,
				description: "test stat",
				updateIntvl: 10,
			},
		},
		expiryMultiplier: 2,
		fam:              make(map[string]*MetricFamily),
	}
	point := backend.Point{
		Name:   "node.test.stat",
		Time:   time.Now().Unix(),
		Fields: []backend.Fields{{"value": 1.0}},
		Tags:   []backend.Tags{{"node": "1"}},
	}

	before := time.Now().Add(20 * time.Second)
	if err := sink.WritePoints(context.Background(), []backend.Point{point}); err != nil {
		t.Fatalf("WritePoints returned an error: %v", err)
	}
	after := time.Now().Add(20 * time.Second)

	var sample *Sample
	for _, family := range sink.fam {
		for _, candidate := range family.Samples {
			sample = candidate
		}
	}
	if sample == nil {
		t.Fatal("WritePoints did not create a sample")
	}
	if sample.Expiration.Before(before) || sample.Expiration.After(after) {
		t.Errorf("sample expiration = %v, want between %v and %v", sample.Expiration, before, after)
	}
}
