package main

import (
	"context"
	"crypto/subtle"
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"net/http"
	"regexp"
	"sort"
	"strings"
	"sync"
	"time"

	"github.com/isilon/powerscale_data_insights/internal/backend"
	"github.com/isilon/powerscale_data_insights/internal/config"
	"github.com/isilon/powerscale_data_insights/internal/platform"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promhttp"
)

type promSDTarget struct {
	Targets []string          `json:"targets"`
	Labels  map[string]string `json:"labels"`
}

func startPromSDListener(ctx context.Context, cfg tomlConfig) error {
	listenAddr := cfg.PromSD.ListenAddr
	if listenAddr == "" {
		var err error
		listenAddr, err = platform.FindExternalAddr()
		if err != nil {
			return err
		}
	}
	targets := make([]string, 0, len(cfg.Clusters))
	for _, cluster := range cfg.Clusters {
		if !cluster.Disabled && cluster.PrometheusPort != nil {
			targets = append(targets, fmt.Sprintf("%s:%d", listenAddr, *cluster.PrometheusPort))
		}
	}
	payload, err := json.Marshal([]promSDTarget{{
		Targets: targets,
		Labels:  map[string]string{"__meta_prometheus_job": "isilon_quotas"},
	}})
	if err != nil {
		return err
	}
	mux := http.NewServeMux()
	mux.HandleFunc("/", func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write(payload)
	})
	server := &http.Server{Handler: mux, ReadHeaderTimeout: 5 * time.Second}
	listenConfig := net.ListenConfig{Control: platform.Control}
	listener, err := listenConfig.Listen(ctx, "tcp", fmt.Sprintf(":%d", cfg.PromSD.SDport))
	if err != nil {
		return fmt.Errorf("listen for Prometheus HTTP SD: %w", err)
	}
	go func() {
		if err := server.Serve(listener); err != nil && !errors.Is(err, http.ErrServerClosed) {
			log.Error("Prometheus HTTP SD listener stopped", "error", err)
		}
	}()
	go func() {
		<-ctx.Done()
		shutdownCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_ = server.Shutdown(shutdownCtx)
	}()
	return nil
}

var quotaLabelNames = []string{
	"cluster",
	"quota_id",
	"quota_type",
	"path",
	"persona_type",
	"persona_id",
	"persona_name",
	"thresholds_on",
	"linked",
	"include_snapshots",
}

var prometheusLabelPattern = regexp.MustCompile(`^[a-zA-Z_][a-zA-Z0-9_]*$`)

type prometheusSnapshot struct {
	metrics []prometheus.Metric
	count   int
	series  int
}

// PrometheusSink is both the quota DBWriter and an atomic snapshot collector.
// WritePoints constructs a complete replacement before taking the lock, so a
// concurrent scrape sees either the old or the new successful snapshot.
type PrometheusSink struct {
	mu sync.RWMutex

	clusterName       string
	instanceLabelName string
	snapshot          prometheusSnapshot
	descriptors       map[string]*prometheus.Desc
	lastSuccess       float64
	lastDuration      float64
	lastCollectionOK  float64
	server            *http.Server
	registry          *prometheus.Registry
}

func newPrometheusSink() *PrometheusSink {
	return &PrometheusSink{descriptors: make(map[string]*prometheus.Desc)}
}

func (s *PrometheusSink) Init(ctx context.Context, cluster *Cluster, cfg *tomlConfig, clusterIndex int) error {
	port := cfg.Clusters[clusterIndex].PrometheusPort
	if port == nil || *port == 0 {
		return fmt.Errorf("prometheus_port must be configured for cluster %s", cluster.Hostname)
	}
	s.clusterName = cluster.ClusterName
	if cfg.Prometheus.InstanceLabelName != nil && *cfg.Prometheus.InstanceLabelName != "" {
		s.instanceLabelName = *cfg.Prometheus.InstanceLabelName
		if !prometheusLabelPattern.MatchString(s.instanceLabelName) || strings.HasPrefix(s.instanceLabelName, "__") {
			return fmt.Errorf("invalid Prometheus instance_label_name %q", s.instanceLabelName)
		}
		for _, name := range quotaLabelNames {
			if s.instanceLabelName == name {
				return fmt.Errorf("Prometheus instance_label_name %q conflicts with a quota label", s.instanceLabelName)
			}
		}
	}
	s.registry = prometheus.NewRegistry()
	if err := s.registry.Register(s); err != nil {
		return fmt.Errorf("register quota Prometheus collector: %w", err)
	}

	username := ""
	password := ""
	if cfg.Prometheus.Authenticated {
		username = cfg.Prometheus.Username
		var err error
		password, err = config.SecretFromEnv(cfg.Prometheus.Password)
		if err != nil {
			return fmt.Errorf("retrieve Prometheus password: %w", err)
		}
		if username == "" || password == "" {
			return fmt.Errorf("Prometheus authentication requires username and password")
		}
	}
	if (cfg.Prometheus.TLSCert == "") != (cfg.Prometheus.TLSKey == "") {
		return fmt.Errorf("both prometheus tls_cert and tls_key must be configured")
	}

	handler := promhttp.HandlerFor(s.registry, promhttp.HandlerOpts{})
	if username != "" {
		handler = basicAuthHandler(handler, username, password)
	}
	mux := http.NewServeMux()
	mux.Handle("/metrics", handler)
	mux.Handle("/", handler)
	s.server = &http.Server{Handler: mux, ReadHeaderTimeout: 5 * time.Second}

	listenConfig := net.ListenConfig{Control: platform.Control}
	listener, err := listenConfig.Listen(ctx, "tcp", fmt.Sprintf(":%d", *port))
	if err != nil {
		return fmt.Errorf("listen for Prometheus on port %d: %w", *port, err)
	}

	go func() {
		var serveErr error
		if cfg.Prometheus.TLSCert != "" {
			serveErr = s.server.ServeTLS(listener, cfg.Prometheus.TLSCert, cfg.Prometheus.TLSKey)
		} else {
			serveErr = s.server.Serve(listener)
		}
		if serveErr != nil && !errors.Is(serveErr, http.ErrServerClosed) {
			log.Error("Prometheus listener stopped", "cluster", s.clusterName, "error", serveErr)
		}
	}()
	go func() {
		<-ctx.Done()
		shutdownCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_ = s.server.Shutdown(shutdownCtx)
	}()
	return nil
}

func basicAuthHandler(next http.Handler, username, password string) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		u, p, ok := r.BasicAuth()
		if !ok || subtle.ConstantTimeCompare([]byte(u), []byte(username)) != 1 ||
			subtle.ConstantTimeCompare([]byte(p), []byte(password)) != 1 {
			w.Header().Set("WWW-Authenticate", `Basic realm="Restricted"`)
			http.Error(w, "Not authorized", http.StatusUnauthorized)
			return
		}
		next.ServeHTTP(w, r)
	})
}

func (s *PrometheusSink) Describe(ch chan<- *prometheus.Desc) {
	// Descriptors are dynamic because optional quota fields are exposed only
	// when OneFS returns a ready value. DescribeByCollect permits that model.
	prometheus.DescribeByCollect(s, ch)
}

func (s *PrometheusSink) Collect(ch chan<- prometheus.Metric) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	for _, metric := range s.snapshot.metrics {
		ch <- metric
	}

	healthLabels := []string{"cluster"}
	healthValues := []string{s.clusterName}
	if s.instanceLabelName != "" {
		healthLabels = append(healthLabels, s.instanceLabelName)
		healthValues = append(healthValues, s.clusterName)
	}
	health := []struct {
		name  string
		help  string
		value float64
	}{
		{"last_success_timestamp_seconds", "Unix time of the last successful complete quota collection.", s.lastSuccess},
		{"last_collection_duration_seconds", "Duration of the last quota collection attempt.", s.lastDuration},
		{"last_collection_success", "Whether the last quota collection attempt succeeded.", s.lastCollectionOK},
		{"quotas", "Number of quotas in the current successful snapshot.", float64(s.snapshot.count)},
		{"series", "Number of quota value series in the current successful snapshot.", float64(s.snapshot.series)},
	}
	for _, item := range health {
		desc := prometheus.NewDesc("isilon_quota_collector_"+item.name, item.help, healthLabels, nil)
		ch <- prometheus.MustNewConstMetric(desc, prometheus.GaugeValue, item.value, healthValues...)
	}
}

func (s *PrometheusSink) descriptor(field string, labelNames []string) *prometheus.Desc {
	key := field
	if s.instanceLabelName != "" {
		key += "|" + s.instanceLabelName
	}
	if desc, ok := s.descriptors[key]; ok {
		return desc
	}
	desc := prometheus.NewDesc(
		"isilon_quota_"+field,
		"OneFS quota "+field+" value.",
		labelNames,
		nil,
	)
	s.descriptors[key] = desc
	return desc
}

func (s *PrometheusSink) WritePoints(_ context.Context, points []backend.Point) error {
	metrics := make([]prometheus.Metric, 0, len(points)*8)
	labelNames := append([]string(nil), quotaLabelNames...)
	if s.instanceLabelName != "" {
		labelNames = append(labelNames, s.instanceLabelName)
	}

	for _, point := range points {
		for i, fields := range point.Fields {
			if i >= len(point.Tags) {
				return fmt.Errorf("point %q has fields without matching tags", point.Name)
			}
			tags := point.Tags[i]
			labelValues := make([]string, 0, len(labelNames))
			for _, label := range quotaLabelNames {
				labelValues = append(labelValues, tags[label])
			}
			if s.instanceLabelName != "" {
				labelValues = append(labelValues, s.clusterName)
			}

			fieldNames := make([]string, 0, len(fields))
			for field := range fields {
				fieldNames = append(fieldNames, field)
			}
			sort.Strings(fieldNames)
			for _, field := range fieldNames {
				value, ok := numericValue(fields[field])
				if !ok {
					return fmt.Errorf("unsupported Prometheus value type %T for field %q", fields[field], field)
				}
				metric := prometheus.MustNewConstMetric(s.descriptor(field, labelNames), prometheus.GaugeValue, value, labelValues...)
				// Quotas represent the collector's current snapshot. Let Prometheus
				// timestamp each scrape so an hourly collection remains queryable;
				// last_success_timestamp_seconds exposes the source freshness.
				metrics = append(metrics, metric)
			}
		}
	}

	s.mu.Lock()
	s.snapshot = prometheusSnapshot{metrics: metrics, count: len(points), series: len(metrics)}
	s.lastSuccess = float64(time.Now().Unix())
	s.lastCollectionOK = 1
	s.mu.Unlock()
	return nil
}

func numericValue(value any) (float64, bool) {
	switch v := value.(type) {
	case bool:
		if v {
			return 1, true
		}
		return 0, true
	case float32:
		return float64(v), true
	case float64:
		return v, true
	case int:
		return float64(v), true
	case int32:
		return float64(v), true
	case int64:
		return float64(v), true
	case uint:
		return float64(v), true
	case uint32:
		return float64(v), true
	case uint64:
		return float64(v), true
	default:
		return 0, false
	}
}

func (s *PrometheusSink) recordAttempt(duration time.Duration, success bool) {
	s.mu.Lock()
	s.lastDuration = duration.Seconds()
	if success {
		s.lastCollectionOK = 1
	} else {
		s.lastCollectionOK = 0
	}
	s.mu.Unlock()
}
