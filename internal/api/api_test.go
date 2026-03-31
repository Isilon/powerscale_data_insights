package api

import (
	"errors"
	"fmt"
	"syscall"
	"testing"
)

func TestCluster_String(t *testing.T) {
	c := &Cluster{ClusterName: "mycluster"}
	if c.String() != "mycluster" {
		t.Errorf("expected 'mycluster', got %q", c.String())
	}
}

func TestCluster_String_Empty(t *testing.T) {
	c := &Cluster{}
	if c.String() != "" {
		t.Errorf("expected empty string, got %q", c.String())
	}
}

func TestInitialize_MissingUsername(t *testing.T) {
	c := &Cluster{
		AuthInfo: AuthInfo{Username: "", Password: "pass"},
		Hostname: "cluster.example.com",
	}
	if err := c.Initialize(); err == nil {
		t.Errorf("expected error for missing username, got none")
	}
}

func TestInitialize_MissingPassword(t *testing.T) {
	c := &Cluster{
		AuthInfo: AuthInfo{Username: "admin", Password: ""},
		Hostname: "cluster.example.com",
	}
	if err := c.Initialize(); err == nil {
		t.Errorf("expected error for missing password, got none")
	}
}

func TestInitialize_MissingHostname(t *testing.T) {
	c := &Cluster{
		AuthInfo: AuthInfo{Username: "admin", Password: "pass"},
		Hostname: "",
	}
	if err := c.Initialize(); err == nil {
		t.Errorf("expected error for missing hostname, got none")
	}
}

func TestInitialize_DefaultPort(t *testing.T) {
	c := &Cluster{
		AuthInfo: AuthInfo{Username: "admin", Password: "pass"},
		Hostname: "cluster.example.com",
		Port:     0,
	}
	if err := c.Initialize(); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if c.Port != 8080 {
		t.Errorf("expected default port 8080, got %d", c.Port)
	}
}

func TestInitialize_ExplicitPort(t *testing.T) {
	c := &Cluster{
		AuthInfo: AuthInfo{Username: "admin", Password: "pass"},
		Hostname: "cluster.example.com",
		Port:     9090,
	}
	if err := c.Initialize(); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if c.Port != 9090 {
		t.Errorf("expected port 9090, got %d", c.Port)
	}
}

func TestInitialize_SetsBaseURL(t *testing.T) {
	c := &Cluster{
		AuthInfo: AuthInfo{Username: "admin", Password: "pass"},
		Hostname: "cluster.example.com",
		Port:     8080,
	}
	if err := c.Initialize(); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if c.BaseURL() != "https://cluster.example.com:8080" {
		t.Errorf("unexpected baseURL: %q", c.BaseURL())
	}
}

func TestInitialize_AlreadyInitialized(t *testing.T) {
	c := &Cluster{
		AuthInfo: AuthInfo{Username: "admin", Password: "pass"},
		Hostname: "cluster.example.com",
		Port:     8080,
	}
	if err := c.Initialize(); err != nil {
		t.Fatalf("first initialize failed: %v", err)
	}
	// Second call should be a no-op (client already set) and not return an error
	if err := c.Initialize(); err != nil {
		t.Errorf("second initialize returned unexpected error: %v", err)
	}
}

func TestIsConnectionRefused_True(t *testing.T) {
	if !IsConnectionRefused(syscall.ECONNREFUSED) {
		t.Errorf("expected true for ECONNREFUSED")
	}
}

func TestIsConnectionRefused_Wrapped(t *testing.T) {
	wrapped := fmt.Errorf("dial failed: %w", syscall.ECONNREFUSED)
	if !IsConnectionRefused(wrapped) {
		t.Errorf("expected true for wrapped ECONNREFUSED")
	}
}

func TestIsConnectionRefused_False(t *testing.T) {
	if IsConnectionRefused(errors.New("some other error")) {
		t.Errorf("expected false for non-ECONNREFUSED error")
	}
}

func TestIsConnectionRefused_Timeout(t *testing.T) {
	if IsConnectionRefused(syscall.ETIMEDOUT) {
		t.Errorf("expected false for ETIMEDOUT")
	}
}
