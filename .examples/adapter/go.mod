module github.com/pjscruggs/slogcp-grpc-adapter/examples/adapter

go 1.26.4

require (
	github.com/pjscruggs/slogcp v1.2.4
	github.com/pjscruggs/slogcp-grpc-adapter v0.0.0
	google.golang.org/grpc v1.81.1
)

require (
	cloud.google.com/go/compute/metadata v0.9.0 // indirect
	github.com/GoogleCloudPlatform/opentelemetry-operations-go/propagator v0.56.0 // indirect
	github.com/cespare/xxhash/v2 v2.3.0 // indirect
	github.com/go-logr/logr v1.4.3 // indirect
	github.com/go-logr/stdr v1.2.2 // indirect
	github.com/grpc-ecosystem/go-grpc-middleware/v2 v2.3.3 // indirect
	go.opentelemetry.io/auto/sdk v1.2.1 // indirect
	go.opentelemetry.io/otel v1.43.0 // indirect
	go.opentelemetry.io/otel/metric v1.43.0 // indirect
	go.opentelemetry.io/otel/trace v1.43.0 // indirect
	golang.org/x/net v0.55.0 // indirect
	golang.org/x/sys v0.45.0 // indirect
	golang.org/x/text v0.37.0 // indirect
	google.golang.org/genproto/googleapis/rpc v0.0.0-20260420184626-e10c466a9529 // indirect
	google.golang.org/protobuf v1.36.11 // indirect
)

replace github.com/pjscruggs/slogcp-grpc-adapter => ../..
