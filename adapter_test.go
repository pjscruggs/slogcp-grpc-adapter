package slogcpadapter

import (
	"bytes"
	"context"
	"io"
	"log/slog"
	"testing"

	grpc_logging "github.com/grpc-ecosystem/go-grpc-middleware/v2/interceptors/logging"
	"github.com/pjscruggs/slogcp"
)

type recordingHandler struct {
	records []slog.Record
}

// Enabled implements slog.Handler and allows all records during testing.
func (h *recordingHandler) Enabled(context.Context, slog.Level) bool { return true }

// Handle records the slog record for later inspection.
func (h *recordingHandler) Handle(_ context.Context, r slog.Record) error {
	h.records = append(h.records, r.Clone())
	return nil
}

// WithAttrs clones the handler and prepends the supplied attributes as a record.
func (h *recordingHandler) WithAttrs(_ []slog.Attr) slog.Handler {
	r := &recordingHandler{}
	r.records = append(r.records, slog.Record{
		Message: "withAttrs",
		Level:   slog.LevelInfo,
	})
	return r
}

// WithGroup preserves the handler for grouped logging.
func (h *recordingHandler) WithGroup(string) slog.Handler { return h }

// TestLoggerLogConvertsFields ensures key/value pairs become slog attrs with coerced keys.
func TestLoggerLogConvertsFields(t *testing.T) {
	rec := &recordingHandler{}
	logger := NewLogger(nil, WithLogger(slog.New(rec)))

	logger.Log(context.Background(), grpc_logging.LevelInfo, "msg",
		"id", 123,
		99, true,
		"lonely",
	)

	if len(rec.records) != 1 {
		t.Fatalf("expected 1 record, got %d", len(rec.records))
	}

	r := rec.records[0]
	if r.Level != slog.LevelInfo {
		t.Fatalf("unexpected level: %v", r.Level)
	}
	if r.Message != "msg" {
		t.Fatalf("unexpected message: %s", r.Message)
	}

	attrs := collectAttrs(r)
	if got := attrs["id"]; got != int64(123) {
		t.Fatalf("expected id attr to be 123, got %v (%T)", got, got)
	}
	if got := attrs["99"]; got != true {
		t.Fatalf("expected coerced key '99', got %v", got)
	}
	if _, ok := attrs["lonely"]; !ok {
		t.Fatalf("expected lonely key to be present")
	}
	if got := attrs["lonely"]; got != nil {
		t.Fatalf("expected lonely value to be nil, got %v", got)
	}
}

// TestLoggerRespectsCustomLevelMapper verifies custom level mapping is used.
func TestLoggerRespectsCustomLevelMapper(t *testing.T) {
	rec := &recordingHandler{}
	mapper := func(_ grpc_logging.Level) slog.Level { return slog.LevelWarn }
	logger := NewLogger(nil, WithLogger(slog.New(rec)), WithLevelMapper(mapper))

	logger.Log(context.Background(), grpc_logging.LevelDebug, "custom", "k", "v")

	if len(rec.records) != 1 {
		t.Fatalf("expected 1 record, got %d", len(rec.records))
	}
	if rec.records[0].Level != slog.LevelWarn {
		t.Fatalf("expected custom level mapper to force warn, got %v", rec.records[0].Level)
	}
}

// TestNewLoggerRestoresDefaultMapperWhenNil ensures nil mapper falls back to default mapping.
func TestNewLoggerRestoresDefaultMapperWhenNil(t *testing.T) {
	rec := &recordingHandler{}
	resetMapper := func(cfg *loggerConfig) { cfg.levelMapper = nil }
	logger := NewLogger(nil, WithLogger(slog.New(rec)), resetMapper)

	logger.Log(context.Background(), grpc_logging.LevelError, "fallback")

	if len(rec.records) != 1 {
		t.Fatalf("expected 1 record, got %d", len(rec.records))
	}
	if rec.records[0].Level != slog.LevelError {
		t.Fatalf("expected default level mapper to be restored, got %v", rec.records[0].Level)
	}
}

// TestNewLoggerPrefersProvidedLogger confirms WithLogger overrides handler selection.
func TestNewLoggerPrefersProvidedLogger(t *testing.T) {
	rec := &recordingHandler{}
	slogLogger := slog.New(rec)
	handler, err := slogcp.NewHandler(io.Discard)
	if err != nil {
		t.Fatalf("failed to create slogcp handler: %v", err)
	}

	logger := NewLogger(handler, WithLogger(slogLogger))
	if logger.log.Handler() != rec {
		t.Fatalf("expected provided logger handler to be used")
	}

	logger.Log(context.Background(), grpc_logging.LevelInfo, "hello", "k", "v")

	if len(rec.records) != 1 {
		t.Fatalf("expected record to be captured by provided logger, got %d", len(rec.records))
	}
}

// TestNewLoggerUsesHandlerAndDefaultFallback ensures handler wiring and default logger fallback both work.
func TestNewLoggerUsesHandlerAndDefaultFallback(t *testing.T) {
	handler, err := slogcp.NewHandler(io.Discard)
	if err != nil {
		t.Fatalf("failed to create slogcp handler: %v", err)
	}
	logger := NewLogger(handler)
	if logger.log == nil {
		t.Fatalf("logger should be initialized when handler is supplied")
	}
	if logger.log.Handler() != handler {
		t.Fatalf("expected slogcp handler to be used")
	}

	buf := &bytes.Buffer{}
	prev := slog.Default()
	slog.SetDefault(slog.New(slog.NewTextHandler(buf, nil)))
	defer slog.SetDefault(prev)

	fallback := NewLogger(nil)
	fallback.Log(context.Background(), grpc_logging.LevelInfo, "default-path", "k", "v")

	if buf.Len() == 0 {
		t.Fatalf("expected default slog logger to receive output")
	}
}

// TestBuildAttrsHandlesEmptyFields checks empty slices yield nil attrs.
func TestBuildAttrsHandlesEmptyFields(t *testing.T) {
	if attrs := buildAttrs(nil); attrs != nil {
		t.Fatalf("expected nil for empty fields, got %v", attrs)
	}
}

// TestDefaultLevelMapper asserts the default mapping for known and unknown levels.
func TestDefaultLevelMapper(t *testing.T) {
	tests := []struct {
		name string
		in   grpc_logging.Level
		want slog.Level
	}{
		{"debug", grpc_logging.LevelDebug, slog.LevelDebug},
		{"info", grpc_logging.LevelInfo, slog.LevelInfo},
		{"warn", grpc_logging.LevelWarn, slog.LevelWarn},
		{"error-default", grpc_logging.LevelError, slog.LevelError},
		{"unknown", grpc_logging.Level(123), slog.LevelError},
	}
	for _, tt := range tests {
		if got := defaultLevelMapper(tt.in); got != tt.want {
			t.Fatalf("%s: expected %v, got %v", tt.name, tt.want, got)
		}
	}
}

// TestLoggerHandlesNilReceiver ensures Log tolerates nil logger and receiver safely.
func TestLoggerHandlesNilReceiver(t *testing.T) {
	defer func() {
		if r := recover(); r != nil {
			t.Fatalf("Log should not panic on nil receiver: %v", r)
		}
	}()

	var logger *Logger
	logger.Log(context.Background(), grpc_logging.LevelInfo, "noop")

	empty := &Logger{}
	empty.Log(context.Background(), grpc_logging.LevelInfo, "noop")
}

// TestInterceptorsConstruct verifies interceptor helpers return non-nil interceptors.
func TestInterceptorsConstruct(t *testing.T) {
	handler, err := slogcp.NewHandler(io.Discard)
	if err != nil {
		t.Fatalf("failed to create slogcp handler: %v", err)
	}
	if UnaryServerInterceptor(handler) == nil {
		t.Fatalf("UnaryServerInterceptor returned nil")
	}
	if StreamServerInterceptor(handler) == nil {
		t.Fatalf("StreamServerInterceptor returned nil")
	}
	if UnaryClientInterceptor(handler) == nil {
		t.Fatalf("UnaryClientInterceptor returned nil")
	}
	if StreamClientInterceptor(handler) == nil {
		t.Fatalf("StreamClientInterceptor returned nil")
	}
}

// collectAttrs flattens slog record attributes into a map for assertions.
func collectAttrs(r slog.Record) map[string]any {
	out := make(map[string]any)
	r.Attrs(func(a slog.Attr) bool {
		out[a.Key] = a.Value.Any()
		return true
	})
	return out
}
