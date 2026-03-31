package main

import (
	"encoding/json"
	"testing"
)

func TestParsePPStatResult(t *testing.T) {
	t.Run("single workload entry", func(t *testing.T) {
		username := "alice"
		protocol := "nfs3"
		input, _ := json.Marshal(PPWorkloadQuery{
			Workloads: []PPStatResult{
				{
					CPU:         1.5,
					Ops:         100,
					Reads:       50,
					Writes:      25,
					BytesIn:     4096,
					BytesOut:    8192,
					L2:          0.1,
					L3:          0.2,
					LatencyRead: 0.3,
					LatencyWrite: 0.4,
					LatencyOther: 0.5,
					Node:        3,
					UnixTime:    1700000000,
					Username:    &username,
					Protocol:    &protocol,
				},
			},
		})
		results, err := parsePPStatResult(input)
		if err != nil {
			t.Fatalf("unexpected error: %v", err)
		}
		if len(results) != 1 {
			t.Fatalf("got %d results, want 1", len(results))
		}
		r := results[0]
		if r.CPU != 1.5 {
			t.Errorf("CPU = %v, want 1.5", r.CPU)
		}
		if r.Node != 3 {
			t.Errorf("Node = %v, want 3", r.Node)
		}
		if r.Username == nil || *r.Username != username {
			t.Errorf("Username = %v, want %q", r.Username, username)
		}
		if r.Protocol == nil || *r.Protocol != protocol {
			t.Errorf("Protocol = %v, want %q", r.Protocol, protocol)
		}
	})

	t.Run("empty workload list", func(t *testing.T) {
		input := []byte(`{"workload":[]}`)
		results, err := parsePPStatResult(input)
		if err != nil {
			t.Fatalf("unexpected error: %v", err)
		}
		if len(results) != 0 {
			t.Errorf("got %d results, want 0", len(results))
		}
	})

	t.Run("null workload field", func(t *testing.T) {
		input := []byte(`{"workload":null}`)
		results, err := parsePPStatResult(input)
		if err != nil {
			t.Fatalf("unexpected error: %v", err)
		}
		if results != nil {
			t.Errorf("got %v, want nil", results)
		}
	})

	t.Run("invalid JSON returns error", func(t *testing.T) {
		_, err := parsePPStatResult([]byte(`not json`))
		if err == nil {
			t.Error("expected error for invalid JSON, got nil")
		}
	})

	t.Run("optional pointer fields default to nil", func(t *testing.T) {
		input := []byte(`{"workload":[{"cpu":0,"ops":0,"reads":0,"writes":0,"bytes_out":0,"bytes_in":0,"l2":0,"l3":0,"latency_read":0,"latency_write":0,"latency_other":0,"node":0,"time":0}]}`)
		results, err := parsePPStatResult(input)
		if err != nil {
			t.Fatalf("unexpected error: %v", err)
		}
		if len(results) != 1 {
			t.Fatalf("got %d results, want 1", len(results))
		}
		r := results[0]
		if r.Username != nil {
			t.Errorf("Username should be nil, got %v", r.Username)
		}
		if r.ExportID != nil {
			t.Errorf("ExportID should be nil, got %v", r.ExportID)
		}
	})
}
