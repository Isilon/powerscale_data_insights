package config

import (
	"os"
	"testing"
)

func TestSecretFromEnv(t *testing.T) {
	tests := []struct {
		name    string
		input   string
		envKey  string
		envVal  string
		setEnv  bool
		want    string
		wantErr bool
	}{
		{
			name:  "literal string returned unchanged",
			input: "plaintext",
			want:  "plaintext",
		},
		{
			name:   "env prefix with set variable",
			input:  "$env:TEST_SECRET_VAR",
			envKey: "TEST_SECRET_VAR",
			envVal: "s3cret",
			setEnv: true,
			want:   "s3cret",
		},
		{
			name:    "env prefix with unset variable",
			input:   "$env:UNSET_VAR_12345",
			wantErr: true,
		},
		{
			name:  "empty string returned unchanged",
			input: "",
			want:  "",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if tt.setEnv {
				t.Setenv(tt.envKey, tt.envVal)
			} else if tt.envKey != "" {
				os.Unsetenv(tt.envKey)
			}
			got, err := SecretFromEnv(tt.input)
			if tt.wantErr {
				if err == nil {
					t.Errorf("SecretFromEnv(%q): expected error, got %q", tt.input, got)
				}
				return
			}
			if err != nil {
				t.Errorf("SecretFromEnv(%q): unexpected error: %v", tt.input, err)
			}
			if got != tt.want {
				t.Errorf("SecretFromEnv(%q) = %q, want %q", tt.input, got, tt.want)
			}
		})
	}
}
