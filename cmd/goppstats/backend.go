package main

import (
	"context"
	"fmt"
	"log/slog"
	"strconv"
)

// the ppFixedFields and workloadTypes definitions are a bit ugly because there are no array constants in Go

// names of the statistics that each partitioned performance metric collects
const (
	fBytesIn  = "bytes_in"
	fBytesOut = "bytes_out"
	fReads    = "reads"
	fWrites   = "writes"
	fOps      = "ops"
	fL2       = "l2"
	fL3       = "l3"
	fCPU      = "cpu"
	fLatRead  = "latency_read"
	fLatWrite = "latency_write"
	fLatOther = "latency_other"
)

// ppFixedFields contains the names of the performance statistics that partitioned performance collects
var ppFixedFields = []string{fBytesIn, fBytesOut, fReads, fWrites, fOps, fL2, fL3, fCPU, fLatRead, fLatWrite, fLatOther}

// workload types: Additional Excluded Overaccounted System Unknown
const (
	wAdditional    = "Additional"
	wExcluded      = "Excluded"
	wOveraccounted = "Overaccounted"
	wSystem        = "System"
	wUnknown       = "Unknown"
	wPinned        = "Pinned"
)

// workloadTypes contains the names of the 5 "overflow" buckets for any given dataset
var workloadTypes = []string{wAdditional, wExcluded, wOveraccounted, wSystem, wUnknown}

// isValidWorkloadType takes a workload_type string and validates that it is one of the 5 "overflow" buckets
func isValidWorkloadType(t string) bool {
	switch t {
	case wAdditional, wExcluded, wOveraccounted, wSystem, wUnknown:
		return true
	}
	return false
}

// exportMap holds a map of NFS exports ids to their corresponding NFS exports paths
type exportMap struct {
	enabled  bool
	pathByID map[int]string
}

// newExportMap creates a map of NFS export ids to their corresponding NFS exports paths
func newExportMap(enabled bool) exportMap {
	m := new(exportMap)
	m.enabled = enabled
	if enabled {
		m.pathByID = make(map[int]string)
	}
	return *m
}

// types for the decoded fields and tags
type ptFields map[string]any
type ptTags map[string]string

// fieldsForPPStat creates and populates the fixed/required fields for
// every partitioned performance stat result
func fieldsForPPStat(ppstat PPStatResult) ptFields {
	fields := make(ptFields)

	// Required fields
	fields[fBytesIn] = ppstat.BytesIn
	fields[fBytesOut] = ppstat.BytesOut
	fields[fReads] = ppstat.Reads
	fields[fWrites] = ppstat.Writes
	fields[fOps] = ppstat.Ops
	fields[fL2] = ppstat.L2
	fields[fL3] = ppstat.L3
	fields[fCPU] = ppstat.CPU
	fields[fLatRead] = ppstat.LatencyRead
	fields[fLatWrite] = ppstat.LatencyWrite
	fields[fLatOther] = ppstat.LatencyOther

	return fields
}

// tagsForPPStat dissects the PPStatResult and converts it to the tags that
// match the original workload definition i.e.
// export_id groupname local_address path protocol remote_address share_name username zone_name
// squash some of the fields e.g. Username vs UserID vs UserSID
func tagsForPPStat(ctx context.Context, ppstat PPStatResult, cluster *Cluster, exports exportMap) ptTags {
	tags := make(ptTags)

	// NFS export id
	if ppstat.ExportID != nil {
		id := *ppstat.ExportID
		tags["export_id"] = strconv.Itoa(id)
		if exports.enabled {
			path, found := exports.pathByID[id]
			if !found {
				var err error
				path, err = cluster.GetExportPathByID(ctx, id)
				if err != nil {
					log.Error("failed to lookup export id", slog.Int("export_id", id), slog.Any("error", err))
					path = "unknown (lookup failed)"
				}
				exports.pathByID[id] = path
			}
			tags["export_path"] = path
		}
	}

	// associated group identity
	if ppstat.GroupName != nil {
		tags["groupname"] = fmt.Sprintf("GID:%s", *ppstat.GroupName)
	} else if ppstat.GroupID != nil {
		tags["groupname"] = fmt.Sprintf("GID:%d", *ppstat.GroupID)
	} else if ppstat.GroupSid != nil {
		tags["groupname"] = fmt.Sprintf("SID:%s", *ppstat.GroupSid)
	}

	// local network name/address
	if ppstat.LocalName != nil {
		tags["local_address"] = *ppstat.LocalName
	} else if ppstat.LocalAddress != nil {
		tags["local_address"] = *ppstat.LocalAddress
	}

	// pathname filter
	if ppstat.Path != nil {
		tags["path"] = *ppstat.Path
	}

	// protocol
	if ppstat.Protocol != nil {
		tags["protocol"] = *ppstat.Protocol
	}

	// remote network name/address
	if ppstat.RemoteName != nil {
		tags["remote_address"] = *ppstat.RemoteName
	} else if ppstat.RemoteAddress != nil {
		tags["remote_address"] = *ppstat.RemoteAddress
	}

	// SMB share name
	if ppstat.ShareName != nil {
		tags["share_name"] = *ppstat.ShareName
	}

	// associated user identity
	if ppstat.Username != nil {
		tags["username"] = *ppstat.Username
	} else if ppstat.UserID != nil {
		tags["username"] = fmt.Sprintf("UID:%d", *ppstat.UserID)
	} else if ppstat.UserSid != nil {
		tags["username"] = fmt.Sprintf("SID:%s", *ppstat.UserSid)
	}

	// OneFS access zone
	if ppstat.ZoneName != nil {
		tags["zone_name"] = *ppstat.ZoneName
	} else if ppstat.ZoneID != nil {
		tags["zone_name"] = fmt.Sprintf("zone:%d", *ppstat.ZoneID)
	}

	// If non-Null, this will be one of the five extra buckets:
	// Additional, Excluded, Overaccounted, System, Unknown
	if ppstat.WorkloadType != nil {
		tags["workload_type"] = *ppstat.WorkloadType
	}

	// Other stuff

	// Only for the System dataset (dataset 0) and contains the process/service name
	if ppstat.SystemName != nil {
		tags["system_name"] = *ppstat.SystemName
	}

	// Only for the System dataset (dataset 0) Job-engine job tag
	if ppstat.JobType != nil {
		tags["job_type"] = *ppstat.JobType
	}

	if ppstat.DomainID != nil {
		tags["domain_id"] = *ppstat.DomainID
	}

	// performance workload id
	if ppstat.WorkloadID != nil {
		tags["workload_id"] = strconv.Itoa(*ppstat.WorkloadID)
	}

	return tags
}
