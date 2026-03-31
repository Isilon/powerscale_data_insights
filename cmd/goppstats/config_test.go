package main

import (
	"testing"
)

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
