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

package main

import (
	"context"
	"errors"
	"io"
	"log"
	"net"

	"github.com/pjscruggs/slogcp"
	slogcpadapter "github.com/pjscruggs/slogcp-grpc-adapter"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/health"
	"google.golang.org/grpc/health/grpc_health_v1"
)

// A minimal runnable example that wires slogcp into go-grpc-middleware logging interceptors.
func main() {
	handler, _ := slogcp.NewHandler(io.Discard)

	grpcServer := grpc.NewServer(
		grpc.ChainUnaryInterceptor(slogcpadapter.UnaryServerInterceptor(handler)),
		grpc.ChainStreamInterceptor(slogcpadapter.StreamServerInterceptor(handler)),
	)

	healthServer := health.NewServer()
	healthServer.SetServingStatus("", grpc_health_v1.HealthCheckResponse_SERVING)
	grpc_health_v1.RegisterHealthServer(grpcServer, healthServer)

	lis, err := net.Listen("tcp", ":0")
	if err != nil {
		log.Fatalf("failed to listen: %v", err)
	}
	go func() {
		if serveErr := grpcServer.Serve(lis); serveErr != nil && !errors.Is(serveErr, grpc.ErrServerStopped) {
			log.Fatalf("server error: %v", serveErr)
		}
	}()
	defer grpcServer.Stop()

	// Exercise a simple health check call to prove interceptors can run.
	conn, err := grpc.NewClient(lis.Addr().String(),
		grpc.WithTransportCredentials(insecure.NewCredentials()),
		grpc.WithChainUnaryInterceptor(slogcpadapter.UnaryClientInterceptor(handler)),
		grpc.WithChainStreamInterceptor(slogcpadapter.StreamClientInterceptor(handler)),
	)
	if err != nil {
		log.Fatalf("failed to dial: %v", err)
	}
	defer conn.Close()

	client := grpc_health_v1.NewHealthClient(conn)
	if _, err := client.Check(context.Background(), &grpc_health_v1.HealthCheckRequest{}); err != nil {
		log.Fatalf("health check failed: %v", err)
	}
}
