package main

import (
	"testing"
	"time"
)

func pointer[T any](value T) *T { return &value }

func TestQuotaToPointReadinessAndRatios(t *testing.T) {
	q := quota{
		ID: "id", Type: quotaTypeDirectory, Path: "/ifs/data", Ready: true,
		ThresholdsOn: "fslogicalsize",
		Usage: quotaUsage{
			FSLogical: pointer(uint64(50)), FSLogicalReady: pointer(true),
			Physical: pointer(uint64(90)), PhysicalReady: pointer(false),
		},
		Thresholds: quotaThresholds{Hard: pointer(uint64(100))},
	}
	point := quotaToPoint("cluster-a", q, time.Unix(123, 0))
	fields := point.Fields[0]
	if fields["usage_fslogical_bytes"] != float64(50) {
		t.Fatalf("fslogical usage = %#v", fields["usage_fslogical_bytes"])
	}
	if _, ok := fields["usage_physical_bytes"]; ok {
		t.Fatal("not-ready physical usage was emitted")
	}
	if fields["usage_bytes"] != float64(50) {
		t.Fatalf("selected usage = %#v", fields["usage_bytes"])
	}
	if fields["hard_utilization_ratio"] != 0.5 {
		t.Fatalf("hard utilization = %#v", fields["hard_utilization_ratio"])
	}
}

func TestQuotaToPointNullThresholdsAreAbsent(t *testing.T) {
	q := quota{ID: "id", Type: quotaTypeDirectory, Path: "/ifs/data"}
	fields := quotaToPoint("cluster-a", q, time.Unix(123, 0)).Fields[0]
	for _, name := range []string{"hard_bytes", "soft_bytes", "advisory_bytes", "usage_bytes"} {
		if _, ok := fields[name]; ok {
			t.Errorf("unexpected field %q", name)
		}
	}
}

func TestQuotaDeletionPoint(t *testing.T) {
	point := quotaDeletionPoint("cluster-a", quota{ID: "id", Type: quotaTypeDirectory, Path: "/ifs/data"}, time.Unix(123, 0))
	if len(point.Fields[0]) != 1 || point.Fields[0]["present"] != false {
		t.Fatalf("unexpected tombstone fields: %#v", point.Fields[0])
	}
	if point.Tags[0]["quota_id"] != "id" || point.Tags[0]["path"] != "/ifs/data" {
		t.Fatalf("tombstone lost identity: %#v", point.Tags[0])
	}
}

func TestQuotaTagsChangeWhenSeriesIdentityChanges(t *testing.T) {
	original := quota{ID: "id", Type: quotaTypeDirectory, Path: "/ifs/old"}
	renamed := original
	renamed.Path = "/ifs/new"
	if quotaTags("cluster-a", original)["path"] == quotaTags("cluster-a", renamed)["path"] {
		t.Fatal("renamed quota retained the original series identity")
	}
}

func TestQuotaToPointUnusualQuotaFields(t *testing.T) {
	q := quota{
		ID: "linked", Type: quotaTypeDefaultDirectory, Path: "/ifs/projects",
		IncludeSnapshots: true, Linked: pointer(true), ThresholdsOn: "physicalsize",
		Usage: quotaUsage{Physical: pointer(uint64(75)), PhysicalReady: pointer(true)},
		Thresholds: quotaThresholds{
			Hard: pointer(uint64(100)), HardExceeded: pointer(true),
			PercentAdvisory: pointer(80.0), SoftGrace: pointer(int64(3600)),
		},
	}
	point := quotaToPoint("cluster-a", q, time.Unix(123, 0))
	fields := point.Fields[0]
	if fields["usage_bytes"] != float64(75) || fields["hard_exceeded"] != true {
		t.Fatalf("unexpected physical/exceeded fields: %#v", fields)
	}
	if fields["advisory_threshold_percent"] != 80.0 || fields["soft_grace_seconds"] != int64(3600) {
		t.Fatalf("unexpected percent/grace fields: %#v", fields)
	}
	if point.Tags[0]["include_snapshots"] != "true" || point.Tags[0]["linked"] != "true" {
		t.Fatalf("unexpected linked/snapshot tags: %#v", point.Tags[0])
	}
}

func TestQuotaToPointUsesInfluxV1CompatibleNumericTypes(t *testing.T) {
	q := quota{
		ID: "id", Type: quotaTypeDirectory, Path: "/ifs/data",
		ThresholdsOn: "fslogicalsize",
		Usage: quotaUsage{
			FSLogical: pointer(uint64(50)), FSLogicalReady: pointer(true),
			Inodes: pointer(uint64(2)), InodesReady: pointer(true),
		},
		Thresholds: quotaThresholds{Hard: pointer(uint64(100))},
	}
	fields := quotaToPoint("cluster-a", q, time.Unix(123, 0)).Fields[0]
	for _, name := range []string{"usage_bytes", "usage_fslogical_bytes", "usage_inodes", "hard_bytes"} {
		if _, ok := fields[name].(float64); !ok {
			t.Fatalf("field %q has type %T, want float64", name, fields[name])
		}
	}
}

func TestQuotaToPointSupportsEveryQuotaType(t *testing.T) {
	quotaTypes := []string{
		quotaTypeDirectory,
		quotaTypeDefaultDirectory,
		quotaTypeUser,
		quotaTypeDefaultUser,
		quotaTypeGroup,
		quotaTypeDefaultGroup,
	}
	for _, quotaType := range quotaTypes {
		t.Run(quotaType, func(t *testing.T) {
			name := "identity-name"
			personaType := "user"
			point := quotaToPoint("cluster-a", quota{
				ID: "id-" + quotaType, Type: quotaType, Path: "/ifs/data",
				Persona: &quotaPersona{ID: "123", Name: &name, Type: &personaType},
			}, time.Unix(123, 0))
			if point.Tags[0]["quota_type"] != quotaType ||
				point.Tags[0]["persona_id"] != "123" ||
				point.Tags[0]["persona_name"] != name {
				t.Fatalf("unexpected tags: %#v", point.Tags[0])
			}
		})
	}
}
