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

// Package slogcpadapter wires [github.com/pjscruggs/slogcp] into
// [github.com/grpc-ecosystem/go-grpc-middleware/v2] logging interceptors.
// It implements logging.Logger by forwarding records to a slog.Logger backed by a
// slogcp handler, stringifying key/value pairs from the middleware into slog.Attr
// values and preserving the gRPC context for trace propagation. When no handler
// or logger is supplied, the adapter falls back to slog.Default so existing
// slogcp defaults still apply.
//
// The helpers UnaryServerInterceptor, StreamServerInterceptor, UnaryClientInterceptor
// and StreamClientInterceptor wrap the middleware logging interceptors, keeping the
// same options surface (for example grpc_logging.WithFieldsFromContext or
// grpc_logging.WithLevels) while avoiding boilerplate.
//
// Quick start:
//
//	handler, _ := slogcp.NewHandler(os.Stdout)
//
//	server := grpc.NewServer(
//		grpc.ChainUnaryInterceptor(slogcpadapter.UnaryServerInterceptor(handler)),
//		grpc.ChainStreamInterceptor(slogcpadapter.StreamServerInterceptor(handler)),
//	)
//
//	conn, _ := grpc.NewClient(
//		addr,
//		grpc.WithTransportCredentials(insecure.NewCredentials()),
//		grpc.WithChainUnaryInterceptor(slogcpadapter.UnaryClientInterceptor(handler)),
//		grpc.WithChainStreamInterceptor(slogcpadapter.StreamClientInterceptor(handler)),
//	)
//
// Customization hooks WithLogger and WithLevelMapper let you reuse an existing
// slog.Logger (for example one shared across components) and adjust how
// grpc_logging.Level values map to slog.Level so slogcp severity tuning carries
// through to gRPC logs.
package slogcpadapter
