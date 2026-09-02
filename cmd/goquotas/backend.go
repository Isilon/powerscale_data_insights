package main

import (
	"strconv"
	"time"

	"github.com/isilon/powerscale_data_insights/internal/backend"
)

const quotaMeasurement = "quota"

func boolString(v bool) string {
	return strconv.FormatBool(v)
}

func readyValue(fields backend.Fields, name string, value *uint64, ready *bool) {
	if value != nil && ready != nil && *ready {
		fields[name] = float64(*value)
	}
}

func addThreshold(fields backend.Fields, name string, threshold *uint64, usage *uint64) {
	if threshold == nil {
		return
	}
	fields[name+"_bytes"] = float64(*threshold)
	if usage != nil && *threshold > 0 {
		fields[name+"_utilization_ratio"] = float64(*usage) / float64(*threshold)
	}
}

func selectedUsage(q quota) *uint64 {
	switch q.ThresholdsOn {
	case "applogicalsize":
		if q.Usage.AppLogicalReady != nil && *q.Usage.AppLogicalReady {
			return q.Usage.AppLogical
		}
	case "physicalsize":
		if q.Usage.PhysicalReady != nil && *q.Usage.PhysicalReady {
			return q.Usage.Physical
		}
	default: // fslogicalsize is the OneFS default, including older responses.
		if q.Usage.FSLogicalReady != nil && *q.Usage.FSLogicalReady {
			return q.Usage.FSLogical
		}
	}
	return nil
}

func quotaTags(clusterName string, q quota) backend.Tags {
	tags := backend.Tags{
		"cluster":           clusterName,
		"quota_id":          q.ID,
		"quota_type":        q.Type,
		"path":              q.Path,
		"thresholds_on":     q.ThresholdsOn,
		"include_snapshots": boolString(q.IncludeSnapshots),
	}
	if q.Linked != nil {
		tags["linked"] = boolString(*q.Linked)
	} else {
		tags["linked"] = ""
	}
	if q.Persona != nil {
		tags["persona_id"] = q.Persona.ID
		if q.Persona.Name != nil {
			tags["persona_name"] = *q.Persona.Name
		}
		if q.Persona.Type != nil {
			tags["persona_type"] = *q.Persona.Type
		}
	}
	return tags
}

func quotaToPoint(clusterName string, q quota, timestamp time.Time) backend.Point {
	tags := quotaTags(clusterName, q)
	fields := backend.Fields{
		"container": q.Container,
		"enforced":  q.Enforced,
		"present":   true,
		"ready":     q.Ready,
	}
	if q.Linked != nil {
		fields["linked"] = *q.Linked
	}
	if q.EfficiencyRatio != nil {
		fields["efficiency_ratio"] = *q.EfficiencyRatio
	}
	if q.ReductionRatio != nil {
		fields["reduction_ratio"] = *q.ReductionRatio
	}

	readyValue(fields, "usage_applogical_bytes", q.Usage.AppLogical, q.Usage.AppLogicalReady)
	readyValue(fields, "usage_fslogical_bytes", q.Usage.FSLogical, q.Usage.FSLogicalReady)
	readyValue(fields, "usage_fsphysical_bytes", q.Usage.FSPhysical, q.Usage.FSPhysicalReady)
	readyValue(fields, "usage_inodes", q.Usage.Inodes, q.Usage.InodesReady)
	readyValue(fields, "usage_physical_bytes", q.Usage.Physical, q.Usage.PhysicalReady)
	readyValue(fields, "usage_physical_data_bytes", q.Usage.PhysicalData, q.Usage.PhysicalDataReady)
	readyValue(fields, "usage_physical_protection_bytes", q.Usage.PhysicalProtection, q.Usage.PhysicalProtectionReady)
	readyValue(fields, "usage_shadow_refs", q.Usage.ShadowRefs, q.Usage.ShadowRefsReady)

	usage := selectedUsage(q)
	if usage != nil {
		fields["usage_bytes"] = float64(*usage)
	}
	addThreshold(fields, "advisory", q.Thresholds.Advisory, usage)
	addThreshold(fields, "soft", q.Thresholds.Soft, usage)
	addThreshold(fields, "hard", q.Thresholds.Hard, usage)

	optionalBool(fields, "advisory_exceeded", q.Thresholds.AdvisoryExceeded)
	optionalBool(fields, "soft_exceeded", q.Thresholds.SoftExceeded)
	optionalBool(fields, "hard_exceeded", q.Thresholds.HardExceeded)
	optionalInt64(fields, "advisory_last_exceeded_timestamp_seconds", q.Thresholds.AdvisoryLastExceeded)
	optionalInt64(fields, "soft_last_exceeded_timestamp_seconds", q.Thresholds.SoftLastExceeded)
	optionalInt64(fields, "hard_last_exceeded_timestamp_seconds", q.Thresholds.HardLastExceeded)
	optionalInt64(fields, "soft_grace_seconds", q.Thresholds.SoftGrace)
	optionalFloat(fields, "advisory_threshold_percent", q.Thresholds.PercentAdvisory)
	optionalFloat(fields, "soft_threshold_percent", q.Thresholds.PercentSoft)

	return backend.Point{
		Name:   quotaMeasurement,
		Time:   timestamp.Unix(),
		Fields: []backend.Fields{fields},
		Tags:   []backend.Tags{tags},
	}
}

func optionalBool(fields backend.Fields, name string, value *bool) {
	if value != nil {
		fields[name] = *value
	}
}

func optionalInt64(fields backend.Fields, name string, value *int64) {
	if value != nil {
		fields[name] = *value
	}
}

func optionalFloat(fields backend.Fields, name string, value *float64) {
	if value != nil {
		fields[name] = *value
	}
}

func quotasToPoints(clusterName string, quotas []quota, timestamp time.Time) []backend.Point {
	points := make([]backend.Point, 0, len(quotas))
	for _, q := range quotas {
		points = append(points, quotaToPoint(clusterName, q, timestamp))
	}
	return points
}

func quotaDeletionPoint(clusterName string, q quota, timestamp time.Time) backend.Point {
	point := quotaToPoint(clusterName, q, timestamp)
	point.Fields = []backend.Fields{{"present": false}}
	return point
}
