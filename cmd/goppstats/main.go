package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"log/slog"
	"os"
	"os/signal"
	"sync"
	"syscall"
	"time"

	"github.com/isilon/powerscale_data_insights/internal/api"
	"github.com/isilon/powerscale_data_insights/internal/backend"
	"github.com/isilon/powerscale_data_insights/internal/config"
	"github.com/isilon/powerscale_data_insights/internal/logging"
	"github.com/isilon/powerscale_data_insights/internal/platform"
)

// Version is the released program version
const Version = "0.32"
const userAgent = "goppstats/" + Version

// PPSampleRate is the poll interval in seconds; PP stats are only updated once every thirty seconds.
const PPSampleRate = 30

// Config file plugin names
const (
	discardPluginName  = "discard"
	influxPluginName   = "influxdb"
	influxV2PluginName = "influxdbv2"
	promPluginName     = "prometheus"
)

// Default logger
var log *slog.Logger

func die(msg string, args ...any) {
	log.Log(context.Background(), logging.LevelFatal, msg, args...)
	os.Exit(1)
}

func main() {
	logFileName := flag.String("logfile", "", "pathname of log file")
	logLevel := flag.String("loglevel", "", "log level [CRITICAL|ERROR|WARNING|NOTICE|INFO|DEBUG]")
	configFileName := flag.String("config-file", "goppstats.toml", "pathname of config file")
	versionFlag := flag.Bool("version", false, "Print application version")
	// parse command line
	flag.Parse()

	// if version requested, print and exit
	if *versionFlag {
		fmt.Printf("gostats version: %s\n", Version)
		return
	}

	// set up early logging so we can log config errors
	log = logging.SetupEarlyLogging()

	// read in our config
	conf := mustReadConfig(*configFileName)

	// set up full logging
	log = logging.Setup("goppstats", conf.Logging, *logLevel, *logFileName)

	// top-level context cancelled on SIGTERM or SIGINT
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	sigterm := make(chan os.Signal, 1)
	signal.Notify(sigterm, syscall.SIGTERM, os.Interrupt)
	defer signal.Stop(sigterm)

	// Cancel the top-level context when SIGTERM/SIGINT arrives.
	go func() {
		select {
		case <-sigterm:
			log.Log(context.Background(), logging.LevelNotice, "shutdown signal received")
			cancel()
		case <-ctx.Done():
		}
	}()

	// Unified reload channel: SIGHUP and the config file watcher both send here.
	reload := make(chan struct{}, 1)

	sighup := make(chan os.Signal, 1)
	platform.NotifySIGHUP(sighup)
	defer signal.Stop(sighup)
	// Forward SIGHUP to the unified reload channel.
	go func() {
		for {
			select {
			case _, ok := <-sighup:
				if !ok {
					return
				}
				log.Log(ctx, logging.LevelNotice, "SIGHUP received - reloading config")
				select {
				case reload <- struct{}{}:
				default: // reload already pending; skip
				}
			case <-ctx.Done():
				return
			}
		}
	}()

	// announce ourselves
	log.Log(ctx, logging.LevelNotice, "Starting goppstats", slog.String("version", Version))

	// Watch the config file for changes; feeds the same reload channel as SIGHUP.
	if err := platform.StartConfigWatcher(ctx, *configFileName, reload); err != nil {
		log.Warn("Config file watching not available", slog.String("error", err.Error()))
	}

outer:
	for {
		// Create a per-run context so collectors can be cancelled independently
		// of the top-level context (e.g. on SIGHUP reload).
		runCtx, cancelRun := context.WithCancel(ctx)

		if conf.Global.Processor == promPluginName && conf.PromSD.Enabled {
			if err := startPromSdListener(runCtx, conf); err != nil {
				log.Error("Failed to start Prometheus SD listener", slog.Any("error", err))
			}
		}

		// start collecting from each defined and enabled cluster
		var wg sync.WaitGroup
		for ci, cl := range conf.Clusters {
			if cl.Disabled {
				log.Info("skipping disabled cluster", slog.String("cluster", cl.Hostname))
				continue
			}
			wg.Add(1)
			go func(ci int, cl config.ClusterConfig) {
				log.Info("spawning collection loop for cluster", slog.String("cluster", cl.Hostname))
				defer wg.Done()
				statsloop(runCtx, &conf, ci)
				log.Info("collection loop for cluster ended", slog.String("cluster", cl.Hostname))
			}(ci, cl)
		}

		done := make(chan struct{})
		go func() {
			wg.Wait()
			close(done)
		}()

		select {
		case <-reload:
			cancelRun()
			<-done
			// If SIGTERM raced with SIGHUP, honour the shutdown.
			if ctx.Err() != nil {
				break outer
			}
			newConf, err := readConfig(*configFileName)
			if err != nil {
				log.Error("Config reload failed, continuing with existing config",
					slog.String("error", err.Error()))
				// conf is unchanged; the loop restarts with the existing config
			} else {
				conf = newConf
				log = logging.Setup("goppstats", conf.Logging, *logLevel, *logFileName)
				log.Log(ctx, logging.LevelNotice, "Config reloaded successfully")
			}
			continue
		case <-done:
			cancelRun()
			break outer
		case <-ctx.Done():
			cancelRun()
			<-done
			break outer
		}
	}
	log.Log(ctx, logging.LevelNotice, "All collectors complete - exiting")
}

func statsloop(ctx context.Context, conf *tomlConfig, ci int) {
	var err error
	var password string
	var ss DBWriter // ss = stats sink

	cc := conf.Clusters[ci]
	gc := conf.Global

	var preserveCase bool

	if cc.PreserveCase == nil { // check for cluster overwrite setting of PreserveCase, default and to global setting
		preserveCase = gc.PreserveCase
	} else {
		preserveCase = *cc.PreserveCase
	}

	// Connect to the cluster
	authtype := cc.AuthType
	if authtype == "" {
		log.Info("No authentication type defined for cluster, defaulting",
			slog.String("cluster", cc.Hostname),
			slog.String("default", api.AuthTypeSession))
		authtype = api.DefaultAuthType
	}
	if authtype != api.AuthTypeSession && authtype != api.AuthTypeBasic {
		log.Warn("Invalid authentication type for cluster, using default",
			slog.String("auth_type", authtype),
			slog.String("cluster", cc.Hostname),
			slog.String("default", api.AuthTypeSession))
		authtype = api.DefaultAuthType
	}
	if cc.Username == "" || cc.Password == "" {
		log.Error("Username and password for cluster must not be null", slog.String("cluster", cc.Hostname))
		return
	}
	password, err = config.SecretFromEnv(cc.Password)
	if err != nil {
		log.Error("Unable to retrieve password from environment for cluster",
			slog.String("cluster", cc.Hostname),
			slog.Any("error", err))
		return
	}
	c := &Cluster{
		Cluster: api.Cluster{
			AuthInfo: api.AuthInfo{
				Username: cc.Username,
				Password: password,
			},
			AuthType:     authtype,
			Hostname:     cc.Hostname,
			Port:         8080,
			VerifySSL:    cc.SSLCheck,
			MaxRetries:   gc.MaxRetries,
			PreserveCase: preserveCase,
			UserAgent:    userAgent,
		},
	}
	if err = c.Connect(ctx); err != nil {
		if !errors.Is(err, context.Canceled) {
			log.Error("Connection to cluster failed", slog.String("cluster", c.Hostname), slog.Any("error", err))
		}
		return
	}
	log.Info("Connected to cluster", slog.String("cluster", c.ClusterName), slog.String("version", c.OSVersion))

	// Configure/initialize backend database writer
	ss, err = getDBWriter(gc.Processor)
	if err != nil {
		log.Error("unsupported backend plugin", slog.Any("error", err))
		return
	}
	err = ss.Init(ctx, c, conf, ci)
	if err != nil {
		log.Error("Unable to initialize plugin", slog.String("plugin", gc.Processor), slog.Any("error", err))
		return
	}

	// Create export map for PP stat → Point conversion
	exports := newExportMap(gc.LookupExportIDs)

	// loop collecting and pushing stats
	log.Info("Starting stat collection loop for cluster", slog.String("cluster", c.ClusterName))
	for {
		curTime := time.Now()
		nextTime := curTime.Add(time.Second * PPSampleRate)

		// Grab current dataset definitions
		log.Info("Querying initial PP stat datasets for cluster", slog.String("cluster", c.ClusterName))
		di, err := c.GetDataSetInfo(ctx)
		if err != nil {
			if !errors.Is(err, context.Canceled) {
				log.Error("Unable to retrieve dataset information for cluster",
					slog.String("cluster", c.ClusterName),
					slog.Any("error", err))
			}
			return
		}
		log.Info("Got data set definitions", slog.Int("count", di.Total))
		for i, entry := range di.Datasets {
			log.Debug("dataset entry",
				slog.Int("index", i),
				slog.String("name", entry.Name),
				slog.String("statkey", entry.StatKey))
		}
		// UpdateDatasets is Prometheus-specific
		if ps, ok := ss.(*PrometheusSink); ok {
			ps.UpdateDatasets(di)
		}

		// Collect one set of stats
		log.Info("Cluster start collecting pp stats", slog.String("cluster", c.ClusterName))
		var sr []PPStatResult
		readFailCount := 0
		const maxRetryTime = time.Second * 1280
		retryTime := time.Second * 10
		for _, ds := range di.Datasets {
			dsName := ds.Name
			log.Debug("Cluster start collecting data set",
				slog.String("cluster", c.ClusterName),
				slog.String("dataset", dsName))
			for {
				sr, err = c.GetPPStats(ctx, dsName)
				if err == nil {
					break
				}
				if errors.Is(err, context.Canceled) {
					return
				}
				readFailCount++
				log.Error("Failed to retrieve PP stats",
					slog.String("dataset", dsName),
					slog.String("cluster", c.ClusterName),
					slog.Any("error", err),
					slog.Int("retry", readFailCount),
					slog.Duration("retry_in", retryTime))
				select {
				case <-time.After(retryTime):
				case <-ctx.Done():
					log.Log(ctx, logging.LevelNotice, "shutting down stats collection", slog.String("cluster", c.ClusterName))
					return
				}
				if retryTime < maxRetryTime {
					retryTime *= 2
				}
			}

			log.Info("Got workload entries", slog.Int("count", len(sr)))
			log.Info("Cluster start writing stats to back end", slog.String("cluster", c.ClusterName))

			// Convert PP stats to generic Points
			points := ppStatsToPoints(ctx, c.ClusterName, ds, sr, c, exports)

			// write points, now with retries
			retryTime = time.Second * time.Duration(gc.ProcessorRetryIntvl)
			for i := 1; i <= gc.ProcessorMaxRetries; i++ {
				err = ss.WritePoints(ctx, points)
				if err == nil {
					break
				}
				if errors.Is(err, context.Canceled) {
					return
				}
				log.Error("write error, retrying",
					slog.Any("error", err),
					slog.Int("retry", i),
					slog.Duration("retry_in", retryTime))
				select {
				case <-time.After(retryTime):
				case <-ctx.Done():
					log.Log(ctx, logging.LevelNotice, "shutting down stats collection", slog.String("cluster", c.ClusterName))
					return
				}
				if retryTime < maxRetryTime {
					retryTime *= 2
				}
			}
			if err != nil {
				log.Error("ProcessorMaxRetries exceeded, failed to write stats to database", slog.Any("error", err))
				return
			}
		}

		curTime = time.Now()
		if curTime.Before(nextTime) {
			select {
			case <-time.After(nextTime.Sub(curTime)):
			case <-ctx.Done():
				log.Log(ctx, logging.LevelNotice, "shutting down stats collection", slog.String("cluster", c.ClusterName))
				return
			}
		}
	}
}

// influxdbWrapper adapts the shared InfluxDB v1 backend to the local DBWriter interface.
type influxdbWrapper struct {
	writer backend.DBWriter
}

func (w *influxdbWrapper) Init(ctx context.Context, cluster *Cluster, cfg *tomlConfig, _ int) error {
	var err error
	w.writer, err = backend.NewInfluxDB(ctx, cluster.ClusterName, cfg.InfluxDB)
	return err
}

func (w *influxdbWrapper) WritePoints(ctx context.Context, points []backend.Point) error {
	return w.writer.WritePoints(ctx, points)
}

// influxdbv2Wrapper adapts the shared InfluxDB v2 backend to the local DBWriter interface.
type influxdbv2Wrapper struct {
	writer backend.DBWriter
}

func (w *influxdbv2Wrapper) Init(ctx context.Context, cluster *Cluster, cfg *tomlConfig, _ int) error {
	var err error
	w.writer, err = backend.NewInfluxDBv2(ctx, cluster.ClusterName, cfg.InfluxDBv2)
	return err
}

func (w *influxdbv2Wrapper) WritePoints(ctx context.Context, points []backend.Point) error {
	return w.writer.WritePoints(ctx, points)
}

// discardWrapper adapts the shared discard backend to the local DBWriter interface.
type discardWrapper struct {
	writer backend.DBWriter
}

func (w *discardWrapper) Init(_ context.Context, _ *Cluster, _ *tomlConfig, _ int) error {
	w.writer = backend.NewDiscard()
	return nil
}

func (w *discardWrapper) WritePoints(ctx context.Context, points []backend.Point) error {
	return w.writer.WritePoints(ctx, points)
}

// return a DBWriter for the given backend name
func getDBWriter(sp string) (DBWriter, error) {
	switch sp {
	case discardPluginName:
		return &discardWrapper{}, nil
	case influxPluginName:
		return &influxdbWrapper{}, nil
	case influxV2PluginName:
		return &influxdbv2Wrapper{}, nil
	case promPluginName:
		return GetPrometheusWriter(), nil
	default:
		return nil, fmt.Errorf("unsupported backend plugin %q", sp)
	}
}
