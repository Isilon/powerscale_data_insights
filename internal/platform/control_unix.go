//go:build !windows

package platform

import (
	"log/slog"
	"syscall"

	"golang.org/x/sys/unix"
)

// Control sets SO_REUSEADDR and SO_REUSEPORT socket options on the listening socket.
func Control(network, address string, c syscall.RawConn) error {
	return c.Control(func(fd uintptr) {
		err := unix.SetsockoptInt(int(fd), unix.SOL_SOCKET, unix.SO_REUSEADDR, 1)
		if err != nil {
			slog.Warn("Could not set SO_REUSEADDR socket option", slog.String("error", err.Error()))
		}
		err = unix.SetsockoptInt(int(fd), unix.SOL_SOCKET, unix.SO_REUSEPORT, 1)
		if err != nil {
			slog.Warn("Could not set SO_REUSEPORT socket option", slog.String("error", err.Error()))
		}
	})
}
