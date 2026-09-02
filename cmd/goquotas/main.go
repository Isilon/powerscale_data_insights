package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"log/slog"
	"maps"
	"math/rand/v2"
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

var version = "dev"
var commit = "none"

var log *slog.Logger

func main() {
	logFileName := flag.String("logfile", "", "pathname of log file")
	logLevel := flag.String("loglevel", "", "log level [CRITICAL|ERROR|WARNING|NOTICE|INFO|DEBUG|TRACE]")
	configFileName := flag.String("config-file", "goquotas.toml", "pathname of config file")
	versionFlag := flag.Bool("version", false, "print application version")
	flag.Parse()

	if *versionFlag {
		fmt.Printf("goquotas version: %s (commit %s)\n", version, commit)
		return
	}

	log = logging.SetupEarlyLogging()
	conf := mustReadConfig(*configFileName)
	log = logging.Setup("goquotas", conf.Logging, *logLevel, *logFileName)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	sigterm := make(chan os.Signal, 1)
	signal.Notify(sigterm, syscall.SIGTERM, os.Interrupt)
	defer signal.Stop(sigterm)
	go func() {
		select {
		case <-sigterm:
			log.Log(context.Background(), logging.LevelNotice, "shutdown signal received")
			cancel()
		case <-ctx.Done():
		}
	}()

	reload := make(chan struct{}, 1)
	sighup := make(chan os.Signal, 1)
	platform.NotifySIGHUP(sighup)
	defer signal.Stop(sighup)
	go func() {
		for {
			select {
			case _, ok := <-sighup:
				if !ok {
					return
				}
				select {
				case reload <- struct{}{}:
				default:
				}
			case <-ctx.Done():
				return
			}
		}
	}()

	if err := platform.StartConfigWatcher(ctx, *configFileName, reload); err != nil {
		log.Warn("config file watching not available", "error", err)
	}
	log.Log(ctx, logging.LevelNotice, "starting goquotas", "version", version)

outer:
	for {
		runCtx, cancelRun := context.WithCancel(ctx)
		if conf.Global.Processor == promPluginName && conf.PromSD.Enabled {
			if err := startPromSDListener(runCtx, conf); err != nil {
				log.Error("unable to start Prometheus HTTP SD listener", "error", err)
			}
		}
		var wg sync.WaitGroup
		for i, clusterConfig := range conf.Clusters {
			if clusterConfig.Disabled {
				continue
			}
			wg.Add(1)
			go func(clusterIndex int, hostname string) {
				defer wg.Done()
				collectCluster(runCtx, &conf, clusterIndex)
				log.Info("quota collection loop ended", "cluster", hostname)
			}(i, clusterConfig.Hostname)
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
			if ctx.Err() != nil {
				break outer
			}
			newConf, err := readConfig(*configFileName)
			if err != nil {
				log.Error("config reload failed; continuing with existing config", "error", err)
			} else {
				conf = newConf
				log = logging.Setup("goquotas", conf.Logging, *logLevel, *logFileName)
				log.Log(ctx, logging.LevelNotice, "config reloaded successfully")
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
	log.Log(context.Background(), logging.LevelNotice, "all quota collectors stopped")
}

func collectCluster(ctx context.Context, conf *tomlConfig, clusterIndex int) {
	clusterConfig := conf.Clusters[clusterIndex]
	global := conf.Global

	authType := clusterConfig.AuthType
	if authType == "" {
		authType = api.DefaultAuthType
	}
	if authType != api.AuthTypeSession && authType != api.AuthTypeBasic {
		log.Error("invalid authentication type", "cluster", clusterConfig.Hostname, "auth_type", authType)
		return
	}
	if clusterConfig.Username == "" || clusterConfig.Password == "" {
		log.Error("username and password must be configured", "cluster", clusterConfig.Hostname)
		return
	}
	password, err := config.SecretFromEnv(clusterConfig.Password)
	if err != nil {
		log.Error("unable to retrieve cluster password", "cluster", clusterConfig.Hostname, "error", err)
		return
	}
	preserveCase := global.PreserveCase
	if clusterConfig.PreserveCase != nil {
		preserveCase = *clusterConfig.PreserveCase
	}
	cluster := &Cluster{Cluster: api.Cluster{
		AuthInfo: api.AuthInfo{Username: clusterConfig.Username, Password: password},
		AuthType: authType, Hostname: clusterConfig.Hostname, Port: 8080,
		VerifySSL: clusterConfig.SSLCheck, MaxRetries: global.MaxRetries,
		PreserveCase: preserveCase, UserAgent: "goquotas/" + version,
	}}
	if err := cluster.Connect(ctx); err != nil {
		if !errors.Is(err, context.Canceled) {
			log.Error("connection to cluster failed", "cluster", clusterConfig.Hostname, "error", err)
		}
		return
	}

	writer, err := getDBWriter(global.Processor)
	if err != nil {
		log.Error("unsupported backend", "error", err)
		return
	}
	if err := writer.Init(ctx, cluster, conf, clusterIndex); err != nil {
		log.Error("unable to initialize backend", "cluster", cluster.ClusterName, "error", err)
		return
	}

	previous := make(map[string]quota)
	for {
		started := time.Now()
		quotas, collectionErr := cluster.GetQuotas(ctx, global.QuotaTypes, global.ResolveNames, global.PageLimit, global.MaxQuotas)
		if collectionErr == nil {
			completed := time.Now()
			points := quotasToPoints(cluster.ClusterName, quotas, completed)
			_, isPrometheus := writer.(*PrometheusSink)
			if !isPrometheus {
				current := make(map[string]quota, len(quotas))
				for _, q := range quotas {
					current[q.ID] = q
				}
				for id, oldQuota := range previous {
					newQuota, exists := current[id]
					if !exists || !maps.Equal(quotaTags(cluster.ClusterName, oldQuota), quotaTags(cluster.ClusterName, newQuota)) {
						points = append(points, quotaDeletionPoint(cluster.ClusterName, oldQuota, completed))
					}
				}
			}
			// Prometheus must receive an empty slice to atomically remove a
			// prior snapshot. Push backends have nothing to write when both the
			// current and previous snapshots are empty.
			if isPrometheus || len(points) > 0 {
				collectionErr = writeWithRetry(ctx, writer, points, global)
			}
			if collectionErr == nil {
				previous = make(map[string]quota, len(quotas))
				for _, q := range quotas {
					previous[q.ID] = q
				}
				log.Info("quota collection complete", "cluster", cluster.ClusterName, "quotas", len(quotas), "duration", time.Since(started))
			}
		}

		duration := time.Since(started)
		if prom, ok := writer.(*PrometheusSink); ok {
			prom.recordAttempt(duration, collectionErr == nil)
		}
		if collectionErr != nil && !errors.Is(collectionErr, context.Canceled) {
			log.Error("quota collection failed; retaining prior successful snapshot", "cluster", cluster.ClusterName, "duration", duration, "error", collectionErr)
		}
		if ctx.Err() != nil {
			return
		}

		delay := jitteredInterval(global.collectionDuration)
		timer := time.NewTimer(delay)
		select {
		case <-timer.C:
		case <-ctx.Done():
			if !timer.Stop() {
				<-timer.C
			}
			return
		}
	}
}

func writeWithRetry(ctx context.Context, writer DBWriter, points []backend.Point, global globalConfig) error {
	delay := time.Duration(global.ProcessorRetryIntvl) * time.Second
	var err error
	for attempt := 1; attempt <= global.ProcessorMaxRetries; attempt++ {
		if err = writer.WritePoints(ctx, points); err == nil {
			return nil
		}
		if errors.Is(err, context.Canceled) {
			return err
		}
		if attempt == global.ProcessorMaxRetries {
			break
		}
		log.Error("backend write failed; retrying", "attempt", attempt, "retry_in", delay, "error", err)
		timer := time.NewTimer(delay)
		select {
		case <-timer.C:
		case <-ctx.Done():
			if !timer.Stop() {
				<-timer.C
			}
			return ctx.Err()
		}
		if delay < 1280*time.Second {
			delay *= 2
		}
	}
	return fmt.Errorf("backend write retries exhausted: %w", err)
}

func jitteredInterval(interval time.Duration) time.Duration {
	return interval + time.Duration(rand.Float64()*0.05*float64(interval))
}
