package main

import (
	"context"
	"fmt"

	"github.com/isilon/powerscale_data_insights/internal/backend"
)

type DBWriter interface {
	Init(ctx context.Context, cluster *Cluster, config *tomlConfig, clusterIndex int) error
	WritePoints(ctx context.Context, points []backend.Point) error
}

const (
	discardPluginName  = "discard"
	influxPluginName   = "influxdb"
	influxV2PluginName = "influxdbv2"
	promPluginName     = "prometheus"
)

type influxdbWrapper struct{ writer backend.DBWriter }

func (w *influxdbWrapper) Init(ctx context.Context, cluster *Cluster, cfg *tomlConfig, _ int) error {
	var err error
	w.writer, err = backend.NewInfluxDB(ctx, cluster.ClusterName, cfg.InfluxDB)
	return err
}

func (w *influxdbWrapper) WritePoints(ctx context.Context, points []backend.Point) error {
	return w.writer.WritePoints(ctx, points)
}

type influxdbv2Wrapper struct{ writer backend.DBWriter }

func (w *influxdbv2Wrapper) Init(ctx context.Context, cluster *Cluster, cfg *tomlConfig, _ int) error {
	var err error
	w.writer, err = backend.NewInfluxDBv2(ctx, cluster.ClusterName, cfg.InfluxDBv2)
	return err
}

func (w *influxdbv2Wrapper) WritePoints(ctx context.Context, points []backend.Point) error {
	return w.writer.WritePoints(ctx, points)
}

type discardWrapper struct{ writer backend.DBWriter }

func (w *discardWrapper) Init(context.Context, *Cluster, *tomlConfig, int) error {
	w.writer = backend.NewDiscard()
	return nil
}

func (w *discardWrapper) WritePoints(ctx context.Context, points []backend.Point) error {
	return w.writer.WritePoints(ctx, points)
}

func getDBWriter(name string) (DBWriter, error) {
	switch name {
	case discardPluginName:
		return &discardWrapper{}, nil
	case influxPluginName:
		return &influxdbWrapper{}, nil
	case influxV2PluginName:
		return &influxdbv2Wrapper{}, nil
	case promPluginName:
		return newPrometheusSink(), nil
	default:
		return nil, fmt.Errorf("unsupported backend plugin %q", name)
	}
}
