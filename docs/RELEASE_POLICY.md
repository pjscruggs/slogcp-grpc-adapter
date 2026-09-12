# slogcp-grpc-adapter release policy

[slogcp-grpc-adapter](../README.md) connects go-grpc-middleware's logging
interceptors to a `slog.Logger` backed by slogcp. It is an independently
versioned Go module. Applications that do not use this integration do not
acquire the `go-grpc-middleware` dependency through slogcp itself.

The adapter retains an intentional Go compatibility floor and dependency
minimums. Eligible security repairs prepare patch releases and merge after
validation. Publication requires tests of the exact release commit and an
annotated signed tag. The example and development tools update separately from
the library.

## Go compatibility and dependency requirements

The adapter's compatibility floor is Go 1.27, declared as `go 1.27.0` in
[`go.mod`](../go.mod). Renovate does not update this directive. A higher library
Go requirement needs a deliberate compatibility decision.

The preferred compiler is recorded separately in [the `toolchain`
directive](https://go.dev/blog/toolchain) and can advance without raising the
consumer requirement. CI tests the adapter with a patched compiler on its Go
compatibility line and with its preferred compiler. It uses `GOTOOLCHAIN=local`
and checks the running compiler in each job.

The library's `require` entries are minimum versions. A consuming application's
module graph may select newer versions through [Go's minimal version
selection](https://go.dev/ref/mod#minimal-version-selection). Routine upstream
releases do not automatically increase the adapter's library requirements.
Security fixes and deliberate correctness changes can justify increases,
including changes needed for correct interceptor behavior.

The adapter and slogcp do not share a version counter or a release schedule. The
adapter's required slogcp version is a compatibility requirement, not a
reference to the latest slogcp release. A newer slogcp release or a newer
integration-test companion is not, by itself, a reason to raise that requirement
or publish an adapter release.

## Automated maintenance and release intent

[`renovate.json`](../renovate.json) separates the adapter library, preferred Go
toolchain, example module, CI tools, and GitHub Actions. Eligible updates are
configured for Renovate-owned squash automerge after validation, without a
routine PR-approval step. Renovate rebases branches that fall behind `main`.

Reported vulnerabilities in direct or indirect library dependencies use the
lowest fixed candidate and native Go tooling to tidy the resulting module graph.
Additional dependency changes may be necessary to satisfy that graph. The repair
must pass the adapter's compatibility tests; automatic maintenance must not
raise the library's Go floor to make a dependency update pass.

For a library security repair, Renovate also increments the patch version in
[`version.go`](../version.go). The version change is included in the dependency
PR and its validation. The publisher does not create another version commit.
Repairs to the example or CI tools do not request a library release.

| Change | Maintenance policy | Adapter release intent |
| --- | --- | --- |
| Adapter library security dependency repair | Lowest fixed candidate, native Go dependency resolution, required validation, and automerge | Patch increment in the repair PR |
| Adapter code or dependency correctness fix | Maintainers select the change and its regression coverage | Explicit version increment appropriate to the release |
| Preferred Go toolchain | Update and test the compiler; preserve the library's `go` directive | None |
| Example Go versions and dependencies | Track the latest stable Go release and compatible dependencies; validate the example | None |
| CI tools and GitHub Actions | Execute the changed tools or actions against the candidate | None |
| New slogcp release | Retain the adapter's declared requirement unless an update is justified | None by itself |
| Adapter Go compatibility floor | Explicit compatibility decision, outside routine automated updates | Explicit release decision |

The publisher recognizes an increase in `Version` relative to the preceding
mainline commit. Security labels and commit-message prefixes do not
independently trigger publication. Maintainers choose the version for other
library changes. The automated publisher accepts canonical stable `v0.x.y` and
`v1.x.y` versions for this unsuffixed module path; it does not publish
prerelease or build-metadata versions.

The [example module](../.examples/adapter/go.mod) uses local adapter source and
has its own dependency requirements. Updating it demonstrates use with newer
dependencies without imposing those requirements on adapter consumers. Example
and tooling changes may be included in a later library release, but do not
independently cause one.

## Validation before merge

The [`Validation Pipeline`](../.github/workflows/validation_pipeline.yml) checks
out immutable source commits. It requires compatibility-floor tests,
preferred-compiler validation, example validation, and [candidate-action smoke
tests](../.github/workflows/ci-action-smoke.yml). The final
`Adapter Local Validation Policy` check requires successful results from every
applicable job. A failed, cancelled, or unexpectedly skipped job does not
satisfy that requirement.

The library tests run with the race detector. Preferred-compiler validation also
checks formatting, module tidiness, linting, license headers, and
vulnerabilities. The example has its own formatting, tidy, race-test, and
vulnerability checks. CI helper tests and shell syntax checks validate the
supporting automation.

### Native RPC regression tests

[`TestInterceptorsRPC`](../adapter_integration_test.go) connects a real gRPC
client and server to a real slogcp handler through the adapter's public
interceptor helpers. It uses an in-memory `bufconn` connection rather than a
cloud deployment. It checks unary, client-streaming, server-streaming, and
bidirectional-streaming calls, including success and error results, payloads,
final status, structured fields, and severity.

These tests execute in the adapter's library module. They are the relevant
regression coverage for interceptor completion and callback behavior. Passing a
cloud scenario with a newer middleware version would not establish that the
adapter's declared lower dependency requirement works.

### Tools and compilers

CI tools are declared in [a separate module](../.github/tools/go.mod) and built
by [`install_ci_tools.sh`](../.github/scripts/install_ci_tools.sh). Validation
executes the resulting formatter, linter, license checker, and vulnerability
checker. Formatting and tidy steps must leave the candidate clean, and the
verification commands must pass. Merely printing a changed tool's version is not
sufficient.

The tools compiler is selected separately from the library and example
compilers. A tool needing a newer Go version does not justify increasing the
adapter's consumer requirement. Latest-Go canary runs supplement the normal
required validation rather than replacing it.

### Current-base checks

PR validation first requires the candidate to contain the observed current base.
Before accepting success, it rechecks the head and repository, base branch and
commit, workflow run, and attempt. A changed candidate or base, or a superseded
validation run, requires updated validation.

The [main branch
rules](https://github.com/pjscruggs/slogcp-grpc-adapter/rules/17476192) require
`Adapter Local Validation Policy` and use non-strict status checks. The final
workflow check is not an atomic guarantee that the base cannot move before
merge. The publisher separately runs validation on the exact release commit.

## Release validation and cloud coverage

[`Auto Release`](../.github/workflows/auto-release.yml) starts when a push to
`main` changes `version.go`. It checks for a genuine increasing version
transition and calls the reusable validation workflow on the immutable release
SHA. The signing job requires both successful completion and the workflow's
affirmative validation output. An earlier successful PR check alone is not
enough.

The adapter's release gate is local to this repository. It tests the final
candidate's code and declared module graph; it does not compute a validation
plan from the previous published release. Maintainers therefore need to consider
all unreleased changes when selecting a release version and its regression
coverage, including when the final PR changes only `version.go`.

Combined root-and-adapter cloud runs can provide additional integration
evidence. They are not a required adapter PR check or an automated prerequisite
for adapter publication. The adapter publisher does not consume slogcp's
root-parity cloud receipts. Additional cloud evidence must identify the source
revisions and dependency graph it exercised.

Cloud E2E is appropriate when it exercises a changed integration or cloud
execution path. It is not a routine requirement for example dependency changes,
preferred compiler updates, or native interceptor regressions already exercised
by the RPC tests. Changes to cloud authentication or orchestration still need
validation of those mechanisms before their operation is claimed as tested.

## Signed tags and publication

The publisher creates an annotated SSH-signed tag at the exact validated commit.
It verifies the tag locally before pushing, then requires GitHub to report a
valid signature and verifies the tag's target before publishing the GitHub
release. A conflicting tag causes failure; publication does not move a version
to different source.

The signing job uses the `release-tags` environment and configured signing
identity. It can publish with the repository's workflow token or with a
dedicated, repository-scoped release App token that has Contents write
permission. The App ID and private key must be configured together. Signing keys
are separate from API credentials and are removed from the runner after the
signing step. These credentials do not establish permission to dispatch another
repository's workflow or execute its cloud jobs.

Releases use [GitHub release
immutability](https://docs.github.com/en/code-security/concepts/supply-chain-security/immutable-releases).
The associated tag and attached assets are locked after publication; the title
and release notes can still be corrected. The workflow publishes generated
release notes before making a best-effort request for Go proxy indexing. A proxy
indexing delay does not require a replacement release.

## Recovery

Release runs are serialized without cancelling a running release when another is
queued. The publisher retries transient API and tag-push failures. An existing
tag must be annotated, signature-verified, and attached to the expected commit
before publication can resume. An existing matching published release is a
no-op.

To recover a failed publication, rerun the original workflow for its
version-transition commit. Manual dispatch must also use a mainline transition,
and a requested version must match its `Version`. A later `main` commit with no
version transition is rejected. Retries retain the original version and commit
and re-evaluate validation; they do not create a version bump loop. There is no
scheduled release-recovery reconciler in this workflow.

## Implementation and release records

[`renovate.json`](../renovate.json) defines update scope and patch-version
preparation.
[`validate_renovate_pr.py`](../.github/scripts/validate_renovate_pr.py) checks
candidate scope and version intent. The [validation
workflow](../.github/workflows/validation_pipeline.yml), [release policy
code](../.github/scripts/release_policy.py), and [release
workflow](../.github/workflows/auto-release.yml) implement the checks summarized
here. Policy changes should update this document in the same PR as the
implementation.

Use the [published
releases](https://github.com/pjscruggs/slogcp-grpc-adapter/releases) and
[Actions history](https://github.com/pjscruggs/slogcp-grpc-adapter/actions) to
inspect a release's publication and validation records. Check that version's
tagged `go.mod` for its consumer requirements. Validation added on `main` after
a release is not evidence that the earlier release passed it.
