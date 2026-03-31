package backend

import (
	"context"
	"crypto/tls"
	"fmt"
	"log/slog"
	"time"

	"github.com/isilon/powerscale_data_insights/internal/config"
	influxdb2 "github.com/influxdata/influxdb-client-go/v2"
	"github.com/influxdata/influxdb-client-go/v2/api"
	"github.com/influxdata/influxdb-client-go/v2/api/write"
)

// InfluxDBv2Sink writes Points to an InfluxDB v2 database.
type InfluxDBv2Sink struct {
	cluster  string
	c        influxdb2.Client
	writeAPI api.WriteAPIBlocking
}

// NewInfluxDBv2 creates and connects an InfluxDB v2 backend writer.
func NewInfluxDBv2(ctx context.Context, clusterName string, ic config.InfluxDBv2Config) (DBWriter, error) {
	s := &InfluxDBv2Sink{cluster: clusterName}
	var err error

	scheme := "http"
	if ic.UseSSL {
		scheme = "https"
	}
	url := scheme + "://" + ic.Host + ":" + ic.Port

	token := ic.Token
	if token == "" {
		return nil, fmt.Errorf("InfluxDBv2 access token is missing or empty")
	}
	token, err = config.SecretFromEnv(token)
	if err != nil {
		return nil, fmt.Errorf("unable to retrieve InfluxDBv2 token from environment: %w", err)
	}
	opts := influxdb2.DefaultOptions()
	if ic.InsecureSkipVerify {
		opts.SetTLSConfig(&tls.Config{InsecureSkipVerify: true}) //nolint:gosec
	}
	client := influxdb2.NewClientWithOptions(url, token, opts)

	// ping the database to ensure we can connect
	pingCtx, cancel := context.WithTimeout(ctx, 30*time.Second)
	defer cancel()
	ok, err := client.Ping(pingCtx)
	if err != nil {
		return nil, fmt.Errorf("failed to ping InfluxDBv2: %w", err)
	}
	if !ok {
		return nil, fmt.Errorf("InfluxDBv2 ping failed - server not reachable")
	}
	slog.Info("successfully connected to InfluxDBv2", slog.String("cluster", clusterName))

	s.c = client
	s.writeAPI = client.WriteAPIBlocking(ic.Org, ic.Bucket)
	return s, nil
}

// WritePoints writes a batch of Points to InfluxDB v2.
func (s *InfluxDBv2Sink) WritePoints(ctx context.Context, points []Point) error {
	var pts []*write.Point
	for _, point := range points {
		for i, field := range point.Fields {
			pts = append(pts, influxdb2.NewPoint(point.Name, point.Tags[i], field, time.Unix(point.Time, 0).UTC()))
		}
	}
	if err := s.writeAPI.WritePoint(ctx, pts...); err != nil {
		return fmt.Errorf("InfluxDBv2 write failed: %w", err)
	}
	return nil
}
