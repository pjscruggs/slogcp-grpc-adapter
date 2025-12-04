package main

import (
	"io"

	"github.com/pjscruggs/slogcp"
	slogcpadapter "github.com/pjscruggs/slogcp-grpc-adapter"
	"google.golang.org/grpc"
)

// This example demonstrates wiring slogcp into go-grpc-middleware logging
// interceptors using the adapter. It builds (and will run if invoked), proving
// the adapter satisfies the middleware Logger interface.
func ExampleUnaryServerInterceptor() {
	handler, _ := slogcp.NewHandler(io.Discard)

	server := grpc.NewServer(
		grpc.ChainUnaryInterceptor(slogcpadapter.UnaryServerInterceptor(handler)),
		grpc.ChainStreamInterceptor(slogcpadapter.StreamServerInterceptor(handler)),
	)

	defer server.Stop()
	// Output:
}
