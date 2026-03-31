//go:build !windows

package main

import (
	"log/slog"
	"syscall"

	"golang.org/x/sys/unix"
)

// Control sets SO_REUSEADDR and SO_REUSEPORT socket options on the listener.
func Control(network, address string, c syscall.RawConn) error {
	return c.Control(func(fd uintptr) {
		err := unix.SetsockoptInt(int(fd), unix.SOL_SOCKET, unix.SO_REUSEADDR, 1)
		if err != nil {
			log.Warn("Could not set SO_REUSEADDR socket option", slog.Any("error", err))
		}
		err = unix.SetsockoptInt(int(fd), unix.SOL_SOCKET, unix.SO_REUSEPORT, 1)
		if err != nil {
			log.Warn("Could not set SO_REUSEPORT socket option", slog.Any("error", err))
		}
	})
}
