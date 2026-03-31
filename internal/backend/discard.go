package backend

import "context"

// DiscardSink is a no-op backend for testing.
type DiscardSink struct{}

// NewDiscard creates a discard backend that silently drops all points.
func NewDiscard() DBWriter {
	return &DiscardSink{}
}

// WritePoints discards all points.
func (s *DiscardSink) WritePoints(_ context.Context, _ []Point) error {
	return nil
}
