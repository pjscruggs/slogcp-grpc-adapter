# Adapter E2E

This directory is the adapter repo's end-to-end test boundary.

## What Lives Here

- `adapter_smoke_test.go` exercises the adapter's unary client and server
  logging path against a real in-memory gRPC transport.
- `local/run-local.sh` and `local/run-local.ps1` run the adapter E2E smoke test
  locally.
- `cloudbuild/cloudbuild.yaml` runs the same smoke test in Cloud Build.
- `.github/workflows/adapter-e2e-smoke.yml` runs this Cloud Build smoke path
  from GitHub Actions on a manual trigger and a weekly schedule.

## Local Usage

From the repo root:

```bash
cd .e2e
go test -race ./...
```

Or use the wrapper scripts:

```bash
.e2e/local/run-local.sh
```

On Windows PowerShell:

```powershell
.e2e\local\run-local.ps1
```

## GitHub Cloud Build Auth

The GitHub workflow uses Google Cloud Workload Identity Federation rather than
service account keys.

The default project configuration is:

- project: `slogcp`
- provider: configured by repository secret.
- service account: `GCP_SERVICE_ACCOUNT_EMAIL`

The provider is scoped to `pjscruggs/slogcp-grpc-adapter`, and that repository
principal has `roles/iam.workloadIdentityUser` on the Cloud Build submitter
service account.
