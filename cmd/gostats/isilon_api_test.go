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

// Tests for the transient per-stat retry helpers

func TestIsTransientStatError(t *testing.T) {
	transient := []int{StatErrorStale, StatErrorConnTimeout, StatErrorTimeout, StatErrorNoHistory, StatErrorSystem}
	for _, code := range transient {
		if !isTransientStatError(code) {
			t.Errorf("expected code %d to be transient", code)
		}
	}
	permanent := []int{StatErrorNone, StatErrorNotPresent, StatErrorNotImplemented, StatErrorDegraded, StatErrorNotConfigured, StatErrorNoData}
	for _, code := range permanent {
		if isTransientStatError(code) {
			t.Errorf("expected code %d to be non-transient", code)
		}
	}
}

func TestTransientFailedKeys(t *testing.T) {
	results := []StatResult{
		{Key: "a", Devid: 1, ErrorCode: StatErrorNone},
		{Key: "a", Devid: 2, ErrorCode: StatErrorTimeout}, // key a failed on one node
		{Key: "b", Devid: 1, ErrorCode: StatErrorNone},
		{Key: "c", Devid: 1, ErrorCode: StatErrorStale},
		{Key: "d", Devid: 1, ErrorCode: StatErrorNotPresent}, // permanent, not retried
	}
	failed := transientFailedKeys(results)
	if !failed.Contains("a") || !failed.Contains("c") {
		t.Errorf("expected keys a and c to be flagged, got %v", failed.ToSlice())
	}
	if failed.Contains("b") || failed.Contains("d") {
		t.Errorf("did not expect keys b or d to be flagged, got %v", failed.ToSlice())
	}
}

func TestMergeRetriedResults_RecoveryAndPersistentFailure(t *testing.T) {
	// Initial: key a failed on node 2, key c failed on node 1.
	results := []StatResult{
		{Key: "a", Devid: 1, ErrorCode: StatErrorNone, Value: 1.0},
		{Key: "a", Devid: 2, ErrorCode: StatErrorTimeout},
		{Key: "c", Devid: 1, ErrorCode: StatErrorTimeout},
	}
	// Retry: a/2 recovers, c/1 still times out.
	retried := []StatResult{
		{Key: "a", Devid: 2, ErrorCode: StatErrorNone, Value: 2.0},
		{Key: "c", Devid: 1, ErrorCode: StatErrorTimeout},
	}
	merged, failed := mergeRetriedResults(results, retried)

	// a/2 should now carry the recovered value and no error.
	var a2 *StatResult
	for i := range merged {
		if merged[i].Key == "a" && merged[i].Devid == 2 {
			a2 = &merged[i]
		}
	}
	if a2 == nil || a2.ErrorCode != StatErrorNone || a2.Value != 2.0 {
		t.Errorf("expected a/2 to recover to value 2.0 with no error, got %+v", a2)
	}
	// a/1 good data must be untouched.
	for _, r := range merged {
		if r.Key == "a" && r.Devid == 1 && r.Value != 1.0 {
			t.Errorf("good data a/1 was clobbered: %+v", r)
		}
	}
	// c still failing.
	if !failed.Contains("c") {
		t.Errorf("expected c to still be failing, got %v", failed.ToSlice())
	}
	if failed.Contains("a") {
		t.Errorf("expected a to have recovered, got %v", failed.ToSlice())
	}
}

func TestMergeRetriedResults_NoClobberGoodData(t *testing.T) {
	// A good value should never be overwritten even if a retry returns a worse
	// (transient) result for the same (key, devid).
	results := []StatResult{
		{Key: "a", Devid: 1, ErrorCode: StatErrorNone, Value: 42.0},
	}
	retried := []StatResult{
		{Key: "a", Devid: 1, ErrorCode: StatErrorTimeout},
	}
	merged, failed := mergeRetriedResults(results, retried)
	if len(merged) != 1 || merged[0].ErrorCode != StatErrorNone || merged[0].Value != 42.0 {
		t.Errorf("good data must not be clobbered, got %+v", merged)
	}
	if failed.Cardinality() != 0 {
		t.Errorf("expected no failed keys, got %v", failed.ToSlice())
	}
}
