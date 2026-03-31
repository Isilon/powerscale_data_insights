// Package backend provides the shared Point data model and DBWriter interface
// for writing time-series data to various backends (InfluxDB v1/v2, Prometheus,
// discard). Both gostats and goppstats convert their collector-specific data
// into Points before passing them to the backend.
package backend

import "context"

// Fields maps field names to their values for a single metric instance.
type Fields map[string]any

// Tags maps tag names to their string values for a single metric instance.
type Tags map[string]string

// Point represents a single named measurement at a given time in a time-series
// dataset. Because some statistics return multiple sets of data with unique
// combinations of tags, there is a single measurement name and timestamp, but
// arrays of field/tag maps (one entry per unique tag combination).
type Point struct {
	Name   string
	Time   int64
	Fields []Fields
	Tags   []Tags
}

// DBWriter defines the interface for writing time-series data to a backend.
type DBWriter interface {
	WritePoints(ctx context.Context, points []Point) error
}
