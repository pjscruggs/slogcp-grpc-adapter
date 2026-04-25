# Adapter E2E

This directory is the adapter repo's end-to-end test boundary.

## What Lives Here

- `adapter_smoke_test.go` exercises the adapter's unary client and server
  logging path against a real in-memory gRPC transport.
- `cloudbuild/cloudbuild.yaml` runs the same smoke test in Cloud Build.
- `.github/workflows/adapter-e2e-smoke.yml` runs this Cloud Build smoke path
  from GitHub Actions on a manual trigger and a weekly schedule.
