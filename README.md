# slogcp-grpc-adapter

An adapter that lets the [slogcp](https://github.com/pjscruggs/slogcp) structured logging handler plug directly into the [go-grpc-middleware](https://github.com/grpc-ecosystem/go-grpc-middleware) logging interceptors.

`slogcp-grpc-adapter` implements the `logging.Logger` interface from `github.com/grpc-ecosystem/go-grpc-middleware/v2/interceptors/logging` using a `*slog.Logger` backed by `slogcp`. This lets you:

- Keep using go-grpc-middleware's logging interceptors for unary and streaming RPCs (on both client and server).
- Emit JSON logs shaped for Google Cloud Logging / Error Reporting / Cloud Trace via slogcp.
- Preserve request-scoped loggers, attributes, and trace context coming from `context.Context`.

It lives in its own module so that `github.com/grpc-ecosystem/go-grpc-middleware` is *not* a dependency of slogcp itself. Projects that want this integration can opt in to the adapter without affecting the core slogcp module graph.

## Installation

```bash
go get github.com/pjscruggs/slogcp-grpc-adapter
```

You will usually also want:

- `github.com/pjscruggs/slogcp` – the Google Cloud friendly `slog.Handler`.
- `github.com/grpc-ecosystem/go-grpc-middleware/v2/interceptors/logging` – the gRPC logging interceptors this adapter plugs into.

## Why Would I Use This?

### Who is this for?

This adapter is for you if:

1. **You are already using go-grpc-middleware for gRPC logging.**  
   Your services rely on the `interceptors/logging` package to log method names, status codes, latencies, payload sizes, and peer info for unary and streaming RPCs.

2. **You want those logs to be Google Cloud native.**  
   You want Cloud Logging to see `severity` instead of `level`, you want trace IDs in `logging.googleapis.com/trace` / `spanId` / `trace_sampled`, and you want Error Reporting to group RPC failures based on stack traces and `serviceContext`.

3. **You prefer stdout JSON over direct Cloud Logging clients.**  
   Like `slogcp`, this adapter keeps logging as JSON to `stdout` or to whatever writer you configure, letting Google Cloud's logging ingester do the heavy lifting. You keep the ergonomic `slog` APIs plus go-grpc-middleware's interceptor wiring.

### How does this fit with slogcp and go-grpc-middleware?

- [`slogcp`](https://github.com/pjscruggs/slogcp) gives you a `slog.Handler` that understands Google Cloud's logging, trace, and error-reporting conventions, plus HTTP and gRPC integrations of its own (`slogcpgrpc`).
- [`go-grpc-middleware`](https://github.com/grpc-ecosystem/go-grpc-middleware) gives you generic, pluggable gRPC interceptors for logging, metrics, retries, auth, validation, and more.
- `slogcp-grpc-adapter` is a **thin bridge** between the two: it implements go-grpc-middleware's `logging.Logger` using a `*slog.Logger` built on `slogcp`, so your existing interceptor chains can emit Cloud Logging–friendly JSON without rewriting your middleware configuration.

Use it when you want to keep the go-grpc-middleware logging story (including its context field injection and per-RPC metadata) while standardizing on slogcp as your logging backend for Google Cloud.

## Features

### Adapts go-grpc-middleware logging to slogcp

The core type in this module is `*slogcpadapter.Logger`, which:

- Implements `logging.Logger` from `github.com/grpc-ecosystem/go-grpc-middleware/v2/interceptors/logging`.
- Forwards calls to a `*slog.Logger` backed by a `*slogcp.Handler`.
- Preserves the `context.Context` passed in by go-grpc-middleware so `slogcp` can attach trace correlation fields (`logging.googleapis.com/trace`, etc.) and Error Reporting metadata.

The adapter converts the variadic key/value pairs used by go-grpc-middleware into structured `slog.Attr` values:

- Keys are coerced to strings using `fmt.Sprint`.
- Values are wrapped as `slog.Any` so they serialize naturally into JSON.

### Severity mapping and GCP levels

go-grpc-middleware defines its own `Level` enum using the same numeric scheme as `log/slog` (for example, `LevelDebug = -4`, `LevelInfo = 0`, `LevelWarn = 4`, `LevelError = 8`). The adapter's default mapping simply converts `logging.Level` into `slog.Level`:

- With the default go-grpc-middleware `WithLevels` configuration, `LevelDebug`/`LevelInfo`/`LevelWarn`/`LevelError` map 1:1 onto `slog` and therefore to the expected Cloud Logging severities via slogcp.
- If you customize `logging.WithLevels` to return intermediate integer levels (for example values matching `slogcp.LevelNotice`, `slogcp.LevelCritical`, `slogcp.LevelAlert`, `slogcp.LevelEmergency`, or `slogcp.LevelDefault`), those numeric levels are preserved and flow through to slogcp, unlocking the full range of GCP severities for gRPC logs.

If you need completely different semantics, you can still supply your own mapping function via `WithLevelMapper` (see **Customization** below).

### Works with your existing slog defaults

`NewLogger` supports a few construction paths so you can fit it into your existing logging setup:

- **Provide a `*slogcp.Handler`.**  
  The adapter builds a fresh `*slog.Logger` around the handler, giving you a dedicated logger for gRPC interceptors.

- **Provide a `*slog.Logger`.**  
  Use `WithLogger` to reuse an existing logger (for example, your app's default logger) so gRPC logs share the same configuration, attributes, and output destination.

- **Let it fall back to `slog.Default()`.**  
  If you don’t pass a handler or logger, the adapter uses the process-wide default `*slog.Logger`, which is often already configured with a `slogcp` handler in slogcp-based services.

### Drop-in interceptor helpers

To make wiring easy, the package exposes helpers that mirror go-grpc-middleware's logging interceptors but pre-wired with a `slogcp` handler:

- `UnaryServerInterceptor(handler *slogcp.Handler, opts ...logging.Option) grpc.UnaryServerInterceptor`.
- `StreamServerInterceptor(handler *slogcp.Handler, opts ...logging.Option) grpc.StreamServerInterceptor`.
- `UnaryClientInterceptor(handler *slogcp.Handler, opts ...logging.Option) grpc.UnaryClientInterceptor`.
- `StreamClientInterceptor(handler *slogcp.Handler, opts ...logging.Option) grpc.StreamClientInterceptor`.

These simply construct a `*slogcpadapter.Logger` for you and pass it into the corresponding go-grpc-middleware interceptors. You can still use all of go-grpc-middleware's logging options (for example, `WithFieldsFromContext`) to control what gets logged per RPC.

## Quick Start

The examples below show how to wire slogcp, this adapter, and go-grpc-middleware's interceptors together. They intentionally focus on the logging pieces; for full observability (tracing, metrics) you will typically also add OpenTelemetry `otelgrpc` and other interceptors from the `grpc-ecosystem` project.

### Server: basic logging with slogcp

```go
package main

import (
	"log"
	"log/slog"
	"net"
	"os"

	grpc_logging "github.com/grpc-ecosystem/go-grpc-middleware/v2/interceptors/logging"
	"github.com/pjscruggs/slogcp"
	"github.com/pjscruggs/slogcp-grpc-adapter"
	"google.golang.org/grpc"
)

func main() {
	handler, err := slogcp.NewHandler(os.Stdout)
	if err != nil {
		log.Fatalf("configure slogcp: %v", err)
	}
	logger := slog.New(handler)
	slog.SetDefault(logger)

	adapted := slogcpadapter.NewLogger(handler)

	grpcServer := grpc.NewServer(
		grpc.ChainUnaryInterceptor(
			grpc_logging.UnaryServerInterceptor(adapted),
		),
		grpc.ChainStreamInterceptor(
			grpc_logging.StreamServerInterceptor(adapted),
		),
	)

	lis, err := net.Listen("tcp", ":8080")
	if err != nil {
		log.Fatalf("listen: %v", err)
	}
	if err := grpcServer.Serve(lis); err != nil {
		log.Fatalf("serve: %v", err)
	}
}
```

If you prefer, you can skip `NewLogger` and use the convenience helpers:

```go
grpcServer := grpc.NewServer(
	grpc.ChainUnaryInterceptor(
		slogcpadapter.UnaryServerInterceptor(handler),
	),
	grpc.ChainStreamInterceptor(
		slogcpadapter.StreamServerInterceptor(handler),
	),
)
```

Either way, go-grpc-middleware will call into the adapter for each RPC, and the resulting logs will be emitted through slogcp's handler with Google Cloud–friendly JSON and trace correlation.

### Client: logging outbound RPCs

On the client side, you can reuse the same handler (or logger) to observe outbound RPCs:

```go
conn, err := grpc.NewClient(
	addr,
	grpc.WithTransportCredentials(insecure.NewCredentials()), // use real TLS creds in production
	grpc.WithChainUnaryInterceptor(slogcpadapter.UnaryClientInterceptor(handler)),
	grpc.WithChainStreamInterceptor(slogcpadapter.StreamClientInterceptor(handler)),
)
if err != nil {
	log.Fatalf("dial: %v", err)
}
defer conn.Close()

client := myservicepb.NewMyServiceClient(conn)
_ = client
```

Because the adapter always receives a `context.Context`, logs for outbound RPCs can still participate in OpenTelemetry tracing and Cloud Logging trace correlation, as long as there is an active span on the context and `slogcp` is configured normally.

## Customization

### Reusing an existing slog logger

If you already have a configured `*slog.Logger` (for example, with global attributes, source locations, or async wrappers), you can tell the adapter to use it directly:

```go
base := slog.New(handler)
adapted := slogcpadapter.NewLogger(nil, slogcpadapter.WithLogger(base))

grpcServer := grpc.NewServer(
	grpc.ChainUnaryInterceptor(
		grpc_logging.UnaryServerInterceptor(adapted),
	),
)
```

In this mode, the `handler` argument to `NewLogger` is optional; the adapter will prefer the provided logger and only fall back to building a logger from the handler when no logger is supplied.

### Custom level mapping

By default, the adapter passes `logging.Level` through to `slog.Level`, which works well with slogcp's extended severity levels when you customize `logging.WithLevels`. If you need finer control over how go-grpc-middleware's logging levels map onto slog (and thus Cloud Logging severities), provide a custom mapper:

```go
mapper := func(level grpc_logging.Level) slog.Level {
	switch level {
	case grpc_logging.LevelDebug:
		return slog.LevelDebug
	case grpc_logging.LevelInfo:
		return slog.LevelInfo
	case grpc_logging.LevelWarn, grpc_logging.LevelError:
		return slog.LevelError
	default:
		return slog.LevelInfo
	}
}

adapted := slogcpadapter.NewLogger(handler, slogcpadapter.WithLevelMapper(mapper))
_ = adapted
```

You can also combine this with a custom `logging.WithLevels` configuration that returns values matching `slogcp.LevelNotice`, `slogcp.LevelCritical`, `slogcp.LevelAlert`, `slogcp.LevelEmergency`, or `slogcp.LevelDefault` to take full advantage of GCP's severity range for gRPC logs.

## How This Plays With slogcp's Native gRPC Integration

The main `slogcp` repository already offers its own gRPC helpers in the `slogcpgrpc` package, which provide interceptors wired with OpenTelemetry stats handlers and trace propagation.

This adapter does **not** replace `slogcpgrpc`; instead it gives you another integration point:

- Use `slogcpgrpc` when you want a **single, opinionated package** that handles slogcp logging, trace correlation, and OpenTelemetry wiring for gRPC.
- Use `slogcp-grpc-adapter` when you already rely on the broader [`go-grpc-middleware`](https://github.com/grpc-ecosystem/go-grpc-middleware) ecosystem (auth, retry, selector, prometheus providers, etc.) and you simply want its logging interceptors to emit slogcp/Cloud Logging–compatible JSON.

In more complex setups you can mix both: for example, use `slogcpgrpc` for servers that you fully control, but use `slogcp-grpc-adapter` in services where go-grpc-middleware logging interceptors are already deeply embedded or where you benefit from its `logging.WithFieldsFromContext` ecosystem.

## License

[Apache 2.0](LICENSE)

## Contributing

Contributions are welcome! Feel free to submit issues for bugs or feature requests. For code contributions, please fork the repository, create a feature branch, and submit a pull request with your changes.
