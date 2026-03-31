package main

import (
	"os"
	"testing"
)

func TestSecretFromEnv(t *testing.T) {
	const envKey = "GOPPSTATS_TEST_SECRET"
	const envVal = "s3cr3t"

	t.Run("literal string returned unchanged", func(t *testing.T) {
		got, err := secretFromEnv("mypassword")
		if err != nil {
			t.Fatalf("unexpected error: %v", err)
		}
		if got != "mypassword" {
			t.Errorf("got %q, want %q", got, "mypassword")
		}
	})

	t.Run("env prefix with set variable", func(t *testing.T) {
		t.Setenv(envKey, envVal)
		got, err := secretFromEnv(envPrefix + envKey)
		if err != nil {
			t.Fatalf("unexpected error: %v", err)
		}
		if got != envVal {
			t.Errorf("got %q, want %q", got, envVal)
		}
	})

	t.Run("env prefix with unset variable", func(t *testing.T) {
		os.Unsetenv(envKey)
		_, err := secretFromEnv(envPrefix + envKey)
		if err == nil {
			t.Error("expected error for unset env var, got nil")
		}
	})

	t.Run("empty string returned unchanged", func(t *testing.T) {
		got, err := secretFromEnv("")
		if err != nil {
			t.Fatalf("unexpected error: %v", err)
		}
		if got != "" {
			t.Errorf("got %q, want empty string", got)
		}
	})
}

func TestValidateConfigVersion_Valid(t *testing.T) {
	valid := []string{"0.29", "0.30", "0.31", "0.32", "v0.29", "V0.31"}
	for _, v := range valid {
		t.Run(v, func(t *testing.T) {
			if err := validateConfigVersion(v); err != nil {
				t.Errorf("unexpected error for valid version %q: %v", v, err)
			}
		})
	}
}

func TestValidateConfigVersion_Invalid(t *testing.T) {
	cases := []struct {
		name    string
		version string
	}{
		{"empty", ""},
		{"unsupported", "0.99"},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if err := validateConfigVersion(tc.version); err == nil {
				t.Errorf("expected error for invalid version %q, got nil", tc.version)
			}
		})
	}
}
