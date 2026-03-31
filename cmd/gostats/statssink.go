package main

import (
	"context"

	"github.com/isilon/powerscale_data_insights/internal/backend"
)

// DBWriter defines an interface to write OneFS stats to a persistent store/database
type DBWriter interface {
	// Initialize a statssink
	Init(ctx context.Context, clusterName string, config *tomlConfig, ci int, sg map[string]statDetail) error
	// Write an array of points to the sink
	WritePoints(ctx context.Context, points []backend.Point) error
}
