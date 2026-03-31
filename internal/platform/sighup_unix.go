//go:build !windows

package platform

import (
	"os"
	"os/signal"
	"syscall"
)

// NotifySIGHUP arranges for SIGHUP to be delivered to ch.
func NotifySIGHUP(ch chan<- os.Signal) {
	signal.Notify(ch, syscall.SIGHUP)
}
