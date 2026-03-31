package main

import "context"

// DBWriter defines an interface to write OneFS partitioned performance stats to a persistent store/database
type DBWriter interface {
	// Initialize a statssink
	Init(ctx context.Context, cluster *Cluster, config *tomlConfig, ci int) error
	// Update our current view of the defined datasets
	UpdateDatasets(di *DsInfo)
	// Write a set of partitioned performance stats to the sink
	WritePPStats(ctx context.Context, ds DsInfoEntry, stats []PPStatResult) error
}
