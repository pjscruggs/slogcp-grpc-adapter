// Copyright 2025 Patrick J. Scruggs
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
	"log/slog"
	"testing"

	grpc_logging "github.com/grpc-ecosystem/go-grpc-middleware/v2/interceptors/logging"
)

// discardHandler satisfies slog.Handler while discarding all records.
type discardHandler struct{}

// Enabled allows all log levels during benchmarks.
func (discardHandler) Enabled(context.Context, slog.Level) bool { return true }

// Handle drops records and avoids allocations.
func (discardHandler) Handle(context.Context, slog.Record) error { return nil }

// WithAttrs returns a fresh discardHandler for attribute chaining.
func (discardHandler) WithAttrs([]slog.Attr) slog.Handler { return discardHandler{} }

// WithGroup returns a discardHandler because grouping is irrelevant for benchmarks.
func (discardHandler) WithGroup(string) slog.Handler { return discardHandler{} }

// BenchmarkLogger measures adapter cost when converting simple fields.
func BenchmarkLogger(b *testing.B) {
	adapter := NewLogger(nil, WithLogger(slog.New(discardHandler{})))

	ctx := context.Background()
	for i := 0; b.Loop(); i++ {
		adapter.Log(ctx, grpc_logging.LevelInfo, "bench",
			"id", i,
			"user", "abc",
			"ok", true,
		)
	}
}

// BenchmarkLoggerLevelMapping measures adapter cost when custom level mapping is used.
func BenchmarkLoggerLevelMapping(b *testing.B) {
	adapter := NewLogger(nil, WithLogger(slog.New(discardHandler{})), WithLevelMapper(defaultLevelMapper))
	ctx := context.Background()
	for b.Loop() {
		adapter.Log(ctx, grpc_logging.LevelWarn, "bench")
	}
}
