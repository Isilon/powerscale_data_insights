package main

import (
	"context"
	"fmt"
	"log/slog"
	"strconv"
	"time"

	client "github.com/influxdata/influxdb1-client/v2"
)

// InfluxDBSink defines the data to allow us talk to an InfluxDB database
type InfluxDBSink struct {
	clusterName string
	cluster     *Cluster // needed to enable per-cluster export id lookup
	client      client.Client
	bpConfig    client.BatchPointsConfig
	exports     exportMap
}

// GetInfluxDBWriter returns an InfluxDB DBWriter
func GetInfluxDBWriter() DBWriter {
	return &InfluxDBSink{}
}

// Init initializes an InfluxDBSink so that points can be written
func (s *InfluxDBSink) Init(ctx context.Context, cluster *Cluster, config *tomlConfig, ci int) error {
	s.clusterName = cluster.ClusterName
	s.cluster = cluster
	var username, password string
	var err error
	ic := config.InfluxDB
	url := "http://" + ic.Host + ":" + ic.Port

	s.bpConfig = client.BatchPointsConfig{
		Database:  ic.Database,
		Precision: "s",
	}

	if ic.Authenticated {
		username = ic.Username
		password = ic.Password
		password, err = secretFromEnv(password)
		if err != nil {
			return fmt.Errorf("unable to retrieve InfluxDB password from environment: %w", err)
		}
	}

	dbClient, err := client.NewHTTPClient(client.HTTPConfig{
		Addr:     url,
		Username: username,
		Password: password,
	})
	if err != nil {
		return fmt.Errorf("failed to create InfluxDB client: %w", err)
	}
	// ping the database to ensure we can connect
	responseTime, response, err := dbClient.Ping(30 * time.Second)
	if err != nil {
		return fmt.Errorf("failed to ping InfluxDB: %w", err)
	}
	log.Log(ctx, LevelNotice, "successfully connected to InfluxDB",
		slog.String("response", response),
		slog.Duration("response_time", responseTime))
	s.client = dbClient
	s.exports = newExportMap(config.Global.LookupExportIDs)
	return nil
}

// UpdateDatasets updates the back end view of the current dataset definitions.
func (s *InfluxDBSink) UpdateDatasets(di *DsInfo) {
	// currently, do nothing
}

// WritePPStats takes an array of PPStatResults and writes them to InfluxDB.
func (s *InfluxDBSink) WritePPStats(ctx context.Context, ds DsInfoEntry, ppstats []PPStatResult) error {
	keyName := ds.StatKey

	bp, err := client.NewBatchPoints(s.bpConfig)
	if err != nil {
		return fmt.Errorf("unable to create InfluxDB batch points: %w", err)
	}
	for _, ppstat := range ppstats {
		fields := fieldsForPPStat(ppstat)
		log.Debug("got fields", slog.Any("fields", fields))

		tags := tagsForPPStat(ctx, ppstat, s.cluster, s.exports)
		tags["cluster"] = s.clusterName
		tags["node"] = strconv.Itoa(ppstat.Node)
		log.Debug("got tags", slog.Any("tags", tags))

		var pt *client.Point
		pt, err = client.NewPoint(keyName, tags, fields, time.Unix(ppstat.UnixTime, 0).UTC())
		if err != nil {
			log.Warn("failed to create point", slog.String("key", keyName))
			continue
		}
		bp.AddPoint(pt)
	}
	// write the batch
	err = s.client.Write(bp)
	if err != nil {
		return fmt.Errorf("failed to write batch of points: %w", err)
	}
	return nil
}
