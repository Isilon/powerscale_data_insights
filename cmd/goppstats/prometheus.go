package main

import (
	"context"
	"crypto/subtle"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"net"
	"net/http"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promhttp"
)

// promDsMap maps the dataset id (int) to the Prometheus-specific dataset information
type promDsMap map[int]promDsInternal

// PrometheusClient holds the metadata for the required networking (http) functionality
type PrometheusClient struct {
	ListenPort    uint64
	TLSCert       string `toml:"tls_cert"`
	TLSKey        string `toml:"tls_key"`
	BasicUsername string `toml:"basic_username"`
	BasicPassword string `toml:"basic_password"`

	server   *http.Server
	registry *prometheus.Registry
}

// PrometheusSink defines the data to allow us talk to an Prometheus database
// Since Prometheus uses a pull model, this actually means it defines the data
// to enable us to host a web page that the Prometheus server scrapes
type PrometheusSink struct {
	clusterName       string
	instanceLabelName string
	cluster           *Cluster // needed to enable per-cluster export id lookup
	exports           exportMap

	dsm    promDsMap
	client PrometheusClient

	sync.Mutex
	fam map[string]*MetricFamily
}

const namespace = "isilon"
const basePPName = "ppstat"

// promMetric holds the Prometheus metadata exposed by the "/metrics"
// endpoint for a given partitioned performance stat within a dataset
type promMetric struct {
	name        string
	description string
	labels      []string
}

// promDsInternal holds the dataset and related Prometheus gauges etc.
type promDsInternal struct {
	ds      DsInfoEntry
	metrics map[string]promMetric
}

// SampleID uniquely identifies a Sample
type SampleID string

// Sample represents the current value of a series.
type Sample struct {
	// Labels are the Prometheus labels.
	Labels map[string]string
	Value  float64
	// Metric timestamp
	Timestamp time.Time
	// Expiration is the deadline that this Sample is valid until.
	Expiration time.Time
}

// MetricFamily contains the data required to build valid prometheus Metrics.
type MetricFamily struct {
	// Samples are the Sample belonging to this MetricFamily.
	Samples map[SampleID]*Sample
	// LabelSet is the label counts for all Samples.
	LabelSet map[string]int
	// Desc contains the detailed description for this metric
	Desc string
}

// Wrapper to set socket reuse options
func createListener(ctx context.Context, addr string) (net.Listener, error) {
	// Create Listener Config
	lc := net.ListenConfig{
		Control: Control,
	}

	// Start Listener
	l, err := lc.Listen(ctx, "tcp", addr)
	return l, err
}

// GetPrometheusWriter returns a Prometheus DBWriter
func GetPrometheusWriter() DBWriter {
	return &PrometheusSink{}
}

func makePromDataset(ds DsInfoEntry) promDsInternal {
	dsi := promDsInternal{ds: ds}
	dsi.metrics = make(map[string]promMetric)
	return dsi
}

func (s *PrometheusSink) makePromMetrics(id int) {
	dsi := s.dsm[id]
	// Sort a copy to avoid mutating the stored DsInfoEntry.Metrics backing array
	metricNames := append([]string(nil), dsi.ds.Metrics...)
	sort.Strings(metricNames)
	basename := namespace + "_" + basePPName
	for _, m := range metricNames {
		basename = basename + "_" + m
	}
	labels := []string{"cluster", "node"}
	// Deal with overflow buckets first
	// These do not have the dataset breakout (since they collect/aggregate multiple values)
	for _, wb := range workloadTypes {
		for _, field := range ppFixedFields {
			fieldKey := wb + "_" + field
			description := fmt.Sprintf("pp dataset %d, overflow bucket %s, metric %s", dsi.ds.ID, wb, field)
			name := basename + "_" + fieldKey
			dsi.metrics[fieldKey] = promMetric{
				name,
				description,
				labels,
			}
		}
	}
	// Create the regular buckets
	labels = append(labels, metricNames...)
	for _, field := range ppFixedFields {
		description := fmt.Sprintf("pp dataset %d, metric %s", dsi.ds.ID, field)
		name := basename + "_" + field
		dsi.metrics[field] = promMetric{
			name,
			description,
			labels,
		}
	}
}

func (p *PrometheusClient) auth(h http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if p.BasicUsername != "" && p.BasicPassword != "" {
			w.Header().Set("WWW-Authenticate", `Basic realm="Restricted"`)

			username, password, ok := r.BasicAuth()
			if !ok ||
				subtle.ConstantTimeCompare([]byte(username), []byte(p.BasicUsername)) != 1 ||
				subtle.ConstantTimeCompare([]byte(password), []byte(p.BasicPassword)) != 1 {
				http.Error(w, "Not authorized", http.StatusUnauthorized)
				return
			}
		}

		h.ServeHTTP(w, r)
	})
}

type httpSdConf struct {
	ListenIP    string
	ListenPorts []uint64
}

// httpSdTarget is the JSON structure for a Prometheus HTTP SD target
type httpSdTarget struct {
	Targets []string          `json:"targets"`
	Labels  map[string]string `json:"labels"`
}

// ServeHTTP implements the http.Handler interface for the Prometheus HTTP SD handler
func (h *httpSdConf) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	target := httpSdTarget{
		Targets: make([]string, len(h.ListenPorts)),
		Labels:  map[string]string{"__meta_prometheus_job": "isilon_ppstats"},
	}
	for i, port := range h.ListenPorts {
		target.Targets[i] = fmt.Sprintf("%s:%d", h.ListenIP, port)
	}
	jsonBytes, err := json.Marshal([]httpSdTarget{target})
	if err != nil {
		log.Error("error encoding JSON response for HTTP SD", slog.String("error", err.Error()))
		http.Error(w, "error encoding JSON response", http.StatusInternalServerError)
		return
	}
	_, _ = w.Write(jsonBytes)
}

// Start an http listener in a goroutine to server Prometheus HTTP SD requests
func startPromSdListener(ctx context.Context, conf tomlConfig) error {
	var listenAddr string
	var err error
	listenAddr = conf.PromSD.ListenAddr
	if listenAddr == "" {
		listenAddr, err = findExternalAddr()
		if err != nil {
			return err
		}
	}
	var promPorts []uint64
	for _, cl := range conf.Clusters {
		if cl.PrometheusPort != nil {
			promPorts = append(promPorts, *cl.PrometheusPort)
		}
	}
	h := httpSdConf{ListenIP: listenAddr, ListenPorts: promPorts}
	// Create listener
	mux := http.NewServeMux()
	mux.Handle("/", &h)
	addr := fmt.Sprintf(":%d", conf.PromSD.SDport)
	listener, err := createListener(ctx, addr)
	if err != nil {
		return fmt.Errorf("error creating listener for Prometheus HTTP SD: %w", err)
	}
	sdServer := &http.Server{Handler: mux}
	log.Info("Starting Prometheus HTTP SD listener", slog.String("addr", addr))
	go func() {
		if err := sdServer.Serve(listener); err != nil && !errors.Is(err, http.ErrServerClosed) {
			log.Error("Prometheus HTTP SD listener error", slog.Any("error", err))
		}
	}()
	go func() {
		<-ctx.Done()
		shutdownCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_ = sdServer.Shutdown(shutdownCtx)
	}()
	return nil
}

// homepage provides a landing page pointing to the metrics handler
func homepage(w http.ResponseWriter, r *http.Request) {
	description := `<html>
<body>
<h1>Dell PowerScale OpenMetrics Exporter</h1>
<p>Partitioned-performance metrics for this cluster may be found at <a href="/metrics">/metrics</a></p>
</body>
</html>`

	_, _ = fmt.Fprintf(w, "%s", description)
}

// Connect sets up the HTTP server and handlers for Prometheus.
func (p *PrometheusClient) Connect(ctx context.Context) error {
	addr := fmt.Sprintf(":%d", p.ListenPort)

	mux := http.NewServeMux()
	mux.HandleFunc("/", homepage)
	mux.Handle("/metrics", p.auth(promhttp.HandlerFor(
		p.registry, promhttp.HandlerOpts{ErrorHandling: promhttp.ContinueOnError})))

	p.server = &http.Server{
		Addr:    addr,
		Handler: mux,
	}

	listener, err := createListener(ctx, addr)
	if err != nil {
		return fmt.Errorf("error creating listener for Prometheus client: %w", err)
	}

	go func() {
		var err error
		if p.TLSCert != "" && p.TLSKey != "" {
			err = p.server.ServeTLS(listener, p.TLSCert, p.TLSKey)
		} else {
			err = p.server.Serve(listener)
		}
		if err != nil && !errors.Is(err, http.ErrServerClosed) {
			log.Error("error creating prometheus metric endpoint", slog.Any("error", err))
		}
	}()

	go func() {
		<-ctx.Done()
		shutdownCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_ = p.server.Shutdown(shutdownCtx)
	}()

	return nil
}

// Init initializes an PrometheusSink so that points can be "written"
// (which means exposed via http in the case of Prometheus)
func (s *PrometheusSink) Init(ctx context.Context, cluster *Cluster, config *tomlConfig, ci int) error {
	s.clusterName = cluster.ClusterName
	s.cluster = cluster
	if config.Prometheus.InstanceLabelName != nil {
		s.instanceLabelName = *config.Prometheus.InstanceLabelName
	}
	promconf := config.Prometheus
	gc := config.Global
	s.exports = newExportMap(gc.LookupExportIDs)
	port := config.Clusters[ci].PrometheusPort
	if port == nil {
		return fmt.Errorf("prometheus plugin initialization failed - missing port definition for cluster %v", cluster)
	}
	pc := &s.client
	pc.ListenPort = *port

	if promconf.Authenticated {
		pc.BasicUsername = promconf.Username
		pc.BasicPassword = promconf.Password
	}
	pc.TLSCert = config.Prometheus.TLSCert
	pc.TLSKey = config.Prometheus.TLSKey

	registry := prometheus.NewRegistry()
	pc.registry = registry
	if err := registry.Register(s); err != nil {
		return fmt.Errorf("failed to register Prometheus collector: %w", err)
	}

	s.fam = make(map[string]*MetricFamily)

	// Set up http server here
	err := pc.Connect(ctx)

	return err
}

// CreateDataset assigns the provided dataset to the map
// and creates and tracks the associated Prometheus gauges
func (s *PrometheusSink) CreateDataset(id int, entry DsInfoEntry) {
	// if export_id lookup is enabled, we need to add the export_path here
	if s.exports.enabled {
		for _, m := range entry.Metrics {
			if m == "export_id" {
				entry.Metrics = append(entry.Metrics, "export_path")
			}
		}
	}
	s.dsm[id] = makePromDataset(entry)
	s.makePromMetrics(id)
}

// ClearDataset removes the dataset with the given id including
// unregistering all of the Prometheus gauges
func (s *PrometheusSink) ClearDataset(id int) {
	// clear the map entry
	delete(s.dsm, id)
}

// UpdateDatasets updates the back end view of the current dataset definitions.
func (s *PrometheusSink) UpdateDatasets(di *DsInfo) {
	s.Lock()
	defer s.Unlock()
	if s.dsm == nil {
		// First time through so allocate and set up the maps and gauges
		s.dsm = make(promDsMap)
		for _, ds := range di.Datasets {
			s.CreateDataset(ds.ID, ds)
		}
		return
	}

	// Regular call so compare to see if we need to update anything

	// make a map of the new dataset metadata
	nsdMap := make(map[int]DsInfoEntry)
	for _, v := range di.Datasets {
		nsdMap[v.ID] = v
	}

	// compare each possible slot to what we currently have
	// we are going to assert/assume that the System dataset is immutable so skip checking dataset 0
	for id := 1; id <= MaxDsID; id++ {
		cur, ok := s.dsm[id]
		if ok {
			new, ok := nsdMap[id]
			if !ok {
				// dataset has been deleted
				s.ClearDataset(id)
				continue
			}
			if cur.ds.CreationTime == new.CreationTime {
				// dataset creation time matches; dataset has not changed
				continue
			}
			// delete old entry
			s.ClearDataset(id)
			// create new
			s.CreateDataset(id, new)
		} else {
			// dataset does not currently exist, has it been added?
			new, ok := nsdMap[id]
			if !ok {
				// no, there's no new entry either
				continue
			}
			// New entry so populate it and generate gauges
			s.CreateDataset(id, new)
		}
	}
}

// Description returns a human-readable description of the Prometheus sink configuration.
func (s *PrometheusSink) Description() string {
	return "Configuration for the Prometheus client to spawn"
}

// Describe implements the prometheus.Collector interface.
func (s *PrometheusSink) Describe(ch chan<- *prometheus.Desc) {
	prometheus.NewGauge(prometheus.GaugeOpts{Name: "Dummy", Help: "Dummy"}).Describe(ch)
}

// Expire removes Samples that have expired.
func (s *PrometheusSink) Expire() {
	now := time.Now()
	for name, family := range s.fam {
		for key, sample := range family.Samples {
			if now.After(sample.Expiration) {
				for k := range sample.Labels {
					family.LabelSet[k]--
				}
				delete(family.Samples, key)

				if len(family.Samples) == 0 {
					delete(s.fam, name)
				}
			}
		}
	}
}

// Collect implements the prometheus.Collector interface
func (s *PrometheusSink) Collect(ch chan<- prometheus.Metric) {
	s.Lock()
	defer s.Unlock()

	s.Expire()

	for name, family := range s.fam {
		// Get list of all labels on MetricFamily
		var labelNames []string
		for k, v := range family.LabelSet {
			if v > 0 {
				labelNames = append(labelNames, k)
			}
		}

		for _, sample := range family.Samples {
			desc := prometheus.NewDesc(name, family.Desc, labelNames, nil)
			// Get labels for this sample; unset labels will be set to the
			// empty string
			var labels []string
			for _, label := range labelNames {
				v := sample.Labels[label]
				labels = append(labels, v)
			}

			metric, err := prometheus.NewConstMetric(desc, prometheus.GaugeValue, sample.Value, labels...)
			if err != nil {
				log.Error("error creating prometheus metric",
					slog.String("key", name),
					slog.Any("labels", labels),
					slog.Any("error", err))
				continue
			}

			metric = prometheus.NewMetricWithTimestamp(sample.Timestamp, metric)
			ch <- metric
		}
	}
}

// CreateSampleID creates a SampleID based on the tags of a OneFS.Metric.
func CreateSampleID(tags map[string]string) SampleID {
	pairs := make([]string, 0, len(tags))
	for k, v := range tags {
		pairs = append(pairs, fmt.Sprintf("%s=%s", k, v))
	}
	sort.Strings(pairs)
	return SampleID(strings.Join(pairs, ","))
}

func addSample(fam *MetricFamily, sample *Sample, sampleID SampleID) {
	if old, ok := fam.Samples[sampleID]; ok {
		for k := range old.Labels {
			fam.LabelSet[k]--
		}
	}
	for k := range sample.Labels {
		fam.LabelSet[k]++
	}
	fam.Samples[sampleID] = sample
}

func (s *PrometheusSink) addMetricFamily(sample *Sample, mname string, desc string, sampleID SampleID) {
	var fam *MetricFamily
	var ok bool
	if fam, ok = s.fam[mname]; !ok {
		fam = &MetricFamily{
			Samples:  make(map[SampleID]*Sample),
			LabelSet: make(map[string]int),
			Desc:     desc,
		}
		s.fam[mname] = fam
	}

	addSample(fam, sample, sampleID)
}

// WritePPStats takes an array of PPStatResults and "writes" them to Prometheus
// (in the case of Prometheus, this means adding them to the data exposed via http
// that the Prometheus server will scrape)
func (s *PrometheusSink) WritePPStats(ctx context.Context, ds DsInfoEntry, ppstats []PPStatResult) error {
	// Currently only one thread writing at any one time, but let's protect ourselves
	s.Lock()
	defer s.Unlock()

	now := time.Now()

	dsi := s.dsm[ds.ID]
	for _, ppstat := range ppstats {
		fieldMap := fieldsForPPStat(ppstat)
		tags := tagsForPPStat(ctx, ppstat, s.cluster, s.exports)
		sampleID := CreateSampleID(tags)
		labels := make(prometheus.Labels)
		labels["cluster"] = s.clusterName
		labels["node"] = strconv.Itoa(ppstat.Node)
		// If instance_label_name is configured, stamp the Isilon cluster name
		// under that label as well as the standard "cluster" label. This is
		// useful in Kubernetes environments where a Prometheus external label
		// named "cluster" identifies the Kubernetes cluster; Prometheus renames
		// any pre-existing "cluster" label on scraped metrics to "exported_cluster",
		// making direct filtering awkward. Choosing a non-conflicting label name
		// (e.g. "isilon_cluster") preserves the Isilon identity without renaming.
		if s.instanceLabelName != "" {
			labels[s.instanceLabelName] = s.clusterName
		}

		// check for the "overflows" buckets
		// "Pinned" is special. It is effectively a regular stat gather not a separate bucket.
		// We do add a label to show whether it was a pinned workflow or not.
		workloadType := ppstat.WorkloadType
		if workloadType != nil && *workloadType != wPinned {
			// validate the return
			if !isValidWorkloadType(*workloadType) {
				log.Error("invalid workload type found in output, ignoring", slog.String("workload_type", *workloadType))
				continue
			}
		} else {
			// Regular stat so include the additional dataset tags
			for _, label := range dsi.ds.Metrics {
				labels[label] = tags[label]
			}
			if workloadType != nil && *workloadType == wPinned {
				labels["pinned"] = "true"
			} else {
				labels["pinned"] = "false"
			}
		}

		for _, field := range ppFixedFields {
			// overflow bucket keys are of the form "<bucket>_<field>"
			fieldKey := field
			if workloadType != nil && *workloadType != wPinned {
				fieldKey = *workloadType + "_" + field
			}
			fullname := dsi.metrics[fieldKey].name
			description := dsi.metrics[fieldKey].description
			value, ok := fieldMap[field].(float64)
			if !ok {
				return fmt.Errorf("unexpected null value for field %q in dataset %q", field, ds.Name)
			}
			sample := &Sample{
				Labels:     labels,
				Value:      value,
				Timestamp:  time.Unix(ppstat.UnixTime, 0),
				Expiration: now.Add(30 * time.Second),
			}
			s.addMetricFamily(sample, fullname, description, sampleID)
		}
	}

	return nil
}
