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
	"errors"
	"io"
	"log/slog"
	"net"
	"strings"
	"sync"
	"testing"
	"time"

	grpc_logging "github.com/grpc-ecosystem/go-grpc-middleware/v2/interceptors/logging"
	"github.com/pjscruggs/slogcp"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials/insecure"
	pb "google.golang.org/grpc/interop/grpc_testing"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"
	"google.golang.org/grpc/test/bufconn"
)

// rpcLogBuffer captures concurrent client/server JSON output without a data race.
type rpcLogBuffer struct {
	mu  sync.Mutex
	buf bytes.Buffer
}

// Write appends one handler write atomically.
func (b *rpcLogBuffer) Write(p []byte) (int, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.buf.Write(p)
}

// snapshot returns an independent copy for assertions while RPCs finish.
func (b *rpcLogBuffer) snapshot() []byte {
	b.mu.Lock()
	defer b.mu.Unlock()
	return bytes.Clone(b.buf.Bytes())
}

// rpcTestService uses the generated gRPC interoperability protocol without adding
// another module or code-generation dependency to the library's minimum graph.
type rpcTestService struct {
	pb.UnimplementedTestServiceServer
	result codes.Code
}

// UnaryCall echoes a payload, or returns the selected application error.
func (s *rpcTestService) UnaryCall(_ context.Context, req *pb.SimpleRequest) (*pb.SimpleResponse, error) {
	if err := status.Error(s.result, "test result"); err != nil {
		return nil, err
	}
	return &pb.SimpleResponse{Payload: req.GetPayload()}, nil
}

// StreamingOutputCall sends two messages before returning the selected result.
func (s *rpcTestService) StreamingOutputCall(req *pb.StreamingOutputCallRequest, stream grpc.ServerStreamingServer[pb.StreamingOutputCallResponse]) error {
	for range 2 {
		if err := stream.Send(&pb.StreamingOutputCallResponse{Payload: req.GetPayload()}); err != nil {
			return err
		}
	}
	return status.Error(s.result, "test result")
}

// StreamingInputCall counts all received bytes before returning a response or error.
func (s *rpcTestService) StreamingInputCall(stream grpc.ClientStreamingServer[pb.StreamingInputCallRequest, pb.StreamingInputCallResponse]) error {
	var size int32
	for {
		req, err := stream.Recv()
		if errors.Is(err, io.EOF) {
			break
		}
		if err != nil {
			return err
		}
		size += int32(len(req.GetPayload().GetBody()))
	}
	if err := status.Error(s.result, "test result"); err != nil {
		return err
	}
	return stream.SendAndClose(&pb.StreamingInputCallResponse{AggregatedPayloadSize: size})
}

// FullDuplexCall echoes each message before receiving the next one.
func (s *rpcTestService) FullDuplexCall(stream grpc.BidiStreamingServer[pb.StreamingOutputCallRequest, pb.StreamingOutputCallResponse]) error {
	for {
		req, err := stream.Recv()
		if errors.Is(err, io.EOF) {
			return status.Error(s.result, "test result")
		}
		if err != nil {
			return err
		}
		if err := stream.Send(&pb.StreamingOutputCallResponse{Payload: req.GetPayload()}); err != nil {
			return err
		}
	}
}

// newRPCConnection wires all four public interceptor helpers into a real gRPC
// transport and a real slogcp handler. Only the network socket is in-memory.
func newRPCConnection(t *testing.T, code codes.Code) (*grpc.ClientConn, *rpcLogBuffer) {
	t.Helper()
	logs := &rpcLogBuffer{}
	handler, err := slogcp.NewHandler(logs, slogcp.WithLevel(slog.LevelDebug), slogcp.WithSeverityAliases(false))
	if err != nil {
		t.Fatal(err)
	}
	options := []grpc_logging.Option{
		grpc_logging.WithLogOnEvents(grpc_logging.FinishCall),
		grpc_logging.WithLevels(func(code codes.Code) grpc_logging.Level {
			if code == codes.OK {
				return grpc_logging.Level(slogcp.LevelNotice.Level())
			}
			return grpc_logging.LevelError
		}),
		grpc_logging.WithFieldsFromContext(func(ctx context.Context) grpc_logging.Fields {
			md, ok := metadata.FromIncomingContext(ctx)
			if !ok {
				md, _ = metadata.FromOutgoingContext(ctx)
			}
			return grpc_logging.Fields{"request_id", strings.Join(md.Get("x-request-id"), ",")}
		}),
	}
	listener := bufconn.Listen(1024 * 1024)
	server := grpc.NewServer(
		grpc.ChainUnaryInterceptor(UnaryServerInterceptor(handler, options...)),
		grpc.ChainStreamInterceptor(StreamServerInterceptor(handler, options...)),
	)
	pb.RegisterTestServiceServer(server, &rpcTestService{result: code})
	served := make(chan error, 1)
	go func() { served <- server.Serve(listener) }()
	t.Cleanup(func() {
		server.Stop()
		if err := listener.Close(); err != nil {
			t.Error(err)
		}
		select {
		case err := <-served:
			if err != nil && !errors.Is(err, grpc.ErrServerStopped) {
				t.Error(err)
			}
		case <-time.After(5 * time.Second):
			t.Error("gRPC server did not stop")
		}
	})
	conn, err := grpc.NewClient("passthrough:///adapter-test",
		grpc.WithContextDialer(func(ctx context.Context, _ string) (net.Conn, error) {
			return listener.DialContext(ctx)
		}),
		grpc.WithTransportCredentials(insecure.NewCredentials()),
		grpc.WithChainUnaryInterceptor(UnaryClientInterceptor(handler, options...)),
		grpc.WithChainStreamInterceptor(StreamClientInterceptor(handler, options...)),
	)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		if err := conn.Close(); err != nil {
			t.Error(err)
		}
	})
	return conn, logs
}

// TestInterceptorsRPC validates payloads, final status, structured fields and
// severity for unary and all streaming directions on the root module graph.
func TestInterceptorsRPC(t *testing.T) {
	calls := []struct {
		method string
		invoke func(*testing.T, context.Context, pb.TestServiceClient) error
	}{
		{"UnaryCall", invokeUnary},
		{"StreamingOutputCall", invokeServerStream},
		{"StreamingInputCall", invokeClientStream},
		{"FullDuplexCall", invokeBidiStream},
	}
	for _, call := range calls {
		for _, code := range []codes.Code{codes.OK, codes.PermissionDenied} {
			t.Run(call.method+"/"+code.String(), func(t *testing.T) {
				conn, logs := newRPCConnection(t, code)
				ctx, cancel := context.WithTimeout(t.Context(), 10*time.Second)
				defer cancel()
				ctx = metadata.AppendToOutgoingContext(ctx, "x-request-id", t.Name())
				err := call.invoke(t, ctx, pb.NewTestServiceClient(conn))
				if status.Code(err) != code {
					t.Fatalf("RPC status = %v, want %v: %v", status.Code(err), code, err)
				}
				assertRPCLogs(t, logs, call.method, code)
			})
		}
	}
}

// invokeUnary verifies the successful unary response and returns the RPC status.
func invokeUnary(t *testing.T, ctx context.Context, client pb.TestServiceClient) error {
	t.Helper()
	resp, err := client.UnaryCall(ctx, &pb.SimpleRequest{Payload: &pb.Payload{Body: []byte("unary")}})
	if err == nil && string(resp.GetPayload().GetBody()) != "unary" {
		t.Fatalf("unexpected unary payload: %v", resp)
	}
	return err
}

// invokeServerStream requires both messages, then reads the terminal status.
func invokeServerStream(t *testing.T, ctx context.Context, client pb.TestServiceClient) error {
	t.Helper()
	stream, err := client.StreamingOutputCall(ctx, &pb.StreamingOutputCallRequest{Payload: &pb.Payload{Body: []byte("server")}})
	if err != nil {
		t.Fatal(err)
	}
	for range 2 {
		resp, err := stream.Recv()
		if err != nil || string(resp.GetPayload().GetBody()) != "server" {
			t.Fatalf("unexpected server stream payload: %v, %v", resp, err)
		}
	}
	_, err = stream.Recv()
	return terminalStreamResult(t, err)
}

// invokeClientStream sends multiple messages and checks their aggregate response.
func invokeClientStream(t *testing.T, ctx context.Context, client pb.TestServiceClient) error {
	t.Helper()
	stream, err := client.StreamingInputCall(ctx)
	if err != nil {
		t.Fatal(err)
	}
	for range 2 {
		if err := stream.Send(&pb.StreamingInputCallRequest{Payload: &pb.Payload{Body: []byte("client")}}); err != nil {
			t.Fatal(err)
		}
	}
	resp, err := stream.CloseAndRecv()
	if err == nil && resp.GetAggregatedPayloadSize() != 12 {
		t.Fatalf("unexpected client stream byte count: %v", resp)
	}
	return err
}

// invokeBidiStream verifies each response arrives before the next request.
func invokeBidiStream(t *testing.T, ctx context.Context, client pb.TestServiceClient) error {
	t.Helper()
	stream, err := client.FullDuplexCall(ctx)
	if err != nil {
		t.Fatal(err)
	}
	for _, payload := range []string{"first", "second"} {
		if err := stream.Send(&pb.StreamingOutputCallRequest{Payload: &pb.Payload{Body: []byte(payload)}}); err != nil {
			t.Fatal(err)
		}
		resp, err := stream.Recv()
		if err != nil || string(resp.GetPayload().GetBody()) != payload {
			t.Fatalf("unexpected bidirectional payload: %v, %v", resp, err)
		}
	}
	if err := stream.CloseSend(); err != nil {
		t.Fatal(err)
	}
	_, err = stream.Recv()
	return terminalStreamResult(t, err)
}

// terminalStreamResult distinguishes a completed stream from an extra message.
func terminalStreamResult(t *testing.T, err error) error {
	t.Helper()
	if err == nil {
		t.Fatal("received an unexpected extra stream message")
	}
	if errors.Is(err, io.EOF) {
		return nil
	}
	return err
}

// assertRPCLogs requires exactly one completion from each side, including errors.
func assertRPCLogs(t *testing.T, logs *rpcLogBuffer, method string, code codes.Code) {
	t.Helper()
	decoder := json.NewDecoder(bytes.NewReader(logs.snapshot()))
	seen := make(map[string]int)
	for {
		var record map[string]any
		err := decoder.Decode(&record)
		if errors.Is(err, io.EOF) {
			break
		}
		if err != nil {
			t.Fatal(err)
		}
		component, _ := record["grpc.component"].(string)
		if component != "client" && component != "server" {
			t.Fatalf("unexpected RPC component: %v", record)
		}
		seen[component]++
		severity := "NOTICE"
		if code != codes.OK {
			severity = "ERROR"
			message, _ := record["grpc.error"].(string)
			if !strings.Contains(message, "test result") {
				t.Errorf("missing RPC error: %v", record)
			}
		}
		for key, want := range map[string]string{
			"message": "finished call", "grpc.service": "grpc.testing.TestService",
			"grpc.method": method, "grpc.code": code.String(),
			"request_id": t.Name(), "severity": severity,
		} {
			if record[key] != want {
				t.Errorf("%s = %v, want %q: %v", key, record[key], want, record)
			}
		}
	}
	if seen["client"] != 1 || seen["server"] != 1 {
		t.Fatalf("expected one client and one server completion, got %v: %s", seen, logs.snapshot())
	}
}
