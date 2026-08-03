// Package api provides a shared OneFS PAPI HTTP client with session-based and
// basic authentication, automatic re-authentication, and retry logic with
// exponential backoff.
package api

import (
	"bytes"
	"context"
	"crypto/tls"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"net/http/cookiejar"
	"net/url"
	"strconv"
	"strings"
	"syscall"
	"time"

	"github.com/isilon/powerscale_data_insights/internal/logging"
	"golang.org/x/net/publicsuffix"
)

// MaxAPIPathLen is the limit on the length of an API request URL.
const MaxAPIPathLen = 8198

// Authentication type constants.
const (
	AuthTypeBasic   = "basic-auth"
	AuthTypeSession = "session"
	DefaultAuthType = AuthTypeSession
)

// API endpoint paths shared by both collectors.
const (
	SessionPath = "/session/1/session"
	ConfigPath  = "/platform/1/cluster/config"
)

const maxTimeoutSecs = 1800 // clamp retry timeout to 30 minutes

// AuthInfo provides username and password to authenticate against the OneFS API.
type AuthInfo struct {
	Username string
	Password string
}

// Cluster contains all of the information to talk to a OneFS cluster via the
// OneFS PAPI. Both collectors embed or use this struct directly.
type Cluster struct {
	AuthInfo
	AuthType     string
	Hostname     string
	Port         int
	VerifySSL    bool
	OSVersion    string
	ClusterName  string
	UserAgent    string // set by each collector, e.g. "gostats/0.40"
	baseURL      string
	client       *http.Client
	csrfToken    string
	reauthTime   time.Time
	MaxRetries   int
	PreserveCase bool
}

// Initialize sets up the HTTP client with TLS configuration and cookie jar.
// It must be called before any API requests.
func (c *Cluster) Initialize() error {
	log := slog.Default()
	if c.client != nil {
		log.Warn("initialize called for cluster when it was already initialized, skipping",
			slog.String("cluster", c.Hostname))
		return nil
	}
	if c.Username == "" {
		return fmt.Errorf("username must be set")
	}
	if c.Password == "" {
		return fmt.Errorf("password must be set")
	}
	if c.Hostname == "" {
		return fmt.Errorf("hostname must be set")
	}
	if c.Port == 0 {
		c.Port = 8080
	}
	jar, err := cookiejar.New(&cookiejar.Options{PublicSuffixList: publicsuffix.List})
	if err != nil {
		return err
	}
	tr := &http.Transport{
		TLSClientConfig: &tls.Config{InsecureSkipVerify: !c.VerifySSL},
	}
	c.client = &http.Client{
		Transport: tr,
		Jar:       jar,
	}
	c.baseURL = "https://" + c.Hostname + ":" + strconv.Itoa(c.Port)
	return nil
}

// String returns the cluster name.
func (c *Cluster) String() string {
	return c.ClusterName
}

// BaseURL returns the base URL for the cluster API.
func (c *Cluster) BaseURL() string {
	return c.baseURL
}

// Authenticate authenticates to the cluster using the session API endpoint
// and saves the cookies needed to authenticate subsequent requests.
func (c *Cluster) Authenticate(ctx context.Context) error {
	log := slog.Default()
	var err error
	var resp *http.Response

	am := struct {
		Username string   `json:"username"`
		Password string   `json:"password"`
		Services []string `json:"services"`
	}{
		Username: c.Username,
		Password: c.Password,
		Services: []string{"platform"},
	}
	b, err := json.Marshal(am)
	if err != nil {
		return err
	}
	u, err := url.Parse(c.baseURL + SessionPath)
	if err != nil {
		return err
	}
	// POST our authentication request to the API
	// This may be our first connection so we'll retry here in the hope that if
	// we can't connect to one node, another may be responsive
	retrySecs := 1
	for i := 1; i <= c.MaxRetries; i++ {
		var req *http.Request
		req, err = http.NewRequestWithContext(ctx, http.MethodPost, u.String(), bytes.NewBuffer(b))
		if err != nil {
			return err
		}
		req.Header.Set("User-Agent", c.UserAgent)
		req.Header.Set("Content-Type", "application/json")
		resp, err = c.client.Do(req)
		if err == nil {
			break
		}
		log.Warn("Authentication request failed", slog.String("error", err.Error()), slog.Int("retry_secs", retrySecs))
		select {
		case <-time.After(time.Duration(retrySecs) * time.Second):
		case <-ctx.Done():
			return ctx.Err()
		}
		retrySecs *= 2
		if retrySecs > maxTimeoutSecs {
			retrySecs = maxTimeoutSecs
		}
	}
	if err != nil {
		return fmt.Errorf("max retries exceeded for connect to %s, aborting connection attempt", c.Hostname)
	}
	defer resp.Body.Close() //nolint:errcheck
	// 201(StatusCreated) is success
	if resp.StatusCode != http.StatusCreated {
		return fmt.Errorf("auth failed: %s", resp.Status)
	}
	// parse out time limit so we can reauth when necessary
	dec := json.NewDecoder(resp.Body)
	var ar map[string]any
	err = dec.Decode(&ar)
	if err != nil {
		return fmt.Errorf("unable to parse auth response: %s", err)
	}
	// drain any other output
	_, _ = io.Copy(io.Discard, resp.Body)
	var timeout int
	ta, ok := ar["timeout_absolute"]
	if ok {
		if taF, ok := ta.(float64); ok {
			timeout = int(taF)
		} else {
			log.Warn("authentication API returned unexpected type for timeout value, using default")
			timeout = 14400
		}
	} else {
		// This shouldn't happen, but just set it to a sane default
		log.Warn("authentication API did not return timeout value, using default")
		timeout = 14400
	}
	if timeout > 60 {
		timeout -= 60 // Give a minute's grace to the reauth timer
	}
	c.reauthTime = time.Now().Add(time.Duration(timeout) * time.Second)

	c.csrfToken = ""
	// Dig out CSRF token so we can set the appropriate header
	for _, cookie := range c.client.Jar.Cookies(u) {
		if cookie.Name == "isicsrf" {
			log.Debug("Found csrf cookie", "cookie", cookie)
			c.csrfToken = cookie.Value
		}
	}
	if c.csrfToken == "" {
		log.Debug("No CSRF token found, assuming old-style session auth", slog.String("cluster", c.Hostname))
	}

	return nil
}

// GetClusterConfig pulls information from the cluster config API endpoint,
// including the actual cluster name and OneFS version.
func (c *Cluster) GetClusterConfig(ctx context.Context) error {
	var v any
	resp, err := c.RestGet(ctx, ConfigPath)
	if err != nil {
		return err
	}
	err = json.Unmarshal(resp, &v)
	if err != nil {
		return err
	}
	m, ok := v.(map[string]any)
	if !ok {
		return fmt.Errorf("unexpected JSON structure for cluster config")
	}
	version, ok := m["onefs_version"].(map[string]any)
	if !ok {
		return fmt.Errorf("unexpected type for onefs_version field")
	}
	rel, ok := version["version"].(string)
	if !ok {
		return fmt.Errorf("unexpected type for version field")
	}
	c.OSVersion = rel
	name, ok := m["name"].(string)
	if !ok {
		return fmt.Errorf("unexpected type for name field")
	}
	if c.PreserveCase {
		c.ClusterName = name
	} else {
		c.ClusterName = strings.ToLower(name)
	}
	return nil
}

// Connect establishes the initial network connection to the cluster,
// then pulls the cluster config info to get the real cluster name.
func (c *Cluster) Connect(ctx context.Context) error {
	if err := c.Initialize(); err != nil {
		return fmt.Errorf("initialize: %w", err)
	}
	if c.AuthType == AuthTypeSession {
		if err := c.Authenticate(ctx); err != nil {
			return fmt.Errorf("authenticate: %w", err)
		}
	}
	if err := c.GetClusterConfig(ctx); err != nil {
		return fmt.Errorf("get cluster config: %w", err)
	}
	return nil
}

// IsConnectionRefused checks if the given error is a connection refused error.
func IsConnectionRefused(err error) bool {
	return errors.Is(err, syscall.ECONNREFUSED)
}

// RestGet returns the REST response body for the given endpoint from the API.
// It handles session re-authentication and retries on connection refused errors
// with exponential backoff.
func (c *Cluster) RestGet(ctx context.Context, endpoint string) ([]byte, error) {
	log := slog.Default()
	var err error
	var resp *http.Response

	if c.AuthType == AuthTypeSession && time.Now().After(c.reauthTime) {
		log.Info("re-authenticating to cluster based on timer", slog.String("cluster", c.String()))
		if err = c.Authenticate(ctx); err != nil {
			return nil, err
		}
	}

	u, err := url.Parse(c.baseURL + endpoint)
	if err != nil {
		return nil, err
	}
	req, err := c.newGetRequest(ctx, u.String())
	if err != nil {
		return nil, err
	}

	retrySecs := 1
	for i := 1; i <= c.MaxRetries; i++ {
		resp, err = c.client.Do(req)
		if err == nil {
			// We got a valid http response
			if resp.StatusCode == http.StatusOK {
				break
			}
			_ = resp.Body.Close()
			// check for need to re-authenticate (maybe we are talking to a different node)
			if resp.StatusCode == http.StatusUnauthorized {
				if c.AuthType == AuthTypeBasic {
					return nil, fmt.Errorf("basic authentication for cluster %s failed - check username and password", c)
				}
				log.Log(ctx, logging.LevelNotice, "Session-based authentication failed, attempting to re-authenticate", slog.String("cluster", c.String()))
				if err = c.Authenticate(ctx); err != nil {
					return nil, err
				}
				req, err = c.newGetRequest(ctx, u.String())
				if err != nil {
					return nil, err
				}
				continue
			}
			return nil, fmt.Errorf("cluster %s returned unexpected HTTP response: %v", c, resp.Status)
		}
		// assert err != nil
		// TODO - consider adding more retryable cases e.g. temporary DNS hiccup
		if !IsConnectionRefused(err) {
			return nil, err
		}
		log.Error("Connection refused, retrying", slog.String("cluster", c.Hostname), slog.Int("retry_secs", retrySecs))
		select {
		case <-time.After(time.Duration(retrySecs) * time.Second):
		case <-ctx.Done():
			return nil, ctx.Err()
		}
		retrySecs *= 2
		if retrySecs > maxTimeoutSecs {
			retrySecs = maxTimeoutSecs
		}
	}
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close() //nolint:errcheck
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("cluster %s returned unexpected HTTP response: %v", c, resp.Status)
	}
	body, err := io.ReadAll(resp.Body)
	return body, err
}

// newGetRequest creates a new HTTP GET request with the appropriate headers
// and authentication information.
func (c *Cluster) newGetRequest(ctx context.Context, url string) (*http.Request, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("User-Agent", c.UserAgent)
	req.Header.Set("Content-Type", "application/json")
	if c.AuthType == AuthTypeBasic {
		req.SetBasicAuth(c.Username, c.Password)
	}
	if c.csrfToken != "" {
		// Must be newer session-based auth with CSRF protection
		req.Header.Set("X-CSRF-Token", c.csrfToken)
		req.Header.Set("Referer", c.baseURL)
	}
	return req, nil
}
