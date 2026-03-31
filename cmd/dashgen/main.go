// goppstats-dash-gen generates Grafana dashboards for goppstats partitioned
// performance datasets by querying the OneFS PAPI to discover the dataset
// definition at runtime.
package main

import (
	"crypto/tls"
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"net/http"
	"net/http/cookiejar"
	"net/url"
	"os"
	"strings"
	"time"

	"golang.org/x/net/publicsuffix"
)

// ---------------------------------------------------------------------------
// CLI flags
// ---------------------------------------------------------------------------

type Config struct {
	Host       string
	Port       int
	Username   string
	Password   string
	DatasetID  int
	DSVersion  string // "v1" or "v2"
	OutFile    string
	SkipVerify bool
}

func parseFlags() Config {
	var cfg Config
	var useExportPath bool
	flag.StringVar(&cfg.Host, "host", "", "OneFS cluster hostname or IP (required)")
	flag.IntVar(&cfg.Port, "port", 8080, "PAPI port")
	flag.StringVar(&cfg.Username, "user", "", "PAPI username (required)")
	flag.StringVar(&cfg.Password, "password", "", "PAPI password (required)")
	flag.IntVar(&cfg.DatasetID, "dataset", 0, "Partitioned performance dataset ID (required)")
	flag.StringVar(&cfg.DSVersion, "influx-version", "v1", "InfluxDB version: v1 or v2")
	flag.StringVar(&cfg.OutFile, "out", "", "Output file path (default: stdout)")
	flag.BoolVar(&cfg.SkipVerify, "skip-verify", false, "Skip TLS certificate verification")
	flag.BoolVar(&useExportPath, "export-path", false, "Group by export_path tag instead of export_id (use when collector has lookup_export_ids=true)")
	flag.Parse()

	if cfg.Host == "" || cfg.Username == "" || cfg.Password == "" || cfg.DatasetID == 0 {
		fmt.Fprintf(os.Stderr, "Usage of %s:\n", os.Args[0])
		flag.PrintDefaults()
		os.Exit(1)
	}
	if useExportPath {
		exportTagName = "export_path"
	}
	return cfg
}

// ---------------------------------------------------------------------------
// PAPI client
// ---------------------------------------------------------------------------

type PAPIClient struct {
	cfg        Config
	httpClient *http.Client
	baseURL    string
	csrfToken  string
}

func NewPAPIClient(cfg Config) (*PAPIClient, error) {
	jar, err := cookiejar.New(&cookiejar.Options{PublicSuffixList: publicsuffix.List})
	if err != nil {
		return nil, fmt.Errorf("creating cookie jar: %w", err)
	}
	transport := &http.Transport{
		TLSClientConfig: &tls.Config{InsecureSkipVerify: cfg.SkipVerify},
	}
	c := &PAPIClient{
		cfg:     cfg,
		baseURL: fmt.Sprintf("https://%s:%d", cfg.Host, cfg.Port),
		httpClient: &http.Client{
			Transport: transport,
			Jar:       jar,
			Timeout:   30 * time.Second,
		},
	}
	return c, nil
}

// Authenticate performs session-based authentication.
// On success the cookie jar holds the session cookie and csrfToken is set.
func (c *PAPIClient) Authenticate() error {
	sessionURL := c.baseURL + "/session/1/session"
	body := fmt.Sprintf(`{"username":%q,"password":%q,"services":["platform"]}`,
		c.cfg.Username, c.cfg.Password)

	req, err := http.NewRequest("POST", sessionURL, strings.NewReader(body))
	if err != nil {
		return fmt.Errorf("creating auth request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return fmt.Errorf("auth request: %w", err)
	}
	defer resp.Body.Close()

	// 201 Created is the success response for session creation
	if resp.StatusCode != http.StatusCreated {
		return fmt.Errorf("authentication failed: HTTP %d", resp.StatusCode)
	}

	// Extract CSRF token from cookie jar (same as goppstats does)
	u, _ := url.Parse(sessionURL)
	for _, cookie := range c.httpClient.Jar.Cookies(u) {
		if cookie.Name == "isicsrf" {
			c.csrfToken = cookie.Value
		}
	}
	return nil
}

// GET performs an authenticated GET against the PAPI and JSON-decodes the response.
func (c *PAPIClient) GET(path string, result interface{}) error {
	req, err := http.NewRequest("GET", c.baseURL+path, nil)
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	if c.csrfToken != "" {
		req.Header.Set("X-CSRF-Token", c.csrfToken)
		req.Header.Set("Referer", c.baseURL)
	}

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return fmt.Errorf("GET %s: %w", path, err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("GET %s returned HTTP %d", path, resp.StatusCode)
	}
	return json.NewDecoder(resp.Body).Decode(result)
}

// ---------------------------------------------------------------------------
// PAPI response types — match DsInfoEntry / DsInfo in isilon_api.go exactly
// ---------------------------------------------------------------------------

// DsInfo is the envelope returned by /platform/10/performance/datasets
type DsInfo struct {
	Datasets []DsInfoEntry `json:"datasets"`
	Resume   string        `json:"resume"`
	Total    int           `json:"total"`
}

// DsInfoEntry matches the struct of the same name in goppstats/isilon_api.go.
// Metrics holds the partition dimension/attribute names (e.g. ["export_id","protocol","username"]) —
// these become InfluxDB tags and are used for GROUP BY in queries.
// Filters holds the dataset filters (not the attributes).
// StatKey is the InfluxDB measurement name (e.g. "cluster.performance.dataset.1").
type DsInfoEntry struct {
	CreationTime  int      `json:"creation_time"`
	FilterCount   int      `json:"filter_count"`
	Filters       []string `json:"filters"`
	Id            int      `json:"id"`
	Metrics       []string `json:"metrics"`
	Name          string   `json:"name"`
	StatKey       string   `json:"statkey"`
	WorkloadCount int      `json:"workload_count"`
}

// influxTagName maps a PAPI filter/attribute name to the InfluxDB tag name
// that goppstats writes. When lookup_export_ids is enabled in the collector
// config, export_id is resolved and written as export_path in addition to
// export_id. When it is disabled, only export_id is written.
// The dashboard must therefore group by whichever tag the collector writes.
// We default to export_id (always present); the -export-path flag can switch
// this to export_path for installations with lookup_export_ids=true.
var exportTagName = "export_id"

func influxTagName(filter string) string {
	if filter == "export_id" {
		return exportTagName
	}
	return filter
}

// ---------------------------------------------------------------------------
// Known metric metadata: units and aggregation hints
// ---------------------------------------------------------------------------

type MetricMeta struct {
	Title     string
	Unit      string // Grafana unit string
	Agg       string // "mean" or "sum"
	ScaleExpr string // optional math transformation, e.g. " / 1000"
}

var knownMetrics = map[string]MetricMeta{
	// Fields from backend.go ppFixedFields — always written for every PP stat
	"bytes_in":      {Title: "Bytes In", Unit: "Bps", Agg: "sum"},
	"bytes_out":     {Title: "Bytes Out", Unit: "Bps", Agg: "sum"},
	"reads":         {Title: "Read Operations", Unit: "ops/s", Agg: "sum"},
	"writes":        {Title: "Write Operations", Unit: "ops/s", Agg: "sum"},
	"ops":           {Title: "Protocol Operations", Unit: "ops/s", Agg: "sum"},
	"l2":            {Title: "L2 Cache Hit Rate", Unit: "ops/s", Agg: "sum"},
	"l3":            {Title: "L3 Cache Hit Rate", Unit: "ops/s", Agg: "sum"},
	"cpu":           {Title: "CPU", Unit: "ms", Agg: "mean", ScaleExpr: " / 1000"},
	"latency_read":  {Title: "Disk Latency (read)", Unit: "ms", Agg: "mean", ScaleExpr: " / 1000"},
	"latency_write": {Title: "Disk Latency (write)", Unit: "ms", Agg: "mean", ScaleExpr: " / 1000"},
	"latency_other": {Title: "Latency (other)", Unit: "ms", Agg: "mean", ScaleExpr: " / 1000"},
}

// panelMetrics is the ordered list of fixed performance fields from PPStatResult.
// These are always present in every dataset result regardless of the dataset's
// Metrics (attribute) definition. One panel is generated per entry.
var panelMetrics = []string{
	"cpu",
	"ops",
	"reads",
	"writes",
	"bytes_in",
	"bytes_out",
	"latency_read",
	"latency_write",
	"latency_other",
	"l2",
	"l3",
}

func metaFor(metric string) MetricMeta {
	if m, ok := knownMetrics[metric]; ok {
		return m
	}
	// Fallback for unknown metrics
	return MetricMeta{
		Title: strings.ReplaceAll(metric, "_", " "),
		Unit:  "short",
		Agg:   "mean",
	}
}

// ---------------------------------------------------------------------------
// Overflow bucket workload_type values returned by the PAPI
// ---------------------------------------------------------------------------

var overflowWorkloadTypes = []string{
	"Additional",
	"Excluded",
	"Overaccounted",
	"System",
	"Unknown",
}

// ---------------------------------------------------------------------------
// Grafana dashboard JSON model (v2beta1 / apiVersion dashboard.grafana.app)
// ---------------------------------------------------------------------------

// We use map[string]interface{} for the innermost query spec because the
// InfluxDB query spec has several optional fields and differs between v1/v2.

type Dashboard struct {
	APIVersion string          `json:"apiVersion"`
	Kind       string          `json:"kind"`
	Metadata   DashMeta        `json:"metadata"`
	Spec       DashSpec        `json:"spec"`
	Status     json.RawMessage `json:"status"`
}

type DashMeta struct {
	Name string `json:"name,omitempty"`
}

type DashSpec struct {
	Annotations  []Annotation         `json:"annotations"`
	CursorSync   string               `json:"cursorSync"`
	Description  string               `json:"description"`
	Editable     bool                 `json:"editable"`
	Elements     map[string]Panel     `json:"elements"`
	Layout       GridLayout           `json:"layout"`
	Links        []interface{}        `json:"links"`
	LiveNow      bool                 `json:"liveNow"`
	Preload      bool                 `json:"preload"`
	Tags         []string             `json:"tags"`
	TimeSettings TimeSettings         `json:"timeSettings"`
	Title        string               `json:"title"`
	Variables    []Variable           `json:"variables"`
}

type Annotation struct {
	Kind string         `json:"kind"`
	Spec AnnotationSpec `json:"spec"`
}

type AnnotationSpec struct {
	BuiltIn   bool        `json:"builtIn"`
	Enable    bool        `json:"enable"`
	Hide      bool        `json:"hide"`
	IconColor string      `json:"iconColor"`
	Name      string      `json:"name"`
	Query     interface{} `json:"query"`
}

type Panel struct {
	Kind string    `json:"kind"`
	Spec PanelSpec `json:"spec"`
}

type PanelSpec struct {
	Data        QueryGroup  `json:"data"`
	Description string      `json:"description"`
	ID          int         `json:"id"`
	Links       []interface{} `json:"links"`
	Title       string      `json:"title"`
	VizConfig   VizConfig   `json:"vizConfig"`
}

type QueryGroup struct {
	Kind string         `json:"kind"`
	Spec QueryGroupSpec `json:"spec"`
}

type QueryGroupSpec struct {
	Queries        []PanelQuery    `json:"queries"`
	QueryOptions   interface{}     `json:"queryOptions"`
	Transformations []interface{}  `json:"transformations"`
}

type PanelQuery struct {
	Kind string         `json:"kind"`
	Spec PanelQuerySpec `json:"spec"`
}

type PanelQuerySpec struct {
	Hidden bool        `json:"hidden"`
	Query  QueryBlock  `json:"query"`
	RefID  string      `json:"refId"`
}

type QueryBlock struct {
	Datasource DSRef                  `json:"datasource"`
	Group      string                 `json:"group"`
	Kind       string                 `json:"kind"`
	Spec       map[string]interface{} `json:"spec"`
	Version    string                 `json:"version"`
}

// dsDatasourceVar is the v2beta1 dashboard variable reference for the datasource.
// All panel queries reference this variable; its value is set by the
// DatasourceVariable in the variables list, which Grafana populates at import time.
const dsDatasourceVar = "${datasource}"

type DSRef struct {
	Name string `json:"name"`
}

type VizConfig struct {
	Group   string      `json:"group"`
	Kind    string      `json:"kind"`
	Spec    VizSpec     `json:"spec"`
	Version string      `json:"version"`
}

type VizSpec struct {
	FieldConfig FieldConfig `json:"fieldConfig"`
	Options     VizOptions  `json:"options"`
}

type FieldConfig struct {
	Defaults  FieldDefaults `json:"defaults"`
	Overrides []interface{} `json:"overrides"`
}

type FieldDefaults struct {
	Color   map[string]string `json:"color"`
	Custom  map[string]interface{} `json:"custom"`
	Thresholds Thresholds     `json:"thresholds"`
	Unit    string            `json:"unit"`
}

type Thresholds struct {
	Mode  string            `json:"mode"`
	Steps []ThresholdStep   `json:"steps"`
}

type ThresholdStep struct {
	Color string      `json:"color"`
	Value interface{} `json:"value"`
}

type VizOptions struct {
	Legend  LegendOptions  `json:"legend"`
	Tooltip TooltipOptions `json:"tooltip"`
}

type LegendOptions struct {
	Calcs       []string `json:"calcs"`
	DisplayMode string   `json:"displayMode"`
	Placement   string   `json:"placement"`
	ShowLegend  bool     `json:"showLegend"`
}

type TooltipOptions struct {
	HideZeros bool   `json:"hideZeros"`
	Mode      string `json:"mode"`
	Sort      string `json:"sort"`
}

type GridLayout struct {
	Kind string         `json:"kind"`
	Spec GridLayoutSpec `json:"spec"`
}

type GridLayoutSpec struct {
	Items []GridLayoutItem `json:"items"`
}

type GridLayoutItem struct {
	Kind string             `json:"kind"`
	Spec GridLayoutItemSpec `json:"spec"`
}

type GridLayoutItemSpec struct {
	Element ElementRef `json:"element"`
	Height  int        `json:"height"`
	Width   int        `json:"width"`
	X       int        `json:"x"`
	Y       int        `json:"y"`
}

type ElementRef struct {
	Kind string `json:"kind"`
	Name string `json:"name"`
}

type TimeSettings struct {
	AutoRefresh          string   `json:"autoRefresh"`
	AutoRefreshIntervals []string `json:"autoRefreshIntervals"`
	FiscalYearStartMonth int      `json:"fiscalYearStartMonth"`
	From                 string   `json:"from"`
	HideTimepicker       bool     `json:"hideTimepicker"`
	Timezone             string   `json:"timezone"`
	To                   string   `json:"to"`
}

// Variable is the top-level discriminated union entry in spec.variables.
// Spec is interface{} so each kind can supply its own distinct struct,
// avoiding CUE schema conflicts in the v2beta1 API.
type Variable struct {
	Kind string      `json:"kind"`
	Spec interface{} `json:"spec"`
}

// VarCurrent is the current selected value for a variable.
type VarCurrent struct {
	Text  string `json:"text"`
	Value string `json:"value"`
}

// VarOption is a single selectable option for a CustomVariable.
type VarOption struct {
	Selected bool   `json:"selected"`
	Text     string `json:"text"`
	Value    string `json:"value"`
}

// DatasourceVariableSpec matches the v2beta1 spec for kind=DatasourceVariable.
// Grafana presents this as a datasource picker at import time and whenever
// the variable is shown on the dashboard.
type DatasourceVariableSpec struct {
	Current     VarCurrent  `json:"current"`
	Hide        string      `json:"hide"`
	IncludeAll  bool        `json:"includeAll"`
	Multi       bool        `json:"multi"`
	Name        string      `json:"name"`
	Options     []VarOption `json:"options"`
	PluginID    string      `json:"pluginId"`
	Refresh     string      `json:"refresh"`
	Regex       string      `json:"regex"`
	SkipURLSync bool        `json:"skipUrlSync"`
}

// QueryVariableSpec matches the v2beta1 spec for kind=QueryVariable.
type QueryVariableSpec struct {
	AllowCustomValue bool          `json:"allowCustomValue"`
	Current          VarCurrent    `json:"current"`
	Definition       string        `json:"definition"`
	Hide             string        `json:"hide"`
	IncludeAll       bool          `json:"includeAll"`
	Multi            bool          `json:"multi"`
	Name             string        `json:"name"`
	Options          []VarOption   `json:"options"`
	Query            QueryVarQuery `json:"query"`
	Refresh          string        `json:"refresh"`
	Regex            string        `json:"regex"`
	SkipURLSync      bool          `json:"skipUrlSync"`
	Sort             string        `json:"sort"`
}

// QueryVarQuery is the nested query object inside a QueryVariable spec.
type QueryVarQuery struct {
	Datasource DSRef             `json:"datasource"`
	Group      string            `json:"group"`
	Kind       string            `json:"kind"`
	Spec       QueryVarQuerySpec `json:"spec"`
	Version    string            `json:"version"`
}

// QueryVarQuerySpec holds the legacy InfluxDB query string.
type QueryVarQuerySpec struct {
	LegacyStringValue string `json:"__legacyStringValue"`
}

// CustomVariableSpec matches the v2beta1 spec for kind=CustomVariable.
type CustomVariableSpec struct {
	AllowCustomValue bool        `json:"allowCustomValue"`
	Current          VarCurrent  `json:"current"`
	Hide             string      `json:"hide"`
	IncludeAll       bool        `json:"includeAll"`
	Label            string      `json:"label,omitempty"`
	Multi            bool        `json:"multi"`
	Name             string      `json:"name"`
	Options          []VarOption `json:"options"`
	Query            string      `json:"query"`
	SkipURLSync      bool        `json:"skipUrlSync"`
}

// ---------------------------------------------------------------------------
// Dashboard generation
// ---------------------------------------------------------------------------

const grafanaVersion = "12.3.2+security-01"

func refID(n int) string {
	// A-Z, then AA, AB, ...
	if n < 26 {
		return string(rune('A' + n))
	}
	return string(rune('A'+n/26-1)) + string(rune('A'+n%26))
}

// buildNormalQuery builds the query for non-overflow (normal partitioned) data.
// It groups by the primary attribute tags and excludes overflow workload_types.
func buildNormalQuery(measurement, field, agg, scaleExpr string, groupByTags []string) string {
	tagList := make([]string, len(groupByTags))
	for i, t := range groupByTags {
		tagList[i] = fmt.Sprintf("%q::tag", t)
	}
	groupBy := strings.Join(tagList, ", ")
	if groupBy != "" {
		groupBy = ", " + groupBy
	}

	selectExpr := fmt.Sprintf("%s(%q)", agg, field)
	if scaleExpr != "" {
		selectExpr += scaleExpr
	}

	return fmt.Sprintf(
		`SELECT %s FROM %q WHERE "cluster"::tag =~ /^$cluster$/ AND ("workload_type"::tag !~ /./ OR "workload_type"::tag = 'Pinned') AND $timeFilter GROUP BY time($__interval)%s fill(null)`,
		selectExpr, measurement, groupBy,
	)
}

// buildOverflowQuery builds the query for a specific overflow workload_type,
// gated by the [[overflow]] variable trick.
func buildOverflowQuery(measurement, field, agg, scaleExpr, workloadType string) string {
	selectExpr := fmt.Sprintf("%s(%q)", agg, field)
	if scaleExpr != "" {
		selectExpr += scaleExpr
	}

	return fmt.Sprintf(
		`SELECT %s FROM %q WHERE ("workload_type"::tag = '%s' AND "cluster"::tag =~ /^$cluster$/ AND [[overflow]] = 1) AND $timeFilter GROUP BY time($__interval) fill(null)`,
		selectExpr, measurement, workloadType,
	)
}

// buildGroupBySpec builds the groupBy array for the non-raw query spec.
func buildGroupBySpec(groupByTags []string) []map[string]interface{} {
	gb := []map[string]interface{}{
		{"params": []string{"$__interval"}, "type": "time"},
	}
	for _, t := range groupByTags {
		gb = append(gb, map[string]interface{}{
			"params": []string{t + "::tag"},
			"type":   "tag",
		})
	}
	gb = append(gb, map[string]interface{}{
		"params": []string{"null"},
		"type":   "fill",
	})
	return gb
}

// aliasForTags builds a Grafana alias string referencing the group-by tags.
func aliasForTags(groupByTags []string) string {
	if len(groupByTags) == 0 {
		return ""
	}
	parts := make([]string, len(groupByTags))
	for i, t := range groupByTags {
		parts[i] = t + ": $tag_" + t
	}
	return strings.Join(parts, " | ")
}

// makeSelectSpec returns the InfluxDB query builder "select" array.
func makeSelectSpec(field, agg, scaleExpr string) []interface{} {
	sel := []map[string]interface{}{
		{"params": []string{field}, "type": "field"},
		{"params": []string{}, "type": agg},
	}
	if scaleExpr != "" {
		sel = append(sel, map[string]interface{}{
			"params": []string{strings.TrimSpace(scaleExpr)},
			"type":   "math",
		})
	}
	result := make([]interface{}, len(sel))
	for i, s := range sel {
		result[i] = s
	}
	return []interface{}{result}
}

// makeInfluxV1QuerySpec builds the spec map for an InfluxDB v1 normal query.
func makeInfluxV1NormalQuerySpec(measurement, field, agg, scaleExpr, alias string, groupByTags []string) map[string]interface{} {
	return map[string]interface{}{
		"alias":       alias,
		"groupBy":     buildGroupBySpec(groupByTags),
		"measurement": measurement,
		"orderByTime": "ASC",
		"policy":      "default",
		"query":       buildNormalQuery(measurement, field, agg, scaleExpr, groupByTags),
		"rawQuery":    true,
		"resultFormat": "time_series",
		"select":      makeSelectSpec(field, agg, scaleExpr),
	}
}

// makeInfluxV1OverflowQuerySpec builds the spec map for an InfluxDB v1 overflow query.
func makeInfluxV1OverflowQuerySpec(measurement, field, agg, scaleExpr, workloadType string) map[string]interface{} {
	return map[string]interface{}{
		"alias":        workloadType,
		"groupBy":      buildGroupBySpec(nil),
		"measurement":  measurement,
		"orderByTime":  "ASC",
		"policy":       "default",
		"query":        buildOverflowQuery(measurement, field, agg, scaleExpr, workloadType),
		"rawQuery":     true,
		"resultFormat": "time_series",
		"select":       makeSelectSpec(field, agg, scaleExpr),
	}
}

// buildPanel constructs a single time-series panel for one metric.
func buildPanel(id int, ds DsInfoEntry, metric string, meta MetricMeta) Panel {
	// StatKey is the InfluxDB measurement name written by goppstats
	// (e.g. "cluster.performance.dataset.1").
	measurement := ds.StatKey

	// ds.Metrics holds the partition attribute names for this dataset
	// (e.g. ["export_id","protocol","username"]). These become the InfluxDB
	// tags that goppstats writes and that we GROUP BY in queries.
	groupByTags := make([]string, len(ds.Metrics))
	for i, f := range ds.Metrics {
		groupByTags[i] = influxTagName(f)
	}

	queries := []PanelQuery{}
	qIdx := 0

	// Query A: normal (partitioned) data grouped by dataset attributes
	normalSpec := makeInfluxV1NormalQuerySpec(
		measurement, metric, meta.Agg, meta.ScaleExpr,
		aliasForTags(groupByTags), groupByTags,
	)
	queries = append(queries, PanelQuery{
		Kind: "PanelQuery",
		Spec: PanelQuerySpec{
			Hidden: false,
			RefID:  refID(qIdx),
			Query: QueryBlock{
				Datasource: DSRef{Name: dsDatasourceVar},
				Group:      "influxdb",
				Kind:       "DataQuery",
				Spec:       normalSpec,
				Version:    "v0",
			},
		},
	})
	qIdx++

	// Queries B-F: one per overflow workload_type, gated by [[overflow]]
	for _, wt := range overflowWorkloadTypes {
		ovSpec := makeInfluxV1OverflowQuerySpec(measurement, metric, meta.Agg, meta.ScaleExpr, wt)
		queries = append(queries, PanelQuery{
			Kind: "PanelQuery",
			Spec: PanelQuerySpec{
				Hidden: false,
				RefID:  refID(qIdx),
				Query: QueryBlock{
					Datasource: DSRef{Name: dsDatasourceVar},
					Group:      "influxdb",
					Kind:       "DataQuery",
					Spec:       ovSpec,
					Version:    "v0",
				},
			},
		})
		qIdx++
	}

	return Panel{
		Kind: "Panel",
		Spec: PanelSpec{
			Data: QueryGroup{
				Kind: "QueryGroup",
				Spec: QueryGroupSpec{
					Queries:         queries,
					QueryOptions:    map[string]interface{}{},
					Transformations: []interface{}{},
				},
			},
			Description: "",
			ID:          id,
			Links:       []interface{}{},
			Title:       meta.Title,
			VizConfig: VizConfig{
				Group:   "timeseries",
				Kind:    "VizConfig",
				Version: grafanaVersion,
				Spec: VizSpec{
					FieldConfig: FieldConfig{
						Defaults: FieldDefaults{
							Color: map[string]string{"mode": "palette-classic"},
							Custom: map[string]interface{}{
								"axisBorderShow":    false,
								"axisCenteredZero":  false,
								"axisColorMode":     "text",
								"axisLabel":         "",
								"axisPlacement":     "auto",
								"barAlignment":      0,
								"barWidthFactor":    0.6,
								"drawStyle":         "line",
								"fillOpacity":       0,
								"gradientMode":      "none",
								"hideFrom":          map[string]bool{"legend": false, "tooltip": false, "viz": false},
								"insertNulls":       false,
								"lineInterpolation": "linear",
								"lineWidth":         1,
								"pointSize":         5,
								"scaleDistribution": map[string]string{"type": "linear"},
								"showPoints":        "auto",
								"showValues":        false,
								"spanNulls":         60000,
								"stacking":          map[string]string{"group": "A", "mode": "none"},
								"thresholdsStyle":   map[string]string{"mode": "off"},
							},
							Thresholds: Thresholds{
								Mode: "absolute",
								Steps: []ThresholdStep{
									{Color: "green", Value: 0},
									{Color: "red", Value: 80},
								},
							},
							Unit: meta.Unit,
						},
						Overrides: []interface{}{},
					},
					Options: VizOptions{
						Legend: LegendOptions{
							Calcs:       []string{},
							DisplayMode: "list",
							Placement:   "bottom",
							ShowLegend:  true,
						},
						Tooltip: TooltipOptions{
							HideZeros: false,
							Mode:      "single",
							Sort:      "none",
						},
					},
				},
			},
		},
	}
}

// buildDatasourceVariable returns the InfluxDB datasource picker DatasourceVariable.
// Grafana presents this in the import dialog and as a dropdown on the dashboard,
// allowing the user to select which configured InfluxDB datasource to use.
func buildDatasourceVariable() Variable {
	return Variable{
		Kind: "DatasourceVariable",
		Spec: DatasourceVariableSpec{
			Current:     VarCurrent{Text: "", Value: ""},
			Hide:        "dontHide",
			IncludeAll:  false,
			Multi:       false,
			Name:        "datasource",
			Options:     []VarOption{},
			PluginID:    "influxdb",
			Refresh:     "onDashboardLoad",
			Regex:       "",
			SkipURLSync: false,
		},
	}
}

// buildClusterVariable returns the cluster selector QueryVariable.
func buildClusterVariable() Variable {
	qStr := `show tag values with key = "cluster"`
	return Variable{
		Kind: "QueryVariable",
		Spec: QueryVariableSpec{
			AllowCustomValue: true,
			Current:          VarCurrent{Text: "", Value: ""},
			Definition:       qStr,
			Hide:             "dontHide",
			IncludeAll:       false,
			Multi:            false,
			Name:             "cluster",
			Options:          []VarOption{},
				Query: QueryVarQuery{
					Datasource: DSRef{Name: dsDatasourceVar},
				Group:      "influxdb",
				Kind:       "DataQuery",
				Spec:       QueryVarQuerySpec{LegacyStringValue: qStr},
				Version:    "v0",
			},
			Refresh:     "onDashboardLoad",
			Regex:       "",
			SkipURLSync: false,
			Sort:        "disabled",
		},
	}
}

// buildOverflowVariable returns the overflow toggle CustomVariable.
func buildOverflowVariable() Variable {
	return Variable{
		Kind: "CustomVariable",
		Spec: CustomVariableSpec{
			AllowCustomValue: true,
			Current:          VarCurrent{Text: "disabled", Value: "0"},
			Hide:             "dontHide",
			IncludeAll:       false,
			Label:            "Overflow Enabled",
			Multi:            false,
			Name:             "overflow",
			Options: []VarOption{
				{Selected: true, Text: "disabled", Value: "0"},
				{Selected: false, Text: "enabled", Value: "1"},
			},
			Query:       "disabled : 0, enabled : 1",
			SkipURLSync: false,
		},
	}
}

func buildAnnotations() []Annotation {
	return []Annotation{
		{
			Kind: "AnnotationQuery",
			Spec: AnnotationSpec{
				BuiltIn:   true,
				Enable:    true,
				Hide:      true,
				IconColor: "rgba(0, 211, 255, 1)",
				Name:      "Annotations & Alerts",
				Query: map[string]interface{}{
					"datasource": map[string]string{"name": "-- Grafana --"},
					"group":      "grafana",
					"kind":       "DataQuery",
					"spec":       map[string]interface{}{},
					"version":    "v0",
				},
			},
		},
	}
}

// GenerateDashboard produces the full Grafana dashboard for a dataset.
func GenerateDashboard(ds DsInfoEntry) Dashboard {
	panels := map[string]Panel{}
	layoutItems := []GridLayoutItem{}

	panelID := 1
	yPos := 0
	for _, metric := range panelMetrics {
		meta := metaFor(metric)
		panelKey := fmt.Sprintf("panel-%d", panelID)
		panels[panelKey] = buildPanel(panelID, ds, metric, meta)

		layoutItems = append(layoutItems, GridLayoutItem{
			Kind: "GridLayoutItem",
			Spec: GridLayoutItemSpec{
				Element: ElementRef{Kind: "ElementReference", Name: panelKey},
				Height:  7,
				Width:   24,
				X:       0,
				Y:       yPos,
			},
		})
		panelID++
		yPos += 7
	}

	// Build human-readable attribute list for the description using translated tag names.
	translatedAttrs := make([]string, len(ds.Metrics))
	for i, a := range ds.Metrics {
		translatedAttrs[i] = influxTagName(a)
	}
	attrStr := strings.Join(translatedAttrs, ", ")

	// ds.Name is a required field per the PAPI schema.
	title := fmt.Sprintf("Partitioned Performance: %s", ds.Name)
	description := fmt.Sprintf("Dataset %d (%s) – breakout by %s", ds.Id, ds.Name, attrStr)

	return Dashboard{
		APIVersion: "dashboard.grafana.app/v2beta1",
		Kind:       "Dashboard",
		Metadata:   DashMeta{},
		Status:     json.RawMessage("{}"),
		Spec: DashSpec{
			Annotations:  buildAnnotations(),
			CursorSync:   "Off",
			Description:  description,
			Editable:     true,
			Elements:     panels,
			Layout: GridLayout{
				Kind: "GridLayout",
				Spec: GridLayoutSpec{Items: layoutItems},
			},
			Links:   []interface{}{},
			LiveNow: false,
			Preload: false,
			Tags:    []string{"goppstats", "powerscale"},
			TimeSettings: TimeSettings{
				AutoRefresh: "30s",
				AutoRefreshIntervals: []string{
					"30s", "1m", "5m", "15m", "30m", "1h", "2h", "1d",
				},
				From:           "now-30m",
				HideTimepicker: false,
				To:             "now",
			},
			Title: title,
			Variables: []Variable{
				buildDatasourceVariable(),
				buildClusterVariable(),
				buildOverflowVariable(),
			},
		},
	}
}

// ---------------------------------------------------------------------------
// PAPI dataset discovery
// ---------------------------------------------------------------------------

// fetchDataset queries PAPI v10 for the full dataset list and returns the entry
// matching datasetID. This matches goppstats' GetDataSetInfo() which fetches
// /platform/10/performance/datasets (no per-ID endpoint used by goppstats).
func fetchDataset(client *PAPIClient, datasetID int) (DsInfoEntry, error) {
	var di DsInfo
	if err := client.GET("/platform/10/performance/datasets", &di); err != nil {
		return DsInfoEntry{}, fmt.Errorf("fetching dataset list: %w", err)
	}
	for _, entry := range di.Datasets {
		if entry.Id == datasetID {
			return entry, nil
		}
	}
	return DsInfoEntry{}, fmt.Errorf("dataset id %d not found (total returned: %d)", datasetID, di.Total)
}

// ---------------------------------------------------------------------------
// main
// ---------------------------------------------------------------------------

func main() {
	cfg := parseFlags()

	client, err := NewPAPIClient(cfg)
	if err != nil {
		log.Fatalf("Failed to create PAPI client: %v", err)
	}
	if err := client.Authenticate(); err != nil {
		log.Fatalf("PAPI authentication failed: %v", err)
	}

	log.Printf("Fetching dataset %d from %s...", cfg.DatasetID, cfg.Host)
	ds, err := fetchDataset(client, cfg.DatasetID)
	if err != nil {
		log.Fatalf("Failed to fetch dataset: %v", err)
	}

	if len(ds.Metrics) == 0 {
		log.Fatalf("Dataset %d has no partition attributes (Metrics) – check the dataset ID and your permissions", cfg.DatasetID)
	}

	log.Printf("Dataset %d: name=%q statkey=%q filters=%v metrics=%v",
		ds.Id, ds.Name, ds.StatKey, ds.Filters, ds.Metrics)

	dash := GenerateDashboard(ds)

	var out *os.File
	if cfg.OutFile != "" {
		out, err = os.Create(cfg.OutFile)
		if err != nil {
			log.Fatalf("Cannot create output file: %v", err)
		}
		defer out.Close()
	} else {
		out = os.Stdout
	}

	enc := json.NewEncoder(out)
	enc.SetIndent("", "  ")
	if err := enc.Encode(dash); err != nil {
		log.Fatalf("Failed to encode dashboard: %v", err)
	}

	if cfg.OutFile != "" {
		log.Printf("Dashboard written to %s", cfg.OutFile)
	}
}
