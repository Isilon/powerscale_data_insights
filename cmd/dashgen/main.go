// goppstats-dash-gen generates Grafana dashboards for goppstats partitioned
// performance datasets by querying the OneFS PAPI to discover the dataset
// definition at runtime.
package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"os"
	"sort"
	"strings"

	"github.com/isilon/powerscale_data_insights/internal/api"
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
	Backend    string // "influxdb" or "prometheus"
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
	flag.StringVar(&cfg.Backend, "backend", "influxdb", "Dashboard backend: influxdb or prometheus")
	flag.Parse()

	if cfg.Host == "" || cfg.Username == "" || cfg.Password == "" || cfg.DatasetID == 0 {
		if cfg.DatasetID == 0 && cfg.Host != "" {
			fmt.Fprintf(os.Stderr, "Dataset 0 (System) has a fixed schema — use the pre-built dashboards in dashboards/influxdb/ or dashboards/prometheus/ instead.\n")
		} else {
			fmt.Fprintf(os.Stderr, "Usage of %s:\n", os.Args[0])
			flag.PrintDefaults()
		}
		os.Exit(1)
	}
	cfg.Backend = strings.ToLower(cfg.Backend)
	if cfg.Backend != "influxdb" && cfg.Backend != "prometheus" {
		fmt.Fprintf(os.Stderr, "Invalid backend %q: must be 'influxdb' or 'prometheus'\n", cfg.Backend)
		os.Exit(1)
	}
	if useExportPath {
		exportTagName = "export_path"
	}
	return cfg
}

// ---------------------------------------------------------------------------
// PAPI helpers using the shared api.Cluster client
// ---------------------------------------------------------------------------

// papiGET performs an authenticated GET and JSON-decodes the response.
func papiGET(ctx context.Context, cluster *api.Cluster, path string, result interface{}) error {
	body, err := cluster.RestGet(ctx, path)
	if err != nil {
		return err
	}
	return json.Unmarshal(body, result)
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
// Grafana legacy dashboard JSON model
// ---------------------------------------------------------------------------

type Dashboard struct {
	Inputs               []DashInput       `json:"__inputs"`
	Requires             []DashRequire     `json:"__requires"`
	ID                   interface{}       `json:"id"`
	UID                  interface{}       `json:"uid"`
	Title                string            `json:"title"`
	Description          string            `json:"description"`
	Tags                 []string          `json:"tags"`
	SchemaVersion        int               `json:"schemaVersion"`
	Version              int               `json:"version"`
	Editable             bool              `json:"editable"`
	GraphTooltip         int               `json:"graphTooltip"`
	Time                 map[string]string `json:"time"`
	Timepicker           map[string]any    `json:"timepicker"`
	Refresh              string            `json:"refresh"`
	FiscalYearStartMonth int               `json:"fiscalYearStartMonth"`
	Templating           Templating        `json:"templating"`
	Annotations          AnnotationList    `json:"annotations"`
	Panels               []Panel           `json:"panels"`
	Links                []any             `json:"links"`
}

type DashInput struct {
	Name        string `json:"name"`
	Label       string `json:"label"`
	Description string `json:"description"`
	Type        string `json:"type"`
	PluginID    string `json:"pluginId"`
	PluginName  string `json:"pluginName"`
}

type DashRequire struct {
	Type    string `json:"type"`
	ID      string `json:"id"`
	Name    string `json:"name"`
	Version string `json:"version"`
}

type Templating struct {
	List []TemplateVar `json:"list"`
}

type TemplateVar struct {
	Name       string         `json:"name"`
	Type       string         `json:"type"`
	Datasource *DSRef         `json:"datasource,omitempty"`
	Query      any            `json:"query"`
	Definition string         `json:"definition,omitempty"`
	Regex      string         `json:"regex"`
	Sort       int            `json:"sort"`
	Multi      bool           `json:"multi"`
	IncludeAll bool           `json:"includeAll"`
	AllValue   string         `json:"allValue,omitempty"`
	Current    map[string]any `json:"current"`
	Refresh    int            `json:"refresh"`
	Hide       int            `json:"hide"`
	Label      string         `json:"label,omitempty"`
	Options    []VarOption    `json:"options,omitempty"`
}

type VarOption struct {
	Selected bool   `json:"selected"`
	Text     string `json:"text"`
	Value    string `json:"value"`
}

type DSRef struct {
	Type string `json:"type"`
	UID  string `json:"uid"`
}

type AnnotationList struct {
	List []Annotation `json:"list"`
}

type Annotation struct {
	BuiltIn    int    `json:"builtIn"`
	Datasource DSRef  `json:"datasource"`
	Enable     bool   `json:"enable"`
	Hide       bool   `json:"hide"`
	IconColor  string `json:"iconColor"`
	Name       string `json:"name"`
	Type       string `json:"type"`
}

type Panel struct {
	ID          int            `json:"id"`
	Type        string         `json:"type"`
	Title       string         `json:"title"`
	Description string         `json:"description,omitempty"`
	GridPos     GridPos        `json:"gridPos"`
	Datasource  *DSRef         `json:"datasource,omitempty"`
	Targets     []Target       `json:"targets,omitempty"`
	FieldConfig *FieldConfig   `json:"fieldConfig,omitempty"`
	Options     map[string]any `json:"options,omitempty"`
}

type GridPos struct {
	H int `json:"h"`
	W int `json:"w"`
	X int `json:"x"`
	Y int `json:"y"`
}

type Target struct {
	RefID      string `json:"refId"`
	Datasource DSRef  `json:"datasource"`
	// InfluxDB fields
	RawQuery     bool   `json:"rawQuery,omitempty"`
	Query        string `json:"query,omitempty"`
	ResultFormat string `json:"resultFormat,omitempty"`
	Alias        string `json:"alias,omitempty"`
	// Prometheus fields
	Expr         string `json:"expr,omitempty"`
	LegendFormat string `json:"legendFormat,omitempty"`
	EditorMode   string `json:"editorMode,omitempty"`
}

type FieldConfig struct {
	Defaults  FieldDefaults `json:"defaults"`
	Overrides []any         `json:"overrides"`
}

type FieldDefaults struct {
	Color      map[string]string `json:"color,omitempty"`
	Custom     map[string]any    `json:"custom,omitempty"`
	Unit       string            `json:"unit,omitempty"`
	Thresholds *Thresholds       `json:"thresholds,omitempty"`
}

type Thresholds struct {
	Mode  string          `json:"mode"`
	Steps []ThresholdStep `json:"steps"`
}

type ThresholdStep struct {
	Color string `json:"color"`
	Value any    `json:"value"`
}

// ---------------------------------------------------------------------------
// Dashboard generation
// ---------------------------------------------------------------------------

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

	dsRef := DSRef{Type: "influxdb", UID: "${DS_INFLUXDB}"}
	targets := []Target{}
	qIdx := 0

	// Query A: normal (partitioned) data grouped by dataset attributes
	targets = append(targets, Target{
		RefID:        refID(qIdx),
		Datasource:   dsRef,
		RawQuery:     true,
		Query:        buildNormalQuery(measurement, metric, meta.Agg, meta.ScaleExpr, groupByTags),
		ResultFormat: "time_series",
		Alias:        aliasForTags(groupByTags),
	})
	qIdx++

	// Queries B-F: one per overflow workload_type, gated by [[overflow]]
	for _, wt := range overflowWorkloadTypes {
		targets = append(targets, Target{
			RefID:        refID(qIdx),
			Datasource:   dsRef,
			RawQuery:     true,
			Query:        buildOverflowQuery(measurement, metric, meta.Agg, meta.ScaleExpr, wt),
			ResultFormat: "time_series",
			Alias:        wt,
		})
		qIdx++
	}

	return Panel{
		ID:         id,
		Type:       "timeseries",
		Title:      meta.Title,
		GridPos:    GridPos{H: 8, W: 24, X: 0, Y: 0}, // Y set later by GenerateDashboard
		Datasource: &dsRef,
		Targets:    targets,
		FieldConfig: &FieldConfig{
			Defaults: FieldDefaults{
				Color: map[string]string{"mode": "palette-classic"},
				Unit:  meta.Unit,
				Custom: map[string]any{
					"drawStyle":         "line",
					"lineInterpolation": "linear",
					"lineWidth":         1,
					"fillOpacity":       10,
					"pointSize":         5,
					"showPoints":        "auto",
					"spanNulls":         60000,
					"stacking":          map[string]string{"group": "A", "mode": "none"},
				},
				Thresholds: &Thresholds{
					Mode: "absolute",
					Steps: []ThresholdStep{
						{Color: "green", Value: nil},
						{Color: "red", Value: 80},
					},
				},
			},
			Overrides: []any{},
		},
		Options: map[string]any{
			"legend": map[string]any{
				"displayMode": "list",
				"placement":   "bottom",
				"showLegend":  true,
			},
			"tooltip": map[string]any{
				"mode": "multi",
				"sort": "desc",
			},
		},
	}
}

// buildClusterVariable returns the cluster selector query variable.
func buildClusterVariable() TemplateVar {
	return TemplateVar{
		Name:       "cluster",
		Type:       "query",
		Datasource: &DSRef{Type: "influxdb", UID: "${DS_INFLUXDB}"},
		Query:      `SHOW TAG VALUES WITH KEY = "cluster"`,
		Definition: `SHOW TAG VALUES WITH KEY = "cluster"`,
		Sort:       1,
		Multi:      false,
		IncludeAll: false,
		Current:    map[string]any{},
		Refresh:    1,
		Hide:       0,
	}
}

// buildOverflowVariable returns the overflow toggle custom variable.
func buildOverflowVariable() TemplateVar {
	return TemplateVar{
		Name:    "overflow",
		Type:    "custom",
		Label:   "Overflow Enabled",
		Query:   "disabled : 0,enabled : 1",
		Multi:   false,
		Current: map[string]any{"text": "disabled", "value": "0"},
		Refresh: 0,
		Hide:    0,
		Options: []VarOption{
			{Selected: true, Text: "disabled", Value: "0"},
			{Selected: false, Text: "enabled", Value: "1"},
		},
	}
}

// buildReadmePanel constructs an introductory text panel that describes the
// dataset definition and explains the overflow toggle.
func buildReadmePanel(id int, ds DsInfoEntry) Panel {
	// Build attribute list using translated tag names.
	attrs := make([]string, len(ds.Metrics))
	for i, a := range ds.Metrics {
		attrs[i] = "`" + influxTagName(a) + "`"
	}
	attrList := strings.Join(attrs, ", ")

	var sb strings.Builder
	sb.WriteString(fmt.Sprintf("## Partitioned Performance: %s\n\n", ds.Name))
	sb.WriteString("| | |\n|---|---|\n")
	sb.WriteString(fmt.Sprintf("| **Dataset ID** | %d |\n", ds.Id))
	sb.WriteString(fmt.Sprintf("| **Name** | %s |\n", ds.Name))
	sb.WriteString(fmt.Sprintf("| **Stat Key** | `%s` |\n", ds.StatKey))
	sb.WriteString(fmt.Sprintf("| **Partition Attributes** | %s |\n", attrList))
	if len(ds.Filters) > 0 {
		filters := make([]string, len(ds.Filters))
		for i, f := range ds.Filters {
			filters[i] = "`" + f + "`"
		}
		sb.WriteString(fmt.Sprintf("| **Filters** | %s |\n", strings.Join(filters, ", ")))
	} else {
		sb.WriteString("| **Filters** | *(none)* |\n")
	}
	sb.WriteString(fmt.Sprintf("| **Workload Count** | %d |\n", ds.WorkloadCount))

	sb.WriteString("\nEach panel below shows one metric broken out by the partition attributes listed above.\n\n")
	sb.WriteString("### Overflow Toggle\n\n")
	sb.WriteString("The **Overflow Enabled** variable (top of dashboard) controls whether overflow workload ")
	sb.WriteString("buckets are displayed. OneFS tracks five overflow categories that capture work not ")
	sb.WriteString("attributed to a specific partitioned workload:\n\n")
	sb.WriteString("- **Additional** — work from workloads beyond the dataset's workload limit\n")
	sb.WriteString("- **Excluded** — work excluded by dataset filters\n")
	sb.WriteString("- **Overaccounted** — work counted in multiple workloads (deduplicated here)\n")
	sb.WriteString("- **System** — internal OneFS system overhead\n")
	sb.WriteString("- **Unknown** — work that could not be classified\n\n")
	sb.WriteString("Set to **enabled** to overlay these on each panel; set to **disabled** (default) to show only the partitioned workload data.")

	return Panel{
		ID:      id,
		Type:    "text",
		Title:   "",
		GridPos: GridPos{H: 10, W: 24, X: 0, Y: 0},
		Options: map[string]any{
			"mode":    "markdown",
			"content": sb.String(),
		},
	}
}

// GenerateDashboard produces the full Grafana legacy-format dashboard for a dataset.
func GenerateDashboard(ds DsInfoEntry) Dashboard {
	panels := []Panel{}
	panelID := 1
	yPos := 0

	// README panel: dataset definition and overflow explanation
	readme := buildReadmePanel(panelID, ds)
	readme.GridPos.Y = yPos
	panels = append(panels, readme)
	panelID++
	yPos += readme.GridPos.H

	for _, metric := range panelMetrics {
		meta := metaFor(metric)
		panel := buildPanel(panelID, ds, metric, meta)
		panel.GridPos.Y = yPos
		panels = append(panels, panel)
		panelID++
		yPos += 8
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
		Inputs: []DashInput{{
			Name:        "DS_INFLUXDB",
			Label:       "InfluxDB",
			Description: "InfluxDB datasource for PowerScale PP metrics",
			Type:        "datasource",
			PluginID:    "influxdb",
			PluginName:  "InfluxDB",
		}},
		Requires: []DashRequire{
			{Type: "grafana", ID: "grafana", Name: "Grafana", Version: "10.0.0"},
			{Type: "datasource", ID: "influxdb", Name: "InfluxDB", Version: "1.0.0"},
			{Type: "panel", ID: "timeseries", Name: "Time series", Version: ""},
		},
		ID:            nil,
		UID:           nil,
		Title:         title,
		Description:   description,
		Tags:          []string{"goppstats", "powerscale"},
		SchemaVersion: 39,
		Version:       1,
		Editable:      true,
		GraphTooltip:  1,
		Time:          map[string]string{"from": "now-30m", "to": "now"},
		Timepicker:    map[string]any{},
		Refresh:       "30s",
		FiscalYearStartMonth: 0,
		Templating: Templating{
			List: []TemplateVar{
				buildClusterVariable(),
				buildOverflowVariable(),
			},
		},
		Annotations: AnnotationList{
			List: []Annotation{{
				BuiltIn:    1,
				Datasource: DSRef{Type: "grafana", UID: "-- Grafana --"},
				Enable:     true,
				Hide:       true,
				IconColor:  "rgba(0, 211, 255, 1)",
				Name:       "Annotations & Alerts",
				Type:       "dashboard",
			}},
		},
		Panels: panels,
		Links:  []any{},
	}
}

// ---------------------------------------------------------------------------
// Prometheus metric naming (must match goppstats/prometheus.go conventions)
// ---------------------------------------------------------------------------

const (
	promNamespace  = "isilon"
	promBasePPName = "ppstat"
)

// promAgg maps InfluxDB aggregation function names to PromQL equivalents.
func promAgg(influxAgg string) string {
	if influxAgg == "mean" {
		return "avg"
	}
	return influxAgg
}

// promBasename constructs the Prometheus metric base name for a dataset.
// Metric names in goppstats follow: isilon_ppstat_<sorted_metrics>
// where the dataset's partition attribute names are sorted alphabetically.
func promBasename(ds DsInfoEntry) string {
	metricNames := append([]string(nil), ds.Metrics...)
	sort.Strings(metricNames)
	basename := promNamespace + "_" + promBasePPName
	for _, m := range metricNames {
		basename += "_" + m
	}
	return basename
}

// promMetricName returns the full Prometheus metric name for a regular PP field.
func promMetricName(ds DsInfoEntry, field string) string {
	return promBasename(ds) + "_" + field
}

// promOverflowMetricName returns the Prometheus metric name for an overflow
// bucket field. Overflow metrics embed the workload type in the metric name.
func promOverflowMetricName(ds DsInfoEntry, workloadType, field string) string {
	return promBasename(ds) + "_" + workloadType + "_" + field
}

// ---------------------------------------------------------------------------
// Prometheus query builders
// ---------------------------------------------------------------------------

// buildPromNormalQuery builds a PromQL query for non-overflow partitioned data.
func buildPromNormalQuery(ds DsInfoEntry, field, agg, scaleExpr string, groupByTags []string) string {
	metric := promMetricName(ds, field)
	labels := `{cluster=~"$cluster"}`

	var expr string
	if len(groupByTags) > 0 {
		groupBy := strings.Join(groupByTags, ", ")
		expr = fmt.Sprintf("%s by (%s) (%s%s)", promAgg(agg), groupBy, metric, labels)
	} else {
		expr = fmt.Sprintf("%s(%s%s)", promAgg(agg), metric, labels)
	}
	if scaleExpr != "" {
		expr += scaleExpr
	}
	return expr
}

// buildPromOverflowQuery builds a PromQL query for an overflow workload_type,
// gated by the $overflow variable. When $overflow=0 the query returns no data;
// when $overflow=1 it returns the overflow metric values.
func buildPromOverflowQuery(ds DsInfoEntry, field, agg, scaleExpr, workloadType string) string {
	metric := promOverflowMetricName(ds, workloadType, field)
	labels := `{cluster=~"$cluster"}`

	expr := fmt.Sprintf("%s(%s%s)", promAgg(agg), metric, labels)
	if scaleExpr != "" {
		expr += scaleExpr
	}
	// Gate: vector($overflow) == 1 evaluates to empty set when overflow=0,
	// causing the `and on()` to filter everything out.
	return fmt.Sprintf("(%s) and on() (vector($overflow) == 1)", expr)
}

// promLegendFormat builds a Grafana legend format string for Prometheus,
// using Prometheus {{label}} template syntax.
func promLegendFormat(groupByTags []string) string {
	if len(groupByTags) == 0 {
		return ""
	}
	parts := make([]string, len(groupByTags))
	for i, t := range groupByTags {
		parts[i] = t + ": {{" + t + "}}"
	}
	return strings.Join(parts, " | ")
}

// ---------------------------------------------------------------------------
// Prometheus panel and dashboard builders
// ---------------------------------------------------------------------------

// buildPromPanel constructs a single time-series panel for one metric using
// Prometheus as the datasource.
func buildPromPanel(id int, ds DsInfoEntry, metric string, meta MetricMeta) Panel {
	groupByTags := make([]string, len(ds.Metrics))
	for i, f := range ds.Metrics {
		groupByTags[i] = influxTagName(f)
	}

	dsRef := DSRef{Type: "prometheus", UID: "${DS_PROMETHEUS}"}
	targets := []Target{}
	qIdx := 0

	// Query A: normal (partitioned) data grouped by dataset attributes
	targets = append(targets, Target{
		RefID:        refID(qIdx),
		Datasource:   dsRef,
		Expr:         buildPromNormalQuery(ds, metric, meta.Agg, meta.ScaleExpr, groupByTags),
		LegendFormat: promLegendFormat(groupByTags),
		EditorMode:   "code",
	})
	qIdx++

	// Queries B-F: one per overflow workload_type, gated by $overflow variable
	for _, wt := range overflowWorkloadTypes {
		targets = append(targets, Target{
			RefID:        refID(qIdx),
			Datasource:   dsRef,
			Expr:         buildPromOverflowQuery(ds, metric, meta.Agg, meta.ScaleExpr, wt),
			LegendFormat: wt,
			EditorMode:   "code",
		})
		qIdx++
	}

	return Panel{
		ID:         id,
		Type:       "timeseries",
		Title:      meta.Title,
		GridPos:    GridPos{H: 8, W: 24, X: 0, Y: 0}, // Y set later
		Datasource: &dsRef,
		Targets:    targets,
		FieldConfig: &FieldConfig{
			Defaults: FieldDefaults{
				Color: map[string]string{"mode": "palette-classic"},
				Unit:  meta.Unit,
				Custom: map[string]any{
					"drawStyle":         "line",
					"lineInterpolation": "linear",
					"lineWidth":         1,
					"fillOpacity":       10,
					"pointSize":         5,
					"showPoints":        "auto",
					"spanNulls":         60000,
					"stacking":          map[string]string{"group": "A", "mode": "none"},
				},
				Thresholds: &Thresholds{
					Mode: "absolute",
					Steps: []ThresholdStep{
						{Color: "green", Value: nil},
						{Color: "red", Value: 80},
					},
				},
			},
			Overrides: []any{},
		},
		Options: map[string]any{
			"legend": map[string]any{
				"displayMode": "list",
				"placement":   "bottom",
				"showLegend":  true,
			},
			"tooltip": map[string]any{
				"mode": "multi",
				"sort": "desc",
			},
		},
	}
}

// buildPromClusterVariable returns the cluster selector query variable for Prometheus.
func buildPromClusterVariable(ds DsInfoEntry) TemplateVar {
	// Use the first panel metric to discover which clusters have PP data.
	metric := promMetricName(ds, panelMetrics[0])
	return TemplateVar{
		Name:       "cluster",
		Type:       "query",
		Datasource: &DSRef{Type: "prometheus", UID: "${DS_PROMETHEUS}"},
		Query:      fmt.Sprintf("label_values(%s, cluster)", metric),
		Definition: fmt.Sprintf("label_values(%s, cluster)", metric),
		Sort:       1,
		Multi:      false,
		IncludeAll: false,
		AllValue:   ".*",
		Current:    map[string]any{},
		Refresh:    1,
		Hide:       0,
	}
}

// GeneratePromDashboard produces a Prometheus Grafana legacy-format dashboard
// for a dataset.
func GeneratePromDashboard(ds DsInfoEntry) Dashboard {
	panels := []Panel{}
	panelID := 1
	yPos := 0

	// README panel: dataset definition and overflow explanation
	readme := buildReadmePanel(panelID, ds)
	readme.GridPos.Y = yPos
	panels = append(panels, readme)
	panelID++
	yPos += readme.GridPos.H

	for _, metric := range panelMetrics {
		meta := metaFor(metric)
		panel := buildPromPanel(panelID, ds, metric, meta)
		panel.GridPos.Y = yPos
		panels = append(panels, panel)
		panelID++
		yPos += 8
	}

	// Build human-readable attribute list for the description using translated tag names.
	translatedAttrs := make([]string, len(ds.Metrics))
	for i, a := range ds.Metrics {
		translatedAttrs[i] = influxTagName(a)
	}
	attrStr := strings.Join(translatedAttrs, ", ")

	title := fmt.Sprintf("Partitioned Performance: %s (Prometheus)", ds.Name)
	description := fmt.Sprintf("Dataset %d (%s) – breakout by %s", ds.Id, ds.Name, attrStr)

	return Dashboard{
		Inputs: []DashInput{{
			Name:        "DS_PROMETHEUS",
			Label:       "Prometheus",
			Description: "Prometheus datasource for PowerScale PP metrics",
			Type:        "datasource",
			PluginID:    "prometheus",
			PluginName:  "Prometheus",
		}},
		Requires: []DashRequire{
			{Type: "grafana", ID: "grafana", Name: "Grafana", Version: "10.0.0"},
			{Type: "datasource", ID: "prometheus", Name: "Prometheus", Version: "1.0.0"},
			{Type: "panel", ID: "timeseries", Name: "Time series", Version: ""},
		},
		ID:            nil,
		UID:           nil,
		Title:         title,
		Description:   description,
		Tags:          []string{"goppstats", "powerscale", "prometheus"},
		SchemaVersion: 39,
		Version:       1,
		Editable:      true,
		GraphTooltip:  1,
		Time:          map[string]string{"from": "now-30m", "to": "now"},
		Timepicker:    map[string]any{},
		Refresh:       "30s",
		FiscalYearStartMonth: 0,
		Templating: Templating{
			List: []TemplateVar{
				buildPromClusterVariable(ds),
				buildOverflowVariable(),
			},
		},
		Annotations: AnnotationList{
			List: []Annotation{{
				BuiltIn:    1,
				Datasource: DSRef{Type: "grafana", UID: "-- Grafana --"},
				Enable:     true,
				Hide:       true,
				IconColor:  "rgba(0, 211, 255, 1)",
				Name:       "Annotations & Alerts",
				Type:       "dashboard",
			}},
		},
		Panels: panels,
		Links:  []any{},
	}
}

// ---------------------------------------------------------------------------
// PAPI dataset discovery
// ---------------------------------------------------------------------------

// fetchDataset queries PAPI v10 for the full dataset list and returns the entry
// matching datasetID. This matches goppstats' GetDataSetInfo() which fetches
// /platform/10/performance/datasets (no per-ID endpoint used by goppstats).
func fetchDataset(ctx context.Context, cluster *api.Cluster, datasetID int) (DsInfoEntry, error) {
	var di DsInfo
	if err := papiGET(ctx, cluster, "/platform/10/performance/datasets", &di); err != nil {
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
	ctx := context.Background()

	cluster := &api.Cluster{
		AuthInfo: api.AuthInfo{
			Username: cfg.Username,
			Password: cfg.Password,
		},
		AuthType:   api.AuthTypeSession,
		Hostname:   cfg.Host,
		Port:       cfg.Port,
		VerifySSL:  !cfg.SkipVerify,
		UserAgent:  "dashgen/1.0",
		MaxRetries: 3,
	}

	if err := cluster.Connect(ctx); err != nil {
		log.Fatalf("Failed to connect to cluster: %v", err)
	}
	log.Printf("Connected to cluster %s (OneFS %s)", cluster.ClusterName, cluster.OSVersion)

	log.Printf("Fetching dataset %d from %s...", cfg.DatasetID, cfg.Host)
	ds, err := fetchDataset(ctx, cluster, cfg.DatasetID)
	if err != nil {
		log.Fatalf("Failed to fetch dataset: %v", err)
	}

	if len(ds.Metrics) == 0 {
		log.Fatalf("Dataset %d has no partition attributes (Metrics) – check the dataset ID and your permissions", cfg.DatasetID)
	}

	log.Printf("Dataset %d: name=%q statkey=%q filters=%v metrics=%v",
		ds.Id, ds.Name, ds.StatKey, ds.Filters, ds.Metrics)

	var dash Dashboard
	if cfg.Backend == "prometheus" {
		log.Printf("Generating Prometheus dashboard for dataset %d...", cfg.DatasetID)
		dash = GeneratePromDashboard(ds)
	} else {
		log.Printf("Generating InfluxDB dashboard for dataset %d...", cfg.DatasetID)
		dash = GenerateDashboard(ds)
	}

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
