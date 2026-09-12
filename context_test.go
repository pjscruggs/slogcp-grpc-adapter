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
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"sync"
	"testing"

	grpc_logging "github.com/grpc-ecosystem/go-grpc-middleware/v2/interceptors/logging"
	"github.com/pjscruggs/slogcp/v2"
	"go.opentelemetry.io/otel/trace"
	"google.golang.org/grpc"
)

// decodeContextLogs reads complete JSON records after logging has finished.
func decodeContextLogs(t *testing.T, data []byte) []map[string]any {
	t.Helper()
	decoder := json.NewDecoder(bytes.NewReader(data))
	var records []map[string]any
	for {
		var record map[string]any
		if err := decoder.Decode(&record); err == io.EOF {
			return records
		} else if err != nil {
			t.Fatal(err)
		}
		records = append(records, record)
	}
}

// TestContextSelection covers presence, fallback construction and default changes.
func TestContextSelection(t *testing.T) {
	original := slog.Default()
	t.Cleanup(func() { slog.SetDefault(original) })
	for _, source := range []string{"explicit", "handler", "default"} {
		for _, policy := range []LoggerPolicy{Fixed, PreferContext, LoggerPolicy(99)} {
			t.Run(fmt.Sprintf("%s/%d", source, policy), func(t *testing.T) {
				var fallback, contextual, changed bytes.Buffer
				handler, err := slogcp.NewHandler(&fallback)
				if err != nil {
					t.Fatal(err)
				}
				base := slog.New(handler).With("fallback_only", true)
				slog.SetDefault(base)
				var adapted *Logger
				switch source {
				case "explicit":
					adapted = NewLogger(nil, WithLogger(base), WithLoggerPolicy(policy))
				case "handler":
					adapted = NewLogger(handler, WithLoggerPolicy(policy))
				default:
					adapted = NewLogger(nil, WithLoggerPolicy(policy))
				}
				request := slog.New(slog.NewJSONHandler(&contextual, nil)).With("request_id", "alpha")
				ctx := slogcp.ContextWithLogger(t.Context(), request)
				slog.SetDefault(slog.New(slog.NewJSONHandler(&changed, nil)))
				adapted.Log(ctx, grpc_logging.LevelInfo, "request")
				adapted.Log(t.Context(), grpc_logging.LevelInfo, "absent")
				var nilCtx context.Context
				adapted.Log(nilCtx, grpc_logging.LevelInfo, "nil")
				if changed.Len() != 0 {
					t.Fatal("fallback followed changed default")
				}
				wantFallback, wantContext := 3, 0
				if policy == PreferContext {
					wantFallback, wantContext = 2, 1
				}
				if got := len(decodeContextLogs(t, fallback.Bytes())); got != wantFallback {
					t.Fatalf("fallback records = %d", got)
				}
				records := decodeContextLogs(t, contextual.Bytes())
				if len(records) != wantContext {
					t.Fatalf("context records = %d", len(records))
				}
				if wantContext > 0 && (records[0]["request_id"] != "alpha" || records[0]["fallback_only"] != nil) {
					t.Fatalf("selected attributes = %v", records)
				}
				// A logger explicitly stored as the current default still counts as present.
				adapted = NewLogger(nil, WithLogger(base), WithLoggerPolicy(PreferContext))
				adapted.Log(slogcp.ContextWithLogger(t.Context(), slog.Default()), grpc_logging.LevelInfo, "stored default")
				if len(decodeContextLogs(t, changed.Bytes())) != 1 {
					t.Fatal("stored default not selected")
				}
			})
		}
	}
}

// TestContextPipeline verifies that selection precedes filtering and preserves groups and redaction.
func TestContextPipeline(t *testing.T) {
	for _, levels := range []struct {
		fallback, selected slog.Level
		want               int
	}{
		{slog.LevelError, slog.LevelDebug, 1}, {slog.LevelDebug, slog.LevelError, 0},
	} {
		var fallback, selected bytes.Buffer
		base := slog.New(slog.NewJSONHandler(&fallback, &slog.HandlerOptions{Level: levels.fallback}))
		request := slog.New(slog.NewJSONHandler(&selected, &slog.HandlerOptions{
			Level: levels.selected,
			ReplaceAttr: func(_ []string, attr slog.Attr) slog.Attr {
				if attr.Key == "secret" {
					return slog.String("secret", "redacted")
				}
				return attr
			},
		})).With("common", true).WithGroup("request").With("id", "alpha")
		adapted := NewLogger(nil, WithLogger(base), WithLoggerPolicy(PreferContext), WithLevelMapper(func(grpc_logging.Level) slog.Level { return slog.LevelDebug }))
		ctx, cancel := context.WithCancel(slogcp.ContextWithLogger(t.Context(), request))
		cancel()
		adapted.Log(ctx, grpc_logging.LevelError, "event", "secret", "private")
		if fallback.Len() != 0 {
			t.Fatal("selected pipeline fell through")
		}
		records := decodeContextLogs(t, selected.Bytes())
		if len(records) != levels.want {
			t.Fatalf("records = %v", records)
		}
		if levels.want == 1 {
			group := records[0]["request"].(map[string]any)
			if group["id"] != "alpha" || group["secret"] != "redacted" || records[0]["common"] != true {
				t.Fatalf("attributes = %v", records)
			}
		}
		adapted.Log(slogcp.ContextWithLogger(t.Context(), slog.New(slog.DiscardHandler)), grpc_logging.LevelError, "discard")
		if fallback.Len() != 0 {
			t.Fatal("discard fell through")
		}
	}
}

// TestContextRequestIsolation shares an adapter across concurrent request loggers.
func TestContextRequestIsolation(t *testing.T) {
	logs := &rpcLogBuffer{}
	base := slog.New(slog.NewJSONHandler(logs, nil))
	adapted := NewLogger(nil, WithLogger(base), WithLoggerPolicy(PreferContext))
	var wg sync.WaitGroup
	for i := range 32 {
		wg.Go(func() {
			ctx := slogcp.ContextWithLogger(t.Context(), base.With("request_id", i))
			adapted.Log(ctx, grpc_logging.LevelInfo, "request", "event_id", i)
		})
	}
	wg.Wait()
	adapted.Log(t.Context(), grpc_logging.LevelInfo, "fallback")
	records := decodeContextLogs(t, logs.snapshot())
	if len(records) != 33 {
		t.Fatalf("records = %d", len(records))
	}
	seen := map[any]bool{}
	for _, record := range records[:32] {
		if record["request_id"] != record["event_id"] || seen[record["request_id"]] {
			t.Fatalf("request leaked: %v", record)
		}
		seen[record["request_id"]] = true
	}
	if records[32]["request_id"] != nil {
		t.Fatal("request leaked into fallback")
	}
}

// TestContextTraceAndAttributes distinguishes logger selection from trace forwarding.
func TestContextTraceAndAttributes(t *testing.T) {
	for _, withLogger := range []bool{false, true} {
		for _, withSpan := range []bool{false, true} {
			var output bytes.Buffer
			handler, err := slogcp.NewHandler(&output, slogcp.WithTraceProjectID("test-project"))
			if err != nil {
				t.Fatal(err)
			}
			base := slog.New(handler)
			adapted := NewLogger(nil, WithLogger(base), WithLoggerPolicy(PreferContext))
			ctx := t.Context()
			if withLogger {
				ctx = slogcp.ContextWithLogger(ctx, base.With("request_id", "alpha", slog.Group("request", "nested", true)))
			}
			span := trace.NewSpanContext(trace.SpanContextConfig{TraceID: trace.TraceID{1}, SpanID: trace.SpanID{2}, TraceFlags: trace.FlagsSampled})
			if withSpan {
				ctx = trace.ContextWithSpanContext(ctx, span)
			}
			adapted.Log(ctx, grpc_logging.LevelInfo, "event")
			record := decodeContextLogs(t, output.Bytes())[0]
			if (record["request_id"] == "alpha") != withLogger {
				t.Fatalf("logger attributes: %v", record)
			}
			if withLogger && record["request"].(map[string]any)["nested"] != true {
				t.Fatal("nested attribute lost")
			}
			if withSpan {
				if record["logging.googleapis.com/trace"] != "projects/test-project/traces/"+span.TraceID().String() || record["logging.googleapis.com/spanId"] != span.SpanID().String() || record["logging.googleapis.com/trace_sampled"] != true {
					t.Fatalf("trace fields: %v", record)
				}
			} else if record["logging.googleapis.com/trace"] != nil {
				t.Fatalf("unexpected trace: %v", record)
			}
		}
	}
}

// TestContextInterceptorOrdering documents the retained event context for all event types.
func TestContextInterceptorOrdering(t *testing.T) {
	var output bytes.Buffer
	base := slog.New(slog.NewJSONHandler(&output, &slog.HandlerOptions{Level: slog.LevelDebug}))
	adapted := NewLogger(nil, WithLogger(base), WithLoggerPolicy(PreferContext))
	interceptor := grpc_logging.UnaryServerInterceptor(adapted, grpc_logging.WithLogOnEvents(
		grpc_logging.StartCall, grpc_logging.PayloadReceived, grpc_logging.PayloadSent, grpc_logging.FinishCall,
	))
	early := slogcp.ContextWithLogger(t.Context(), base.With("scope", "early"))
	_, err := interceptor(early, nil, &grpc.UnaryServerInfo{FullMethod: "/test.Service/Call"}, func(ctx context.Context, _ any) (any, error) {
		late := slogcp.ContextWithLogger(ctx, base.With("scope", "late"))
		slogcp.Logger(late).InfoContext(late, "application")
		return struct{}{}, nil
	})
	if err != nil {
		t.Fatal(err)
	}
	records := decodeContextLogs(t, output.Bytes())
	if len(records) != 5 {
		t.Fatalf("event count = %d: %v", len(records), records)
	}
	for _, record := range records {
		want := "early"
		if record["msg"] == "application" {
			want = "late"
		}
		if record["scope"] != want {
			t.Fatalf("event context changed: %v", record)
		}
	}
}
