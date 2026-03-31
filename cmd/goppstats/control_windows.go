package main

import (
	"log/slog"
	"syscall"

	"golang.org/x/sys/windows"
)

// Control sets the SO_REUSEADDR socket option on the listener.
func Control(network, address string, c syscall.RawConn) error {
	return c.Control(func(fd uintptr) {
		err := windows.SetsockoptInt(windows.Handle(fd), windows.SOL_SOCKET, windows.SO_REUSEADDR, 1)
		if err != nil {
			log.Warn("Could not set SO_REUSEADDR socket option", slog.Any("error", err))
		}
	})
}
