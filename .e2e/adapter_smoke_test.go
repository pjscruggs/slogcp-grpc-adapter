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

package adaptere2e

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"net"
	"strings"
	"sync"
	"testing"
	"time"

	grpc_logging "github.com/grpc-ecosystem/go-grpc-middleware/v2/interceptors/logging"
	"github.com/pjscruggs/slogcp"
	slogcpadapter "github.com/pjscruggs/slogcp-grpc-adapter"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/health"
	"google.golang.org/grpc/health/grpc_health_v1"
	"google.golang.org/grpc/test/bufconn"
)

const (
	bufSize      = 1024 * 1024
	healthSvc    = "adapter-e2e"
	healthMethod = "Check"
)

// TestAdapterUnaryClientAndServerLogging verifies adapter logs on both sides of a real unary RPC.
func TestAdapterUnaryClientAndServerLogging(t *testing.T) {
	t.Parallel()

	serverLogs := &lockedBuffer{}
	clientLogs := &lockedBuffer{}
	serverHandler := newSlogcpHandler(t, serverLogs)
	clientHandler := newSlogcpHandler(t, clientLogs)

	listener := startHealthServer(t, serverHandler)

	conn, err := grpc.NewClient("passthrough:///adapter-e2e-bufnet",
		grpc.WithContextDialer(func(ctx context.Context, _ string) (net.Conn, error) {
			return listener.DialContext(ctx)
		}),
		grpc.WithTransportCredentials(insecure.NewCredentials()),
		grpc.WithChainUnaryInterceptor(slogcpadapter.UnaryClientInterceptor(clientHandler, logOptions()...)),
		grpc.WithChainStreamInterceptor(slogcpadapter.StreamClientInterceptor(clientHandler, logOptions()...)),
	)
	if err != nil {
		t.Fatalf("create gRPC client: %v", err)
	}
	t.Cleanup(func() {
		if closeErr := conn.Close(); closeErr != nil {
			t.Fatalf("close gRPC client: %v", closeErr)
		}
	})

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	client := grpc_health_v1.NewHealthClient(conn)
	resp, err := client.Check(ctx, &grpc_health_v1.HealthCheckRequest{Service: healthSvc})
	if err != nil {
		t.Fatalf("health check failed: %v", err)
	}
	if resp.GetStatus() != grpc_health_v1.HealthCheckResponse_SERVING {
		t.Fatalf("unexpected health response: %s", resp.GetStatus())
	}

	closeHandler(t, clientHandler)
	closeHandler(t, serverHandler)

	serverEntries := parseEntries(t, serverLogs.String())
	clientEntries := parseEntries(t, clientLogs.String())

	assertGRPCLog(t, serverEntries, "server", "unary", "started call")
	assertGRPCLog(t, serverEntries, "server", "unary", "finished call")
	assertGRPCLog(t, clientEntries, "client", "unary", "started call")
	assertGRPCLog(t, clientEntries, "client", "unary", "finished call")
	assertSeverity(t, serverEntries, "INFO")
	assertSeverity(t, clientEntries, "DEBUG")
}

// startHealthServer starts an in-memory gRPC health service with adapter-backed server logging.
func startHealthServer(t *testing.T, handler *slogcp.Handler) *bufconn.Listener {
	t.Helper()

	listener := bufconn.Listen(bufSize)
	grpcServer := grpc.NewServer(
		grpc.ChainUnaryInterceptor(slogcpadapter.UnaryServerInterceptor(handler, logOptions()...)),
		grpc.ChainStreamInterceptor(slogcpadapter.StreamServerInterceptor(handler, logOptions()...)),
	)

	healthServer := health.NewServer()
	healthServer.SetServingStatus(healthSvc, grpc_health_v1.HealthCheckResponse_SERVING)
	grpc_health_v1.RegisterHealthServer(grpcServer, healthServer)

	errCh := make(chan error, 1)
	go func() {
		errCh <- grpcServer.Serve(listener)
	}()

	t.Cleanup(func() {
		grpcServer.Stop()
		err := <-errCh
		if err != nil && !errors.Is(err, grpc.ErrServerStopped) && !strings.Contains(err.Error(), "closed") {
			t.Fatalf("gRPC server failed: %v", err)
		}
	})

	return listener
}

// newSlogcpHandler creates a slogcp handler suitable for capturing adapter E2E logs.
func newSlogcpHandler(t *testing.T, output *lockedBuffer) *slogcp.Handler {
	t.Helper()

	handler, err := slogcp.NewHandler(output,
		slogcp.WithLevel(slog.LevelDebug),
		slogcp.WithTraceProjectID("adapter-e2e-project"),
	)
	if err != nil {
		t.Fatalf("create slogcp handler: %v", err)
	}
	return handler
}

// closeHandler closes handler and fails the test if slogcp reports a close error.
func closeHandler(t *testing.T, handler *slogcp.Handler) {
	t.Helper()

	if err := handler.Close(); err != nil {
		t.Fatalf("close slogcp handler: %v", err)
	}
}

// logOptions returns the go-grpc-middleware logging options used by the E2E smoke test.
func logOptions() []grpc_logging.Option {
	return []grpc_logging.Option{
		grpc_logging.WithLogOnEvents(grpc_logging.StartCall, grpc_logging.FinishCall),
		grpc_logging.WithFieldsFromContext(func(context.Context) grpc_logging.Fields {
			return grpc_logging.Fields{"adapter.e2e", "true"}
		}),
	}
}

type lockedBuffer struct {
	mu  sync.Mutex
	buf bytes.Buffer
}

// Write appends p to b while holding the buffer lock.
func (b *lockedBuffer) Write(p []byte) (int, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.buf.Write(p)
}

// String returns the buffered log output while holding the buffer lock.
func (b *lockedBuffer) String() string {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.buf.String()
}

type logEntry map[string]any

// parseEntries parses newline-delimited slogcp JSON output into log entries.
func parseEntries(t *testing.T, raw string) []logEntry {
	t.Helper()

	var entries []logEntry
	scanner := bufio.NewScanner(strings.NewReader(raw))
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" {
			continue
		}
		var entry logEntry
		if err := json.Unmarshal([]byte(line), &entry); err != nil {
			t.Fatalf("parse log line %q: %v", line, err)
		}
		entries = append(entries, entry)
	}
	if err := scanner.Err(); err != nil {
		t.Fatalf("scan log output: %v", err)
	}
	if len(entries) == 0 {
		t.Fatalf("expected slogcp JSON output, got none. raw output: %q", raw)
	}
	return entries
}

// assertGRPCLog verifies that entries include the expected go-grpc-middleware log record.
func assertGRPCLog(t *testing.T, entries []logEntry, component, methodType, message string) {
	t.Helper()

	for _, entry := range entries {
		if fmt.Sprint(entry["message"]) != message {
			continue
		}
		if fmt.Sprint(entry["grpc.component"]) != component {
			continue
		}
		if fmt.Sprint(entry["grpc.service"]) != "grpc.health.v1.Health" {
			continue
		}
		if fmt.Sprint(entry["grpc.method"]) != healthMethod {
			continue
		}
		if fmt.Sprint(entry["grpc.method_type"]) != methodType {
			continue
		}
		if fmt.Sprint(entry["adapter.e2e"]) != "true" {
			continue
		}
		return
	}
	t.Fatalf("missing %s %s log for %s; entries=%#v", component, methodType, message, entries)
}

// assertSeverity verifies that at least one log entry was emitted at severity.
func assertSeverity(t *testing.T, entries []logEntry, severity string) {
	t.Helper()

	for _, entry := range entries {
		if fmt.Sprint(entry["severity"]) == severity {
			return
		}
	}
	t.Fatalf("missing severity %s; entries=%#v", severity, entries)
}
