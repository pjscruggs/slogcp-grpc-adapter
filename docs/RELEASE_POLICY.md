# Release policy

[slogcp-grpc-adapter](../README.md) connects go-grpc-middleware logging
interceptors to a `slog.Logger` backed by slogcp. Its module path is
`github.com/pjscruggs/slogcp-grpc-adapter/v2` and it uses
`github.com/pjscruggs/slogcp/v2` for handler types and request context values.
Applications choose the adapter separately from the core library.

## Compatibility and dependencies

The public Go compatibility floor and minimum dependency versions are recorded
in [`go.mod`](../go.mod). Raising the compatibility floor requires a deliberate
decision. Renovate maintains the preferred compiler through the separate
`toolchain` directive.

CI tests the declared dependency graph with the race detector on both the
compatibility compiler and the preferred compiler. It checks the actual Go
runtime with `GOTOOLCHAIN=local`. The separately versioned example uses its own
compiler and dependencies.

Applications may select newer dependencies through Go module resolution.
Routine upstream releases leave the library's minimum requirements unchanged.
Security repairs and correctness fixes can justify raising those requirements.
The adapter and core library have independent release schedules.

## Automated maintenance

[`renovate.json`](../renovate.json) separates library security repairs, compiler
updates, example dependencies, CI tools, and GitHub Actions. Eligible updates
use squash automerge after the required validation succeeds against current
`main`. Renovate rebases branches when their base advances.

Library security repairs select the lowest fixed dependency versions and tidy
the resulting Go graph. They also increment `Version` in
[`version.go`](../version.go) to prepare a patch release. Validation rejects
changes that raise the compatibility floor through routine maintenance.

Example and tooling updates run their own substantive checks. They do not
increment the library version. Updated reusable E2E pins track the core main
branch through an immutable digest. The cloud gate executes changed
infrastructure after confirming it belongs to reviewed core main history.

## Validation before merge

[`Validation Pipeline`](../.github/workflows/validation_pipeline.yml) checks
formatting, module tidiness, license headers, lint, vulnerabilities, race tests,
example behavior, and candidate CI actions. The final
`Adapter Local Validation Policy` requires every expected job to succeed.
Failed, cancelled, skipped, or missing required work prevents acceptance.

The native RPC tests exercise unary, client-streaming, server-streaming, and
bidirectional-streaming calls using an in-memory gRPC connection. They cover
interceptor completion, payloads, status fields, severity, and trace context
with the adapter's declared middleware requirement.

[`Module E2E`](../.github/workflows/module-e2e.yml) additionally runs the complete
cloud suite with exact adapter and core commits. The suite includes Cloud
Logging API delivery, Pub/Sub propagation, HTTP propagation, and gRPC
interceptor behavior. It preserves the supplied module sources and records the
combined dependency graph selected by Go.

The [branch rules](https://github.com/pjscruggs/slogcp-grpc-adapter/rules) require
both local validation and `Module E2E`. Local and cloud gates recheck the live
PR head and base before accepting success. Changed source or a changed base
requires fresh validation.

A maintainer can dispatch the module E2E workflow with a PR number for an
initial workflow migration. A dispatch from a feature branch must execute that
PR's exact commit. Cloud access still depends on the configured federation
policy for the selected workflow.

Before the module workflow exists on main, the registered Auto Release
workflow accepts the same optional PR number. This explicit mode runs the
complete candidate proof and disables release publication.

## Release publication

[`Auto Release`](../.github/workflows/auto-release.yml) runs when a main branch
commit changes `version.go`. It requires a strictly increasing stable semantic
version. Maintainers choose the version for library changes other than
automated security repairs.

The publisher reruns local validation and the complete cloud suite on the
immutable release commit. Both must succeed before the signing job can create
an annotated SSH-signed tag. Publication verifies the signature and tag target.
A conflicting tag fails publication without moving the existing tag.

The signing job uses the `release-tags` environment and its configured signer
identity. Release App credentials and the signing key are separate from cloud
authentication. The runner removes its signing material after use. Environment
protection restricts the release credentials to main branch publication.

The workflow publishes release notes and requests Go proxy indexing. A delayed
proxy refresh can finish after the tag and release are available.

## Recovery

Release runs are serialized. To recover a failure, rerun the original workflow
for its version-transition commit. Manual release dispatch must use that same
mainline transition and its declared version. A later commit with no version
transition cannot create a replacement publication.

An existing matching signed tag or published release can be reused after its
identity is verified. Transient publication failures are retried. Recovery
retains the original version and commit and repeats the required validation.

The [release policy code](../.github/scripts/release_policy.py),
[Renovate scope validator](../.github/scripts/validate_renovate_pr.py), and
workflow files define the executable policy. Consult the
[Actions history](https://github.com/pjscruggs/slogcp-grpc-adapter/actions) and
[published releases](https://github.com/pjscruggs/slogcp-grpc-adapter/releases)
for the validation and publication records of a particular commit.
