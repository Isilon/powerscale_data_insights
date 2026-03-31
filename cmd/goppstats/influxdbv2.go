package main

import (
	"context"
	"fmt"
	"log/slog"
	"strconv"
	"time"

	influxdb2 "github.com/influxdata/influxdb-client-go/v2"
	"github.com/influxdata/influxdb-client-go/v2/api"
	"github.com/influxdata/influxdb-client-go/v2/api/write"
)

// InfluxDBv2Sink defines the data to allow us talk to an InfluxDBv2 database
type InfluxDBv2Sink struct {
	clusterName string
	cluster     *Cluster // needed to enable per-cluster export id lookup
	c           influxdb2.Client
	writeAPI    api.WriteAPIBlocking
	exports     exportMap
}

// GetInfluxDBv2Writer returns an InfluxDBv2 DBWriter
func GetInfluxDBv2Writer() DBWriter {
	return &InfluxDBv2Sink{}
}

// Init initializes an InfluxDBSink so that points can be written
func (s *InfluxDBv2Sink) Init(ctx context.Context, cluster *Cluster, config *tomlConfig, ci int) error {
	s.clusterName = cluster.ClusterName
	s.cluster = cluster
	var err error
	ic := config.InfluxDBv2
	url := "http://" + ic.Host + ":" + ic.Port

	token := ic.Token
	if token == "" {
		return fmt.Errorf("InfluxDBv2 access token is missing or empty")
	}
	token, err = secretFromEnv(token)
	if err != nil {
		return fmt.Errorf("unable to retrieve InfluxDBv2 token from environment: %w", err)
	}
	client := influxdb2.NewClient(url, token)
	// ping the database to ensure we can connect
	pingCtx, cancel := context.WithTimeout(ctx, 30*time.Second)
	defer cancel()
	ok, err := client.Ping(pingCtx)
	if err != nil {
		return fmt.Errorf("failed to ping InfluxDBv2: %w", err)
	}
	if !ok {
		return fmt.Errorf("InfluxDBv2 ping failed - server not reachable")
	}
	log.Log(ctx, LevelNotice, "successfully connected to InfluxDBv2", slog.String("cluster", cluster.ClusterName))
	s.c = client
	s.writeAPI = client.WriteAPIBlocking(ic.Org, ic.Bucket)

	s.exports = newExportMap(config.Global.LookupExportIDs)
	return nil
}

// UpdateDatasets updates the back end view of the current dataset definitions.
func (s *InfluxDBv2Sink) UpdateDatasets(di *DsInfo) {
	// currently, do nothing
}

// WritePPStats takes an array of PPStatResults and writes them to InfluxDB.
func (s *InfluxDBv2Sink) WritePPStats(ctx context.Context, ds DsInfoEntry, ppstats []PPStatResult) error {
	keyName := ds.StatKey

	var pts []*write.Point
	for _, ppstat := range ppstats {
		fields := fieldsForPPStat(ppstat)
		log.Debug("got fields", slog.Any("fields", fields))

		tags := tagsForPPStat(ctx, ppstat, s.cluster, s.exports)
		tags["cluster"] = s.clusterName
		tags["node"] = strconv.Itoa(ppstat.Node)
		log.Debug("got tags", slog.Any("tags", tags))

		pts = append(pts, influxdb2.NewPoint(keyName, tags, fields, time.Unix(ppstat.UnixTime, 0).UTC()))
	}
	if err := s.writeAPI.WritePoint(ctx, pts...); err != nil {
		return fmt.Errorf("InfluxDBv2 write failed: %w", err)
	}
	return nil
}
