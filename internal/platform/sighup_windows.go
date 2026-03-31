//go:build windows

package platform

import "os"

// NotifySIGHUP is a no-op on Windows; config reload via SIGHUP is not supported.
func NotifySIGHUP(_ chan<- os.Signal) {}
