package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"

	"github.com/isilon/powerscale_data_insights/internal/api"
	"github.com/isilon/powerscale_data_insights/internal/logging"
	mapset "github.com/deckarep/golang-set/v2"
)

// Cluster embeds the shared api.Cluster and adds gostats-specific state.
type Cluster struct {
	*api.Cluster
	badStats mapset.Set[string]
}

// Connect delegates to the embedded api.Cluster.Connect and then initialises
// the gostats-specific badStats set.
func (c *Cluster) Connect(ctx context.Context) error {
	if err := c.Cluster.Connect(ctx); err != nil {
		return err
	}
	c.badStats = mapset.NewSet[string]()
	return nil
}

// StatResult contains the information returned for a single stat key
// when querying the OneFS statistics API.
// The Value field can be a simple int/float, or it can be a dictionary
// or an array of dictionaries (e.g. protostats results), or even more complex
// nested structures.
type StatResult struct {
	Devid       int    `json:"devid"`
	Node        *int   `json:"node,omitempty"`
	ErrorString string `json:"error"`
	ErrorCode   int    `json:"error_code"`
	Key         string `json:"key"`
	UnixTime    int64  `json:"time"`
	Value       any    `json:"value"`
}

// statDetail holds the metadata information for a stat as retrieved from
// the statistics '/keys' endpoint
type statDetail struct {
	//	key         string
	valid       bool // flag if this stat doesn't exist on this cluster
	description string
	units       string
	scope       string
	datatype    string // JSON "type"
	aggType     string // aggregation type - add enum if/when we use it
	updateIntvl float64
}

// API endpoint paths (gostats-specific)
const statsPath = "/platform/1/statistics/current"
const statInfoPath = "/platform/1/statistics/keys/"
const summaryStatsPath = "/platform/3/statistics/summary/"

// Summary stats will be persisted as "node.summary.<stat_type>"
const summaryStatsBasename = "node.summary."

// Isi stats key error codes
const (
	StatErrorNone = iota
	StatErrorNotPresent
	StatErrorNotImplemented
	StatErrorDegraded
	StatErrorStale
	StatErrorConnTimeout
	StatErrorTimeout
	StatErrorNoHistory
	StatErrorSystem
	StatErrorNotConfigured
	StatErrorNoData
)

// SummaryStatsProtocol stores the return from the /3/statistics/summary/statistics endpoint
// which returns an array of protocol summary stats or an array of errors
type SummaryStatsProtocol struct {
	// A list of errors that may be returned.
	Errors []APIError `json:"errors,omitempty"`
	// or the array of summary stats
	Protocol []SummaryStatsProtocolItem `json:"protocol,omitempty"`
}

// APIError describes a single error.
type APIError struct {
	Code    string  `json:"code"`            // The error code.
	Field   *string `json:"field,omitempty"` // The field with the error if applicable.
	Message string  `json:"message"`         // The error message.

}

// SummaryStatsProtocolItem describes a single protocol summary stat entry
type SummaryStatsProtocolItem struct {
	Class           string  `json:"class"`             // The class of the operation.
	In              float64 `json:"in"`                // Rate of input (in bytes/second) for an operation since the last time isi statistics collected the data.
	InAvg           float64 `json:"in_avg"`            // Average input (received) bytes for an operation, in bytes.
	InMax           float64 `json:"in_max"`            // Maximum input (received) bytes for an operation, in bytes.
	InMin           float64 `json:"in_min"`            // Minimum input (received) bytes for an operation, in bytes.
	InStandardDev   float64 `json:"in_standard_dev"`   // Standard deviation for input (received) bytes for an operation, in bytes.
	Node            *int64  `json:"node"`              // The node on which the operation was performed.
	Operation       string  `json:"operation"`         // The operation performed.
	OperationCount  int64   `json:"operation_count"`   // The number of times an operation has been performed.
	OperationRate   float64 `json:"operation_rate"`    // The rate (in ops/second) at which an operation has been performed.
	Out             float64 `json:"out"`               // Rate of output (in bytes/second) for an operation since the last time isi statistics collected the data.
	OutAvg          float64 `json:"out_avg"`           // Average output (sent) bytes for an operation, in bytes.
	OutMax          float64 `json:"out_max"`           // Maximum output (sent) bytes for an operation, in bytes.
	OutMin          float64 `json:"out_min"`           // Minimum output (sent) bytes for an operation, in bytes.
	OutStandardDev  float64 `json:"out_standard_dev"`  // Standard deviation for output (received) bytes for an operation, in bytes.
	Protocol        string  `json:"protocol"`          // The protocol of the operation.
	Time            int64   `json:"time"`              // Unix Epoch time in seconds of the request.
	TimeAvg         float64 `json:"time_avg"`          // The average elapsed time (in microseconds) taken to complete an operation.
	TimeMax         float64 `json:"time_max"`          // The maximum elapsed time (in microseconds) taken to complete an operation.
	TimeMin         float64 `json:"time_min"`          // The minimum elapsed time (in microseconds) taken to complete an operation.
	TimeStandardDev float64 `json:"time_standard_dev"` // The standard deviation time (in microseconds) taken to complete an operation.
}

// SummaryStatsClient stores the return from the /3/statistics/summary/client endpoint
// which returns an array of client summary stats or an array of errors
type SummaryStatsClient struct {
	// A list of errors that may be returned.
	Errors []APIError `json:"errors,omitempty"`
	// or the array of summary stats
	Client []SummaryStatsClientItem `json:"client,omitempty"`
}

// SummaryStatsClientItem describes a single client summary stat entry
type SummaryStatsClientItem struct {
	Class         string  `json:"class"`
	In            float64 `json:"in"`
	InAvg         float64 `json:"in_avg"`
	InMax         float64 `json:"in_max"`
	InMin         float64 `json:"in_min"`
	LocalAddr     string  `json:"local_addr"`
	LocalName     string  `json:"local_name"`
	Node          *int64  `json:"node"`
	NumOperations int64   `json:"num_operations"`
	OperationRate float64 `json:"operation_rate"`
	Out           float64 `json:"out"`
	OutAvg        float64 `json:"out_avg"`
	OutMax        float64 `json:"out_max"`
	OutMin        float64 `json:"out_min"`
	Protocol      string  `json:"protocol"`
	RemoteAddr    string  `json:"remote_addr"`
	RemoteName    string  `json:"remote_name"`
	Time          int64   `json:"time"`
	TimeAvg       float64 `json:"time_avg"`
	TimeMax       float64 `json:"time_max"`
	TimeMin       float64 `json:"time_min"`
	User          *struct {
		ID   string `json:"id"`
		Name string `json:"name"`
		Type string `json:"type"`
	} `json:"user,omitempty"`
}

// SummaryStatsDrive stores the return from the /3/statistics/summary/drive endpoint
// which returns an array of drive summary stats or an array of errors
type SummaryStatsDrive struct {
	// A list of errors that may be returned.
	Errors []APIError `json:"errors,omitempty"`
	// or the array of summary stats
	Drive []SummaryStatsDriveItem `json:"drive,omitempty"`
}

// SummaryStatsDriveItem describes a single drive summary stat entry
type SummaryStatsDriveItem struct {
	AccessLatency   float64 `json:"access_latency"`
	AccessSlow      float64 `json:"access_slow"`
	Busy            float64 `json:"busy"`
	BytesIn         float64 `json:"bytes_in"`
	BytesOut        float64 `json:"bytes_out"`
	DriveID         string  `json:"drive_id"`
	IoschedLatency  float64 `json:"iosched_latency"`
	IoschedQueue    float64 `json:"iosched_queue"`
	Time            int64   `json:"time"`
	Type            string  `json:"type"`
	UsedBytesPercent float64 `json:"used_bytes_percent"`
	UsedInodes      float64 `json:"used_inodes"`
	XferSizeIn      float64 `json:"xfer_size_in"`
	XferSizeOut     float64 `json:"xfer_size_out"`
	XfersIn         float64 `json:"xfers_in"`
	XfersOut        float64 `json:"xfers_out"`
}

// UnmarshalSummaryStatsDrive unmarshals the JSON return from the summary stats drive endpoint
func UnmarshalSummaryStatsDrive(data []byte) (SummaryStatsDrive, error) {
	var r SummaryStatsDrive
	err := json.Unmarshal(data, &r)
	return r, err
}

// GetSummaryDriveStats queries the summary stats drive endpoint and returns a SummaryStatsDrive struct or an error
func (c *Cluster) GetSummaryDriveStats(ctx context.Context) ([]SummaryStatsDriveItem, error) {
	path := summaryStatsPath + "drive?degraded=true"
	log.Info("fetching drive summary stats", slog.String("cluster", c.String()))
	resp, err := c.RestGet(ctx, path)
	if err != nil {
		if !errors.Is(err, context.Canceled) {
			log.Error("failed to get drive summary stats", slog.String("cluster", c.String()), slog.String("error", err.Error()))
		}
		// TODO investigate handling partial errors rather than totally failing?
		return nil, err
	}
	// TODO - Need to handle JSON return of "errors" here (e.g. for re-auth
	// when using session cookies)
	log.Log(ctx, logging.LevelTrace, "got response", slog.String("cluster", c.String()), "response", resp)
	r, err := UnmarshalSummaryStatsDrive(resp)
	if err != nil {
		errmsg := fmt.Errorf("cluster %s unable to parse drive summary stats response %q - error %s", c, resp, err)
		return nil, errmsg
	}
	if len(r.Errors) > 0 {
		// Theoretically, the Errors array can contain multiple entries
		// I haven't ever seen that, so we just take the first entry here
		apiError := r.Errors[0]
		errmsg := fmt.Errorf("drive summary stats endpoint for cluster %s returned error code %s, message %s", c.String(), apiError.Code, apiError.Message)
		return nil, errmsg
	}
	log.Debug("successfully decoded drive summary stats", slog.String("cluster", c.String()), slog.Int("count", len(r.Drive)))
	return r.Drive, nil
}

// UnmarshalSummaryStatsProtocol unmarshals the JSON return from the summary stats protocol endpoint
func UnmarshalSummaryStatsProtocol(data []byte) (SummaryStatsProtocol, error) {
	var r SummaryStatsProtocol
	err := json.Unmarshal(data, &r)
	return r, err
}

// GetSummaryProtocolStats queries the summary stats protocol endpoint and returns a SummaryStatsProtocol struct or an error
func (c *Cluster) GetSummaryProtocolStats(ctx context.Context) ([]SummaryStatsProtocolItem, error) {
	path := summaryStatsPath + "protocol?degraded=true"
	log.Info("fetching protocol summary stats", slog.String("cluster", c.String()))
	resp, err := c.RestGet(ctx, path)
	if err != nil {
		if !errors.Is(err, context.Canceled) {
			log.Error("failed to get protocol summary stats", slog.String("cluster", c.String()), slog.String("error", err.Error()))
		}
		// TODO investigate handling partial errors rather than totally failing?
		return nil, err
	}
	// TODO - Need to handle JSON return of "errors" here (e.g. for re-auth
	// when using session cookies)
	log.Log(ctx, logging.LevelTrace, "got response", slog.String("cluster", c.String()), "response", resp)
	r, err := UnmarshalSummaryStatsProtocol(resp)
	if err != nil {
		errmsg := fmt.Errorf("cluster %s unable to parse protocol summary stats response %q - error %s", c, resp, err)
		return nil, errmsg
	}
	if len(r.Errors) > 0 {
		// Theoretically, the Errors array can contain multiple entries
		// I haven't ever seen that, so we just take the first entry here
		apiError := r.Errors[0]
		errmsg := fmt.Errorf("protocol summary stats endpoint for cluster %s returned error code %s, message %s", c.String(), apiError.Code, apiError.Message)
		return nil, errmsg
	}
	log.Debug("successfully decoded protocol summary stats", slog.String("cluster", c.String()), slog.Int("count", len(r.Protocol)))
	return r.Protocol, nil
}

// UnmarshalSummaryStatsClient unmarshals the JSON return from the summary stats client endpoint
func UnmarshalSummaryStatsClient(data []byte) (SummaryStatsClient, error) {
	var r SummaryStatsClient
	err := json.Unmarshal(data, &r)
	return r, err
}

// GetSummaryClientStats queries the summary stats client endpoint and returns a SummaryStatsClient struct or an error
func (c *Cluster) GetSummaryClientStats(ctx context.Context) ([]SummaryStatsClientItem, error) {
	path := summaryStatsPath + "client?degraded=true"
	log.Info("fetching client summary stats", slog.String("cluster", c.String()))
	resp, err := c.RestGet(ctx, path)
	if err != nil {
		if !errors.Is(err, context.Canceled) {
			log.Error("failed to get client summary stats", slog.String("cluster", c.String()), slog.String("error", err.Error()))
		}
		// TODO investigate handling partial errors rather than totally failing?
		return nil, err
	}
	// TODO - Need to handle JSON return of "errors" here (e.g. for re-auth
	// when using session cookies)
	log.Log(ctx, logging.LevelTrace, "got response", slog.String("cluster", c.String()), "response", resp)
	r, err := UnmarshalSummaryStatsClient(resp)
	if err != nil {
		errmsg := fmt.Errorf("cluster %s unable to parse client summary stats response %q - error %s", c, resp, err)
		return nil, errmsg
	}
	if len(r.Errors) > 0 {
		// Theoretically, the Errors array can contain multiple entries
		// I haven't ever seen that, so we just take the first entry here
		apiError := r.Errors[0]
		errmsg := fmt.Errorf("client summary stats endpoint for cluster %s returned error code %s, message %s", c.String(), apiError.Code, apiError.Message)
		return nil, errmsg
	}
	log.Debug("successfully decoded client summary stats", slog.String("cluster", c.String()), slog.Int("count", len(r.Client)))
	return r.Client, nil
}

// GetStats takes an array of statistics keys and returns an
// array of StatResult structures
func (c *Cluster) GetStats(ctx context.Context, stats []string) ([]StatResult, error) {
	var results []StatResult

	basePath := statsPath + "?degraded=true&devid=all&show_nodes=true"
	log.Info("fetching stats", slog.String("cluster", c.String()), slog.Int("count", len(stats)))
	// max space available for &key=... args (subtract basePath length and some slop)
	maxKeyLen := api.MaxAPIPathLen - (len(basePath) + 100)

	var buffer bytes.Buffer
	buffer.WriteString(basePath)
	keyLen := 0

	for _, stat := range stats {
		keyArg := "&key=" + stat
		if keyLen > 0 && keyLen+len(keyArg) > maxKeyLen {
			// Current batch is full; send it before adding the next stat
			log.Debug("sending request", slog.String("cluster", c.String()), slog.String("request", buffer.String()))
			resp, err := c.RestGet(ctx, buffer.String())
			if err != nil {
				if !errors.Is(err, context.Canceled) {
					log.Error("failed to get stats", slog.String("cluster", c.String()), slog.String("error", err.Error()))
				}
				// TODO investigate handling partial errors rather than totally failing?
				return nil, err
			}
			log.Log(ctx, logging.LevelTrace, "got response", slog.String("cluster", c.String()), "response", resp)
			r, err := parseStatResult(resp)
			if err != nil {
				log.Error("unable to parse response", slog.String("cluster", c.String()), slog.String("response", string(resp)), slog.String("error", err.Error()))
				return nil, err
			}
			log.Log(ctx, logging.LevelTrace, "parsed stats results", slog.String("cluster", c.String()), "results", r)
			results = append(results, r...)
			buffer.Reset()
			buffer.WriteString(basePath)
			keyLen = 0
		}
		buffer.WriteString(keyArg)
		keyLen += len(keyArg)
	}

	// Send the final (or only) batch
	log.Debug("sending request", slog.String("cluster", c.String()), slog.String("request", buffer.String()))
	resp, err := c.RestGet(ctx, buffer.String())
	if err != nil {
		if !errors.Is(err, context.Canceled) {
			log.Error("failed to get stats", slog.String("cluster", c.String()), slog.String("error", err.Error()))
		}
		return nil, err
	}
	// TODO - Need to handle JSON return of "errors" here (e.g. for re-auth
	// when using session cookies)
	log.Log(ctx, logging.LevelTrace, "got response", slog.String("cluster", c.String()), "response", resp)
	r, err := parseStatResult(resp)
	if err != nil {
		log.Error("unable to parse response", slog.String("cluster", c.String()), slog.String("response", string(resp)), slog.String("error", err.Error()))
		return nil, err
	}
	log.Log(ctx, logging.LevelTrace, "parsed stats results", slog.String("cluster", c.String()), "results", r)
	results = append(results, r...)

	return results, nil
}

// parseStatResult is currently very basic and just unmarshals the JSON API return
func parseStatResult(res []byte) ([]StatResult, error) {
	sa := struct {
		Stats []StatResult `json:"stats"`
	}{}
	err := json.Unmarshal(res, &sa)
	if err == nil {
		return sa.Stats, nil
	}
	var errors []APIError
	err = json.Unmarshal(res, &errors)
	if err != nil {
		errmsg := fmt.Errorf("unable to parse current stats endpoint result: %s", res)
		return nil, errmsg
	}
	if len(errors) == 0 {
		return nil, fmt.Errorf("stats endpoint returned unparseable response: %s", res)
	}
	// Theoretically, the Errors array can contain multiple entries
	// I haven't ever seen that, so we just take the first entry here
	apiError := errors[0]
	errmsg := fmt.Errorf("stats endpoint returned error code %s, message %s", apiError.Code, apiError.Message)
	return nil, errmsg
}

// fetchStatDetails gathers and returns the API-provided metadata for the given set of stats
func (c *Cluster) fetchStatDetails(ctx context.Context, sg map[string]statGroup) map[string]statDetail {
	badStat := statDetail{valid: false}

	statInfo := make(map[string]statDetail)
	for group := range sg {
		stats := sg[group].stats
		for _, stat := range stats {
			path := statInfoPath + stat
			resp, err := c.RestGet(ctx, path)
			if err != nil {
				if !errors.Is(err, context.Canceled) {
					log.Warn("failed to retrieve information for stat - removing", slog.String("cluster", c.String()), slog.String("stat", stat), slog.String("error", err.Error()))
				}
				statInfo[stat] = badStat
				continue
			}
			// parse stat info
			detail, err := parseStatInfo(resp)
			if err != nil {
				log.Warn("failed to parse detailed information for stat - removing", slog.String("cluster", c.String()), slog.String("stat", stat), slog.String("error", err.Error()))
				statInfo[stat] = badStat
				continue
			}
			statInfo[stat] = *detail
		}
	}
	return statInfo
}

// parseStatInfo parses the OneFS API statistics metric metadata returned
// from the statistics detail endpoint
func parseStatInfo(res []byte) (*statDetail, error) {
	var detail statDetail
	var v any

	// Unmarshal the JSON return first
	err := json.Unmarshal(res, &v)
	if err != nil {
		return nil, err
	}

	m, ok := v.(map[string]any)
	if !ok {
		return nil, fmt.Errorf("unexpected JSON structure")
	}
	// Did the API throw an error?
	if ea, ok := m["errors"]; ok {
		// handle API error return here
		// I've never seen more than one error in the array, but we handle it anyway
		eaSlice, ok := ea.([]any)
		if !ok {
			return nil, fmt.Errorf("unexpected type for errors field")
		}
		es := bytes.NewBufferString("error: ")
		for _, e := range eaSlice {
			eMap, ok := e.(map[string]any)
			if !ok {
				return nil, fmt.Errorf("unexpected type for error entry")
			}
			fmt.Fprintf(es, "code: %q, message: %q", eMap["code"], eMap["message"])
		}
		return nil, errors.New(es.String())
	}

	var keys any
	if keys, ok = m["keys"]; !ok {
		// If we didn't get an error above, we should have got a valid return
		return nil, fmt.Errorf("unexpected JSON return %#v", m)
	}
	ka, ok := keys.([]any)
	if !ok {
		return nil, fmt.Errorf("unexpected type for keys field")
	}
	for _, k := range ka {
		// pull info from key
		kMap, ok := k.(map[string]any)
		if !ok {
			return nil, fmt.Errorf("unexpected type for key entry")
		}
		// Extract stat update times out of "policies" if they exist
		kp := kMap["policies"]
		if kp == nil {
			// 0 == no defined update interval i.e. on-demand
			detail.updateIntvl = 0.0
		} else {
			kpa, ok := kp.([]any)
			if !ok {
				return nil, fmt.Errorf("unexpected type for policies field")
			}
			for _, pol := range kpa {
				polMap, ok := pol.(map[string]any)
				if !ok {
					return nil, fmt.Errorf("unexpected type for policy entry")
				}
				// we only want the current info, not the historical
				if polMap["persistent"] == false {
					intvl, ok := polMap["interval"].(float64)
					if !ok {
						return nil, fmt.Errorf("unexpected type for interval field")
					}
					detail.updateIntvl = intvl
					break
				}
			}
		}
		description, ok := kMap["description"].(string)
		if !ok {
			return nil, fmt.Errorf("unexpected type for description field")
		}
		detail.description = description
		units, ok := kMap["units"].(string)
		if !ok {
			return nil, fmt.Errorf("unexpected type for units field")
		}
		detail.units = units
		scope, ok := kMap["scope"].(string)
		if !ok {
			return nil, fmt.Errorf("unexpected type for scope field")
		}
		detail.scope = scope
		datatype, ok := kMap["type"].(string)
		if !ok {
			return nil, fmt.Errorf("unexpected type for type field")
		}
		detail.datatype = datatype
		aggType, ok := kMap["aggregation_type"].(string)
		if !ok {
			return nil, fmt.Errorf("unexpected type for aggregation_type field")
		}
		detail.aggType = aggType
	}

	detail.valid = true
	return &detail, nil
}
