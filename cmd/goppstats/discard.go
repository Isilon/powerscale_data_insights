package main

import "context"

// DiscardSink defines the data for the null/discard back end
type DiscardSink struct {
	clusterName string
}

// GetDiscardWriter returns a discard DBWriter
func GetDiscardWriter() DBWriter {
	return &DiscardSink{}
}

// Init initializes an DiscardSink so that points can be written (thrown away)
func (s *DiscardSink) Init(_ context.Context, cluster *Cluster, _ *tomlConfig, _ int) error {
	s.clusterName = cluster.ClusterName
	return nil
}

// UpdateDatasets updates the back end view of the current dataset definitions.
func (s *DiscardSink) UpdateDatasets(ds *DsInfo) {
	// empty
}

// WritePPStats takes an array of PPStatResults and discards them.
func (s *DiscardSink) WritePPStats(_ context.Context, ds DsInfoEntry, stats []PPStatResult) error {
	// consider debug/trace statement here for stat count
	return nil
}
