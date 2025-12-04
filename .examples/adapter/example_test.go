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
