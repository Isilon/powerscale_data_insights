package main

import (
	"fmt"
	"strings"
	"testing"
)

// Tests for parseStatResult

func TestParseStatResult_Valid(t *testing.T) {
	data := []byte(`{"stats":[{"devid":0,"key":"cluster.net.ext.bytes.in.rate","error_code":0,"error":"","time":1700000000,"value":12345.6}]}`)
	results, err := parseStatResult(data)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(results) != 1 {
		t.Fatalf("expected 1 result, got %d", len(results))
	}
	if results[0].Key != "cluster.net.ext.bytes.in.rate" {
		t.Errorf("expected key 'cluster.net.ext.bytes.in.rate', got %q", results[0].Key)
	}
	if results[0].Devid != 0 {
		t.Errorf("expected devid 0, got %d", results[0].Devid)
	}
}

func TestParseStatResult_MultipleStats(t *testing.T) {
	data := []byte(`{"stats":[{"devid":0,"key":"stat.one","error_code":0,"error":"","time":1700000000,"value":1.0},{"devid":1,"key":"stat.two","error_code":0,"error":"","time":1700000000,"value":2.0}]}`)
	results, err := parseStatResult(data)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(results) != 2 {
		t.Fatalf("expected 2 results, got %d", len(results))
	}
}

func TestParseStatResult_EmptyStats(t *testing.T) {
	data := []byte(`{"stats":[]}`)
	results, err := parseStatResult(data)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(results) != 0 {
		t.Errorf("expected 0 results, got %d", len(results))
	}
}

func TestParseStatResult_ErrorEnvelope(t *testing.T) {
	// The API returns an array of errors (not a stats object) when auth fails
	data := []byte(`[{"code":"AEC_FORBIDDEN","message":"Access denied"}]`)
	_, err := parseStatResult(data)
	if err == nil {
		t.Fatalf("expected error, got none")
	}
	if !strings.Contains(err.Error(), "AEC_FORBIDDEN") {
		t.Errorf("expected error to mention 'AEC_FORBIDDEN', got: %v", err)
	}
}

func TestParseStatResult_InvalidJSON(t *testing.T) {
	_, err := parseStatResult([]byte(`not json`))
	if err == nil {
		t.Fatalf("expected error for invalid JSON, got none")
	}
}
// Tests for parseStatInfo

// buildStatInfoJSON constructs a minimal valid stat info JSON response
func buildStatInfoJSON(description, units, scope, datatype, aggType string, interval float64) []byte {
	return fmt.Appendf(nil, `{
		"keys": [{
			"description": %q,
			"units": %q,
			"scope": %q,
			"type": %q,
			"aggregation_type": %q,
			"policies": [
				{"persistent": true, "interval": 300.0},
				{"persistent": false, "interval": %g}
			]
		}]
	}`, description, units, scope, datatype, aggType, interval)
}

func TestParseStatInfo_Valid(t *testing.T) {
	data := buildStatInfoJSON("CPU usage", "percent", "node", "float", "avg", 30.0)
	detail, err := parseStatInfo(data)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !detail.valid {
		t.Errorf("expected valid=true")
	}
	if detail.description != "CPU usage" {
		t.Errorf("expected description 'CPU usage', got %q", detail.description)
	}
	if detail.units != "percent" {
		t.Errorf("expected units 'percent', got %q", detail.units)
	}
	if detail.scope != "node" {
		t.Errorf("expected scope 'node', got %q", detail.scope)
	}
	if detail.datatype != "float" {
		t.Errorf("expected datatype 'float', got %q", detail.datatype)
	}
	if detail.aggType != "avg" {
		t.Errorf("expected aggType 'avg', got %q", detail.aggType)
	}
	if detail.updateIntvl != 30.0 {
		t.Errorf("expected updateIntvl 30.0, got %v", detail.updateIntvl)
	}
}

func TestParseStatInfo_NoPolicies(t *testing.T) {
	data := []byte(`{
		"keys": [{
			"description": "some stat",
			"units": "ops/s",
			"scope": "cluster",
			"type": "float",
			"aggregation_type": "sum",
			"policies": null
		}]
	}`)
	detail, err := parseStatInfo(data)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if detail.updateIntvl != 0.0 {
		t.Errorf("expected updateIntvl 0.0 for no policies, got %v", detail.updateIntvl)
	}
	if !detail.valid {
		t.Errorf("expected valid=true")
	}
}

func TestParseStatInfo_APIError(t *testing.T) {
	data := []byte(`{"errors":[{"code":"AEC_NOT_FOUND","message":"Stat not found"}]}`)
	_, err := parseStatInfo(data)
	if err == nil {
		t.Fatalf("expected error, got none")
	}
	if !strings.Contains(err.Error(), "AEC_NOT_FOUND") {
		t.Errorf("expected error to mention 'AEC_NOT_FOUND', got: %v", err)
	}
}

func TestParseStatInfo_InvalidJSON(t *testing.T) {
	_, err := parseStatInfo([]byte(`not json`))
	if err == nil {
		t.Fatalf("expected error for invalid JSON, got none")
	}
}

func TestParseStatInfo_MissingKeysField(t *testing.T) {
	data := []byte(`{"something_else": 42}`)
	_, err := parseStatInfo(data)
	if err == nil {
		t.Fatalf("expected error for missing 'keys' field, got none")
	}
}
