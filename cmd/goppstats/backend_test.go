package main

import (
	"context"
	"strconv"
	"testing"
)

func TestIsValidWorkloadType(t *testing.T) {
	valid := []string{wAdditional, wExcluded, wOveraccounted, wSystem, wUnknown}
	for _, wt := range valid {
		if !isValidWorkloadType(wt) {
			t.Errorf("isValidWorkloadType(%q) = false, want true", wt)
		}
	}
	// wPinned is intentionally NOT a valid overflow bucket
	invalid := []string{wPinned, "", "bogus", "system", "SYSTEM"}
	for _, wt := range invalid {
		if isValidWorkloadType(wt) {
			t.Errorf("isValidWorkloadType(%q) = true, want false", wt)
		}
	}
}

func TestNewExportMap(t *testing.T) {
	t.Run("disabled", func(t *testing.T) {
		m := newExportMap(false)
		if m.enabled {
			t.Error("expected disabled export map")
		}
		if m.pathByID != nil {
			t.Error("expected nil pathByID for disabled map")
		}
	})
	t.Run("enabled", func(t *testing.T) {
		m := newExportMap(true)
		if !m.enabled {
			t.Error("expected enabled export map")
		}
		if m.pathByID == nil {
			t.Error("expected non-nil pathByID for enabled map")
		}
	})
}

func TestFieldsForPPStat(t *testing.T) {
	stat := PPStatResult{
		BytesIn:      1,
		BytesOut:     2,
		Reads:        3,
		Writes:       4,
		Ops:          5,
		L2:           6,
		L3:           7,
		CPU:          8,
		LatencyRead:  9,
		LatencyWrite: 10,
		LatencyOther: 11,
	}
	fields := fieldsForPPStat(stat)

	expected := map[string]float64{
		fBytesIn:  1, fBytesOut: 2, fReads: 3, fWrites: 4, fOps: 5,
		fL2: 6, fL3: 7, fCPU: 8, fLatRead: 9, fLatWrite: 10, fLatOther: 11,
	}
	for k, want := range expected {
		got, ok := fields[k].(float64)
		if !ok {
			t.Errorf("fields[%q] is not float64", k)
			continue
		}
		if got != want {
			t.Errorf("fields[%q] = %v, want %v", k, got, want)
		}
	}
	// All ppFixedFields must be present
	for _, name := range ppFixedFields {
		if _, ok := fields[name]; !ok {
			t.Errorf("fields[%q] is missing", name)
		}
	}
}

func strPtr(s string) *string { return &s }
func intPtr(i int) *int       { return &i }

func TestTagsForPPStat(t *testing.T) {
	ctx := context.Background()
	noExports := newExportMap(false)

	t.Run("empty stat yields empty tags", func(t *testing.T) {
		tags := tagsForPPStat(ctx, PPStatResult{}, nil, noExports)
		if len(tags) != 0 {
			t.Errorf("expected empty tags, got %v", tags)
		}
	})

	t.Run("username string", func(t *testing.T) {
		s := PPStatResult{Username: strPtr("alice")}
		tags := tagsForPPStat(ctx, s, nil, noExports)
		if tags["username"] != "alice" {
			t.Errorf("username tag = %q, want %q", tags["username"], "alice")
		}
	})

	t.Run("username from user_id", func(t *testing.T) {
		s := PPStatResult{UserID: intPtr(1001)}
		tags := tagsForPPStat(ctx, s, nil, noExports)
		want := "UID:1001"
		if tags["username"] != want {
			t.Errorf("username tag = %q, want %q", tags["username"], want)
		}
	})

	t.Run("username from user_sid", func(t *testing.T) {
		s := PPStatResult{UserSid: strPtr("S-1-5-21-1")}
		tags := tagsForPPStat(ctx, s, nil, noExports)
		want := "SID:S-1-5-21-1"
		if tags["username"] != want {
			t.Errorf("username tag = %q, want %q", tags["username"], want)
		}
	})

	t.Run("groupname string", func(t *testing.T) {
		s := PPStatResult{GroupName: strPtr("staff")}
		tags := tagsForPPStat(ctx, s, nil, noExports)
		if tags["groupname"] != "GID:staff" {
			t.Errorf("groupname tag = %q, want GID:staff", tags["groupname"])
		}
	})

	t.Run("groupname from group_id", func(t *testing.T) {
		s := PPStatResult{GroupID: intPtr(20)}
		tags := tagsForPPStat(ctx, s, nil, noExports)
		want := "GID:20"
		if tags["groupname"] != want {
			t.Errorf("groupname tag = %q, want %q", tags["groupname"], want)
		}
	})

	t.Run("export_id without path lookup", func(t *testing.T) {
		s := PPStatResult{ExportID: intPtr(42)}
		tags := tagsForPPStat(ctx, s, nil, noExports)
		if tags["export_id"] != "42" {
			t.Errorf("export_id tag = %q, want %q", tags["export_id"], "42")
		}
		if _, ok := tags["export_path"]; ok {
			t.Error("export_path should not be set when exports are disabled")
		}
	})

	t.Run("local_address from local_name", func(t *testing.T) {
		s := PPStatResult{LocalName: strPtr("node1.local")}
		tags := tagsForPPStat(ctx, s, nil, noExports)
		if tags["local_address"] != "node1.local" {
			t.Errorf("local_address = %q, want %q", tags["local_address"], "node1.local")
		}
	})

	t.Run("local_address fallback to local_address field", func(t *testing.T) {
		s := PPStatResult{LocalAddress: strPtr("192.168.1.1")}
		tags := tagsForPPStat(ctx, s, nil, noExports)
		if tags["local_address"] != "192.168.1.1" {
			t.Errorf("local_address = %q, want %q", tags["local_address"], "192.168.1.1")
		}
	})

	t.Run("zone_name string", func(t *testing.T) {
		s := PPStatResult{ZoneName: strPtr("System")}
		tags := tagsForPPStat(ctx, s, nil, noExports)
		if tags["zone_name"] != "System" {
			t.Errorf("zone_name = %q, want %q", tags["zone_name"], "System")
		}
	})

	t.Run("zone_name from zone_id", func(t *testing.T) {
		s := PPStatResult{ZoneID: intPtr(3)}
		tags := tagsForPPStat(ctx, s, nil, noExports)
		want := "zone:" + strconv.Itoa(3)
		if tags["zone_name"] != want {
			t.Errorf("zone_name = %q, want %q", tags["zone_name"], want)
		}
	})

	t.Run("protocol and share_name", func(t *testing.T) {
		s := PPStatResult{
			Protocol:  strPtr("smb2"),
			ShareName: strPtr("homes"),
		}
		tags := tagsForPPStat(ctx, s, nil, noExports)
		if tags["protocol"] != "smb2" {
			t.Errorf("protocol = %q, want smb2", tags["protocol"])
		}
		if tags["share_name"] != "homes" {
			t.Errorf("share_name = %q, want homes", tags["share_name"])
		}
	})

	t.Run("workload_type and workload_id", func(t *testing.T) {
		s := PPStatResult{
			WorkloadType: strPtr(wSystem),
			WorkloadID:   intPtr(7),
		}
		tags := tagsForPPStat(ctx, s, nil, noExports)
		if tags["workload_type"] != wSystem {
			t.Errorf("workload_type = %q, want %q", tags["workload_type"], wSystem)
		}
		if tags["workload_id"] != "7" {
			t.Errorf("workload_id = %q, want %q", tags["workload_id"], "7")
		}
	})

	t.Run("username preferred over user_id", func(t *testing.T) {
		// If both Username and UserID are set, Username wins
		s := PPStatResult{
			Username: strPtr("bob"),
			UserID:   intPtr(999),
		}
		tags := tagsForPPStat(ctx, s, nil, noExports)
		if tags["username"] != "bob" {
			t.Errorf("username = %q, want bob (Username should take priority over UserID)", tags["username"])
		}
	})
}
