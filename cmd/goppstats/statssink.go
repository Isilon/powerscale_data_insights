package main

import (
	"context"

	"github.com/isilon/powerscale_data_insights/internal/backend"
)

// DBWriter defines an interface to write OneFS partitioned performance stats to a persistent store/database
type DBWriter interface {
	// Initialize a statssink
	Init(ctx context.Context, cluster *Cluster, config *tomlConfig, ci int) error
	// Write a set of generic points to the sink
	WritePoints(ctx context.Context, points []backend.Point) error
}
