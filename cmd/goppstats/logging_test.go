package main

import (
	"log/slog"
	"testing"
)

func TestParseLevel(t *testing.T) {
	tests := []struct {
		input   string
		want    slog.Level
		wantErr bool
	}{
		{"TRACE", LevelTrace, false},
		{"trace", LevelTrace, false},
		{"DEBUG", slog.LevelDebug, false},
		{"debug", slog.LevelDebug, false},
		{"INFO", slog.LevelInfo, false},
		{"NOTICE", LevelNotice, false},
		{"WARN", slog.LevelWarn, false},
		{"WARNING", slog.LevelWarn, false},
		{"warning", slog.LevelWarn, false},
		{"ERROR", slog.LevelError, false},
		{"CRITICAL", LevelCritical, false},
		{"critical", LevelCritical, false},
		{"unknown", 0, true},
		{"", 0, true},
		{"FATAL", 0, true},
	}
	for _, tt := range tests {
		t.Run(tt.input, func(t *testing.T) {
			got, err := ParseLevel(tt.input)
			if tt.wantErr {
				if err == nil {
					t.Errorf("ParseLevel(%q) expected error, got nil (level %v)", tt.input, got)
				}
				return
			}
			if err != nil {
				t.Errorf("ParseLevel(%q) unexpected error: %v", tt.input, err)
				return
			}
			if got != tt.want {
				t.Errorf("ParseLevel(%q) = %v, want %v", tt.input, got, tt.want)
			}
		})
	}
}
