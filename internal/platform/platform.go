// Package platform provides platform-specific functionality including signal
// handling, socket options, config file watching, and network utilities.
package platform

import (
	"context"
	"fmt"
	"log/slog"
	"net"
	"strings"
	"time"

	"github.com/fsnotify/fsnotify"
)

// StartConfigWatcher watches configFileName for modifications and sends on the
// reload channel when a change is detected. Multiple rapid changes (e.g. an
// editor doing an atomic rename-over-write) are coalesced by a short debounce
// so that only one reload is triggered per save.
func StartConfigWatcher(ctx context.Context, configFileName string, reload chan<- struct{}) error {
	log := slog.Default()
	watcher, err := fsnotify.NewWatcher()
	if err != nil {
		return fmt.Errorf("failed to create config file watcher: %w", err)
	}
	if err := watcher.Add(configFileName); err != nil {
		watcher.Close()
		return fmt.Errorf("failed to watch config file %q: %w", configFileName, err)
	}
	log.Info("Watching config file for changes", slog.String("file", configFileName))
	go func() {
		defer watcher.Close()
		const debounceDelay = 500 * time.Millisecond
		var debounceTimer <-chan time.Time
		for {
			select {
			case event, ok := <-watcher.Events:
				if !ok {
					return
				}
				if event.Has(fsnotify.Write) || event.Has(fsnotify.Create) {
					debounceTimer = time.After(debounceDelay)
				}
				// Editors that write atomically (write temp file, rename over
				// target) produce a Rename or Remove event on the watched path.
				// Re-add the watch so we catch the new file.
				if event.Has(fsnotify.Rename) || event.Has(fsnotify.Remove) {
					_ = watcher.Add(configFileName)
					debounceTimer = time.After(debounceDelay)
				}
			case err, ok := <-watcher.Errors:
				if !ok {
					return
				}
				log.Warn("config file watcher error", slog.String("error", err.Error()))
			case <-debounceTimer:
				debounceTimer = nil
				log.Log(ctx, slog.Level(2), "config file changed - reloading",
					slog.String("file", configFileName))
				select {
				case reload <- struct{}{}:
				default: // reload already pending; skip
				}
			case <-ctx.Done():
				return
			}
		}
	}()
	return nil
}

// IsExternalInterface uses a string prefix list to weed out known internal interface names.
func IsExternalInterface(ifname string) bool {
	switch {
	case strings.HasPrefix(ifname, "docker"):
		return false
	case strings.HasPrefix(ifname, "lxdbr"):
		return false
	default:
		return true
	}
}

// IsIPv4 returns true if the address is IPv4, false if IPv6.
func IsIPv4(address string) bool {
	return strings.Count(address, ":") < 2
}

// IsIPv6 returns true if the address is IPv6, false if IPv4.
func IsIPv6(address string) bool {
	return strings.Count(address, ":") >= 2
}

// ListExternalIPs returns a list of IP addresses on externally-reachable interfaces.
func ListExternalIPs() ([]net.IP, error) {
	log := slog.Default()
	var ips []net.IP
	ifaces, err := net.Interfaces()
	if err != nil {
		return nil, fmt.Errorf("failed to enumerate network interfaces: %w", err)
	}
	for _, i := range ifaces {
		if !IsExternalInterface(i.Name) {
			log.Debug("skipping internal interface", slog.String("interface", i.Name))
			continue
		}
		addrs, err := i.Addrs()
		if err != nil {
			return nil, fmt.Errorf("failed to enumerate network addresses: %w", err)
		}
		for _, addr := range addrs {
			var ip net.IP
			switch v := addr.(type) {
			case *net.IPNet:
				ip = v.IP
			case *net.IPAddr:
				ip = v.IP
			default:
				continue
			}
			if ip.IsGlobalUnicast() {
				ips = append(ips, ip)
			}
		}
	}
	return ips, nil
}

// FindExternalAddr attempts to find a reachable external IP address for the system.
// Prefers IPv4 addresses. If multiple are found, returns the first.
func FindExternalAddr() (string, error) {
	var listenAddr string

	ips, err := ListExternalIPs()
	if err != nil {
		return "", fmt.Errorf("unable to list external IP addresses: %w", err)
	}
	for _, ip := range ips {
		if IsIPv4(ip.String()) {
			listenAddr = ip.String()
			break
		}
	}
	if listenAddr == "" {
		// No IPv4 addresses found, choose the first IPv6 address
		if len(ips) == 0 {
			return "", fmt.Errorf("no valid external IP addresses found")
		}
		listenAddr = ips[0].String()
	}
	return listenAddr, nil
}
