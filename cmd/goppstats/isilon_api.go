package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"

	"github.com/isilon/powerscale_data_insights/internal/api"
)

// Cluster wraps api.Cluster with goppstats-specific API methods.
type Cluster struct {
	api.Cluster
}

// MaxDsID is the maximum dataset ID supported by the API; for OneFS releases
// up to and including 9.12, the API supports the System dataset (0) and up to
// four user-defined datasets.
const MaxDsID = 4

const dsPath = "/platform/10/performance/datasets"
const ppWorkloadPath = "/platform/10/statistics/summary/workload"
const exportPath = "/platform/1/protocols/nfs/exports"

// DsInfoEntry contains metadata info for a single partitioned performance dataset
type DsInfoEntry struct {
	CreationTime  int      `json:"creation_time"`
	FilterCount   int      `json:"filter_count"`
	Filters       []string `json:"filters"`
	ID            int      `json:"id"`
	Metrics       []string `json:"metrics"`
	Name          string   `json:"name"`
	StatKey       string   `json:"statkey"`
	WorkloadCount int      `json:"workload_count"`
}

// DsInfo contains metadata info for the PP data sets
type DsInfo struct {
	Datasets []DsInfoEntry `json:"datasets"`
	Resume   string        `json:"resume"`
	Total    int           `json:"total"`
}

// PPStatResult contains the information returned for a single workload entry
// as returned by the OneFS partitioned performance API.
// Many of the fields are optional and depend on the definition of the data set
type PPStatResult struct {
	// required performance metrics
	CPU          float64 `json:"cpu"`
	Ops          float64 `json:"ops"`
	Reads        float64 `json:"reads"`
	Writes       float64 `json:"writes"`
	BytesOut     float64 `json:"bytes_out"`
	BytesIn      float64 `json:"bytes_in"`
	L2           float64 `json:"l2"`
	L3           float64 `json:"l3"`
	LatencyRead  float64 `json:"latency_read"`
	LatencyWrite float64 `json:"latency_write"`
	LatencyOther float64 `json:"latency_other"`
	// regular metadata
	Node     int   `json:"node"`
	UnixTime int64 `json:"time"`
	// optional criteria
	Username      *string `json:"username"`
	Protocol      *string `json:"protocol"`
	ShareName     *string `json:"share_name"`
	JobType       *string `json:"job_type"`
	GroupName     *string `json:"groupname"`
	Path          *string `json:"path"`
	ZoneName      *string `json:"zone_name"`
	DomainID      *string `json:"domain_id"`
	ExportID      *int    `json:"export_id"`
	UserID        *int    `json:"user_id"`
	LocalAddress  *string `json:"local_address"`
	UserSid       *string `json:"user_sid"`
	ErrorString   *string `json:"error"`
	RemoteAddress *string `json:"remote_address"`
	WorkloadType  *string `json:"workload_type"`
	GroupSid      *string `json:"group_sid"`
	RemoteName    *string `json:"remote_name"`
	SystemName    *string `json:"system_name"`
	ZoneID        *int    `json:"zone_id"`
	WorkloadID    *int    `json:"workload_id"`
	LocalName     *string `json:"local_name"`
	GroupID       *int    `json:"group_id"`
}

// PPWorkloadQuery describes the result from calling the partitioned performance workload endpoint
type PPWorkloadQuery struct {
	Workloads []PPStatResult `json:"workload"`
}

// GetDataSetInfo returns info on each of the defined data sets on the cluster
func (c *Cluster) GetDataSetInfo(ctx context.Context) (*DsInfo, error) {
	var di DsInfo
	res, err := c.RestGet(ctx, dsPath)
	if err != nil {
		return nil, err
	}
	log.Debug("Got data set info", slog.String("response", string(res)))

	err = json.Unmarshal(res, &di)
	if err != nil {
		log.Error("Failed to unmarshal data set info for cluster", slog.String("cluster", c.String()))
		return nil, err
	}
	return &di, nil
}

// GetExportPathByID returns the first defined path for the given NFS export id or an error
func (c *Cluster) GetExportPathByID(ctx context.Context, id int) (string, error) {
	// We only care about the paths component here, so ignore the rest
	var exports any
	url := fmt.Sprintf("%s/%d", exportPath, id)
	log.Debug("fetching export info", slog.String("url", url))
	res, err := c.RestGet(ctx, url)
	if err != nil {
		return "", err
	}
	err = json.Unmarshal(res, &exports)
	if err != nil {
		return "", err
	}
	ea1, ok := exports.(map[string]any)
	if !ok {
		return "", fmt.Errorf("unexpected JSON structure for export %d", id)
	}
	ea2, ok := ea1["exports"].([]any)
	if !ok || len(ea2) == 0 {
		return "", fmt.Errorf("unexpected type or empty exports field for export %d", id)
	}
	export, ok := ea2[0].(map[string]any)
	if !ok {
		return "", fmt.Errorf("unexpected type for export entry %d", id)
	}
	paths := export["paths"]
	if paths == nil {
		return "", fmt.Errorf("no paths found for export id %d", id)
	}
	pathList, ok := paths.([]any)
	if !ok || len(pathList) == 0 {
		return "", fmt.Errorf("unexpected type or empty paths for export id %d", id)
	}
	// Just return the first path, even if there are multiple
	path, ok := pathList[0].(string)
	if !ok {
		return "", fmt.Errorf("unexpected type for path entry in export id %d", id)
	}
	return path, nil
}

// GetPPStats queries the API for the specified Partitioned Performance data set and returns
// an array of PPStatResult structures representing that set
func (c *Cluster) GetPPStats(ctx context.Context, dsName string) ([]PPStatResult, error) {
	var results []PPStatResult

	basePath := ppWorkloadPath + "?degraded=true&nodes=all&dataset=" + dsName
	log.Info("fetching PP stats from cluster", slog.String("cluster", c.String()))
	resp, err := c.RestGet(ctx, basePath)
	if err != nil {
		log.Error("Attempt to retrieve workload data failed",
			slog.String("cluster", c.String()),
			slog.String("dataset", dsName),
			slog.Any("error", err))
		return nil, err
	}
	log.Debug("workload response", slog.String("response", string(resp)))
	// Parse the result
	results, err = parsePPStatResult(resp)
	if err != nil {
		log.Error("Unable to parse stat response", slog.Any("error", err))
		return nil, err
	}

	return results, nil
}

// parsePPStatResult unmarshals the JSON response from the partitioned-performance workload
// endpoint and returns the workloads as an array of PPStatResult structures
func parsePPStatResult(res []byte) ([]PPStatResult, error) {
	// XXX need to handle errors response here!
	workloads := PPWorkloadQuery{}
	err := json.Unmarshal(res, &workloads)
	if err != nil {
		return nil, err
	}
	return workloads.Workloads, nil
}
