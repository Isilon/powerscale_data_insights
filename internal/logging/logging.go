// Package logging provides structured logging setup with custom levels
// extending the standard slog levels.
package logging

import (
	"fmt"
	"log/slog"
	"os"
	"strings"

	slogmulti "github.com/samber/slog-multi"
)

// Log levels extending the standard slog levels.
const (
	LevelTrace    = slog.Level(-8)
	LevelDebug    = slog.LevelDebug
	LevelInfo     = slog.LevelInfo
	LevelNotice   = slog.Level(2)
	LevelWarning  = slog.LevelWarn
	LevelError    = slog.LevelError
	LevelCritical = slog.Level(10)
	LevelFatal    = slog.Level(12)
)

// LoggingConfig holds the logging section of the TOML configuration.
type LoggingConfig struct {
	LogFile       *string `toml:"logfile"`
	LogFileFormat *string `toml:"log_file_format"`
	LogLevel      *string `toml:"log_level"`
	LogToStdout   bool    `toml:"log_to_stdout"`
}

// ParseLevel converts a string to a slog.Level.
// It handles standard levels and is case-insensitive.
// If the string does not match a known level, it returns an error.
func ParseLevel(levelStr string) (slog.Level, error) {
	var level slog.Level
	var err error
	switch strings.ToUpper(levelStr) {
	case "TRACE":
		level = LevelTrace
	case "DEBUG":
		level = slog.LevelDebug
	case "INFO":
		level = slog.LevelInfo
	case "NOTICE":
		level = LevelNotice
	case "WARN", "WARNING":
		level = slog.LevelWarn
	case "ERROR":
		level = slog.LevelError
	case "CRITICAL":
		level = LevelCritical
	default:
		err = fmt.Errorf("unknown log level '%s'", levelStr)
	}
	return level, err
}

func handlerOptions(level slog.Level) *slog.HandlerOptions {
	return &slog.HandlerOptions{
		Level:     level,
		AddSource: true,
		ReplaceAttr: func(groups []string, a slog.Attr) slog.Attr {
			// Customize the name of the level key and the output string, including
			// custom level values.
			if a.Key == slog.LevelKey {
				// Handle custom level values.
				level, ok := a.Value.Any().(slog.Level)
				if !ok {
					return a
				}

				// This could also look up the name from a map or other structure, but
				// this demonstrates using a switch statement to rename levels. For
				// maximum performance, the string values should be constants, but this
				// example uses the raw strings for readability.
				switch {
				case level < LevelDebug:
					a.Value = slog.StringValue("TRACE")
				case level < LevelInfo:
					a.Value = slog.StringValue("DEBUG")
				case level < LevelNotice:
					a.Value = slog.StringValue("INFO")
				case level < LevelWarning:
					a.Value = slog.StringValue("NOTICE")
				case level < LevelError:
					a.Value = slog.StringValue("WARN")
				case level < LevelCritical:
					a.Value = slog.StringValue("ERROR")
				case level < LevelFatal:
					a.Value = slog.StringValue("CRITICAL")
				default:
					a.Value = slog.StringValue("FATAL")
				}
			}

			return a
		},
	}
}

// SetupEarlyLogging initializes logging to stdout at INFO level before the
// full logging configuration is available. Returns the logger.
func SetupEarlyLogging() *slog.Logger {
	options := handlerOptions(LevelInfo)
	consoleHandler := slog.NewTextHandler(os.Stdout, options)
	logger := slog.New(consoleHandler)
	slog.SetDefault(logger)
	return logger
}

// Setup initializes the logging system based on the provided configuration
// and optional command-line overrides. It returns the configured logger.
// The progName parameter is used in error messages (e.g., "gostats" or "goppstats").
func Setup(progName string, lc LoggingConfig, logLevel string, logFileName string) *slog.Logger {
	// Determine log level
	// If not set on command line, get from config file
	// If not set in config file, default to NOTICE
	if logLevel == "" {
		if lc.LogLevel == nil {
			logLevel = "NOTICE"
		} else {
			logLevel = *lc.LogLevel
		}
	}
	level, err := ParseLevel(logLevel)
	if err != nil {
		fmt.Fprintf(os.Stderr, "%s: invalid log level '%s' - %s\n", progName, logLevel, err)
		os.Exit(2)
	}

	// Up to two backends (one file, one stdout)
	backends := make([]slog.Handler, 0, 2)
	options := handlerOptions(level)

	// Up to two backends (one file, one stdout)
	// default is to not log to file
	logfile := ""
	// is it set in the config file?
	if lc.LogFile != nil {
		logfile = *lc.LogFile
	}
	// Finally, if it was set on the command line, override the setting
	if logFileName != "" {
		logfile = logFileName
	}
	if logfile != "" {
		f, err := os.OpenFile(logfile, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
		if err != nil {
			fmt.Fprintf(os.Stderr, "%s: unable to open log file %s for output - %s", progName, logfile, err)
			os.Exit(2)
		}
		var fileHandler slog.Handler
		format := "text"
		if lc.LogFileFormat != nil {
			format = strings.ToLower(*lc.LogFileFormat)
		}
		switch format {
		case "json":
			fileHandler = slog.NewJSONHandler(f, options)
		case "text":
			fileHandler = slog.NewTextHandler(f, options)
		default:
			fmt.Fprintf(os.Stderr, "%s: unknown log file format '%s'\n", progName, format)
			os.Exit(2)
		}
		backends = append(backends, fileHandler)
	}
	if lc.LogToStdout {
		consoleHandler := slog.NewTextHandler(os.Stdout, options)
		backends = append(backends, consoleHandler)
	}
	if len(backends) == 0 {
		fmt.Fprintf(os.Stderr, "%s: no logging defined, unable to continue\nPlease configure logging in the config file and/or via the command line\n", progName)
		os.Exit(3)
	}
	logger := slog.New(slogmulti.Fanout(backends...))
	slog.SetDefault(logger)
	return logger
}
