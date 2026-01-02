// Copyright 2025-2026 Patrick J. Scruggs
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

package slogcpadapter

import (
	"context"
	"fmt"
	"log/slog"

	grpc_logging "github.com/grpc-ecosystem/go-grpc-middleware/v2/interceptors/logging"
	"github.com/pjscruggs/slogcp"
	"google.golang.org/grpc"
)

// Logger implements go-grpc-middleware's logging.Logger using a slog.Logger built on slogcp.
type Logger struct {
	log      *slog.Logger
	mapLevel func(grpc_logging.Level) slog.Level
}

type loggerConfig struct {
	logger      *slog.Logger
	levelMapper func(grpc_logging.Level) slog.Level
}

// LoggerOption customizes adapter construction.
type LoggerOption func(*loggerConfig)

// NewLogger creates an adapter backed by the provided slogcp handler. If no handler
// or slog.Logger is provided, the default slog logger is used so existing slogcp defaults apply.
//
// Example:
//
//	handler, _ := slogcp.NewHandler(os.Stdout)
//	adapter := slogcpadapter.NewLogger(handler)
//	server := grpc.NewServer(
//		grpc.ChainUnaryInterceptor(grpc_logging.UnaryServerInterceptor(adapter)),
//	)
func NewLogger(handler *slogcp.Handler, opts ...LoggerOption) *Logger {
	cfg := loggerConfig{
		levelMapper: defaultLevelMapper,
	}
	for _, opt := range opts {
		if opt != nil {
			opt(&cfg)
		}
	}

	switch {
	case cfg.logger != nil:
	case handler != nil:
		cfg.logger = slog.New(handler)
	default:
		cfg.logger = slog.Default()
	}

	if cfg.levelMapper == nil {
		cfg.levelMapper = defaultLevelMapper
	}

	return &Logger{
		log:      cfg.logger,
		mapLevel: cfg.levelMapper,
	}
}

// WithLogger overrides the slog.Logger used by the adapter, allowing reuse of an existing logger.
//
// Example:
//
//	base := slog.New(slog.NewTextHandler(os.Stdout, nil))
//	adapter := slogcpadapter.NewLogger(nil, slogcpadapter.WithLogger(base))
//	_ = grpc_logging.UnaryServerInterceptor(adapter) // reuse base logger in interceptors
func WithLogger(logger *slog.Logger) LoggerOption {
	return func(cfg *loggerConfig) {
		if logger != nil {
			cfg.logger = logger
		}
	}
}

// WithLevelMapper customizes how go-grpc-middleware logging levels map to slog levels.
func WithLevelMapper(mapper func(grpc_logging.Level) slog.Level) LoggerOption {
	return func(cfg *loggerConfig) {
		if mapper != nil {
			cfg.levelMapper = mapper
		}
	}
}

// Log satisfies the go-grpc-middleware logging.Logger interface and forwards entries
// to the underlying slog.Logger, preserving the provided context for trace propagation.
func (l *Logger) Log(ctx context.Context, level grpc_logging.Level, msg string, fields ...any) {
	if l == nil || l.log == nil {
		return
	}
	attrs := buildAttrs(fields)
	l.log.LogAttrs(ctx, l.mapLevel(level), msg, attrs...)
}

// UnaryServerInterceptor returns a grpc.UnaryServerInterceptor that logs using slogcp.
//
// Example:
//
//	handler, _ := slogcp.NewHandler(os.Stdout)
//	server := grpc.NewServer(
//		grpc.ChainUnaryInterceptor(slogcpadapter.UnaryServerInterceptor(handler)),
//	)
func UnaryServerInterceptor(handler *slogcp.Handler, opts ...grpc_logging.Option) grpc.UnaryServerInterceptor {
	return grpc_logging.UnaryServerInterceptor(NewLogger(handler), opts...)
}

// StreamServerInterceptor returns a grpc.StreamServerInterceptor that logs using slogcp.
//
// Example:
//
//	handler, _ := slogcp.NewHandler(os.Stdout)
//	server := grpc.NewServer(
//		grpc.ChainStreamInterceptor(slogcpadapter.StreamServerInterceptor(handler)),
//	)
func StreamServerInterceptor(handler *slogcp.Handler, opts ...grpc_logging.Option) grpc.StreamServerInterceptor {
	return grpc_logging.StreamServerInterceptor(NewLogger(handler), opts...)
}

// UnaryClientInterceptor returns a grpc.UnaryClientInterceptor that logs using slogcp.
//
// Example:
//
//	handler, _ := slogcp.NewHandler(os.Stdout)
//	conn, _ := grpc.NewClient(
//		addr,
//		grpc.WithTransportCredentials(insecure.NewCredentials()),
//		grpc.WithChainUnaryInterceptor(slogcpadapter.UnaryClientInterceptor(handler)),
//	)
func UnaryClientInterceptor(handler *slogcp.Handler, opts ...grpc_logging.Option) grpc.UnaryClientInterceptor {
	return grpc_logging.UnaryClientInterceptor(NewLogger(handler), opts...)
}

// StreamClientInterceptor returns a grpc.StreamClientInterceptor that logs using slogcp.
//
// Example:
//
//	handler, _ := slogcp.NewHandler(os.Stdout)
//	conn, _ := grpc.NewClient(
//		addr,
//		grpc.WithTransportCredentials(insecure.NewCredentials()),
//		grpc.WithChainStreamInterceptor(slogcpadapter.StreamClientInterceptor(handler)),
//	)
func StreamClientInterceptor(handler *slogcp.Handler, opts ...grpc_logging.Option) grpc.StreamClientInterceptor {
	return grpc_logging.StreamClientInterceptor(NewLogger(handler), opts...)
}

// defaultLevelMapper converts go-grpc-middleware levels into slog levels.
// It preserves the numeric value so that custom CodeToLevel functions in
// go-grpc-middleware can express intermediate severities that line up with
// slogcp's extended GCP severity levels (NOTICE, CRITICAL, etc.).
func defaultLevelMapper(level grpc_logging.Level) slog.Level {
	return slog.Level(level)
}

// buildAttrs converts logging fields from go-grpc-middleware into slog attributes.
func buildAttrs(fields []any) []slog.Attr {
	if len(fields) == 0 {
		return nil
	}

	attrs := make([]slog.Attr, 0, (len(fields)+1)/2)
	for i := 0; i < len(fields); i += 2 {
		key := fmt.Sprint(fields[i])
		var val any
		if i+1 < len(fields) {
			val = fields[i+1]
		}
		attrs = append(attrs, slog.Any(key, val))
	}
	return attrs
}
