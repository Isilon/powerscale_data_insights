package backend

import (
	"context"
	"fmt"
	"log/slog"
	"time"

	"github.com/isilon/powerscale_data_insights/internal/config"
	client "github.com/influxdata/influxdb1-client/v2"
)

// InfluxDBSink writes Points to an InfluxDB v1 database.
type InfluxDBSink struct {
	cluster  string
	client   client.Client
	bpConfig client.BatchPointsConfig
}

// NewInfluxDB creates and connects an InfluxDB v1 backend writer.
func NewInfluxDB(ctx context.Context, clusterName string, ic config.InfluxDBConfig) (DBWriter, error) {
	s := &InfluxDBSink{cluster: clusterName}
	var username, password string
	var err error

	scheme := "http"
	if ic.UseSSL {
		scheme = "https"
	}
	url := scheme + "://" + ic.Host + ":" + ic.Port

	s.bpConfig = client.BatchPointsConfig{
		Database:  ic.Database,
		Precision: "s",
	}

	if ic.Authenticated {
		username = ic.Username
		password = ic.Password
		password, err = config.SecretFromEnv(password)
		if err != nil {
			return nil, fmt.Errorf("unable to retrieve InfluxDB password from environment: %w", err)
		}
	}

	dbClient, err := client.NewHTTPClient(client.HTTPConfig{
		Addr:               url,
		Username:           username,
		Password:           password,
		InsecureSkipVerify: ic.InsecureSkipVerify,
	})
	if err != nil {
		return nil, fmt.Errorf("failed to create InfluxDB client: %w", err)
	}
	// ping the database to ensure we can connect
	responseTime, response, err := dbClient.Ping(30 * time.Second)
	if err != nil {
		return nil, fmt.Errorf("failed to ping InfluxDB: %w", err)
	}
	slog.Info("successfully connected to InfluxDB",
		slog.String("response", response),
		slog.Duration("response_time", responseTime))
	s.client = dbClient
	return s, nil
}

// WritePoints writes a batch of Points to InfluxDB v1.
func (s *InfluxDBSink) WritePoints(_ context.Context, points []Point) error {
	bp, err := client.NewBatchPoints(s.bpConfig)
	if err != nil {
		return fmt.Errorf("unable to create InfluxDB batch points: %w", err)
	}
	for _, point := range points {
		var pts []*client.Point
		for i, f := range point.Fields {
			var pt *client.Point
			pt, err = client.NewPoint(point.Name, point.Tags[i], f, time.Unix(point.Time, 0).UTC())
			if err != nil {
				slog.Warn("failed to create point", slog.String("measurement", point.Name))
				continue
			}
			pts = append(pts, pt)
		}
		if len(pts) > 0 {
			bp.AddPoints(pts)
		}
	}
	err = s.client.Write(bp)
	if err != nil {
		return fmt.Errorf("failed to write batch of points: %w", err)
	}
	return nil
}
