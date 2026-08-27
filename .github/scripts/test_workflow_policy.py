#!/usr/bin/env python3
# Copyright 2025-2026 Patrick J. Scruggs
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import annotations

import pathlib
import re
import subprocess
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
AUTO_RELEASE = (ROOT / ".github/workflows/auto-release.yml").read_text(encoding="utf-8")
VALIDATION = (ROOT / ".github/workflows/validation_pipeline.yml").read_text(
    encoding="utf-8"
)
LATEST_CANARY = (ROOT / ".github/workflows/latest-go-canary.yml").read_text(
    encoding="utf-8"
)
WORKFLOW_SOURCES = {
    path.name: path.read_text(encoding="utf-8")
    for path in (ROOT / ".github/workflows").glob("*.yml")
}
VERSION_SOURCE = (ROOT / "version.go").read_text(encoding="utf-8")


class WorkflowPolicyTests(unittest.TestCase):
    def test_release_requires_explicit_version_intent(self) -> None:
        self.assertIn("paths:\n      - version.go", AUTO_RELEASE)
        self.assertIn("required: true", AUTO_RELEASE)
        self.assertNotIn("security_pr_count", AUTO_RELEASE)
        self.assertNotIn("No root Go module metadata changed", AUTO_RELEASE)

    def test_initial_version_marker_is_non_releasing(self) -> None:
        self.assertIn(
            'git cat-file -e "${BEFORE_SHA}:version.go"',
            AUTO_RELEASE,
        )
        self.assertIn(
            "version.go is being seeded; no release will be created.",
            AUTO_RELEASE,
        )

    def test_push_release_requires_the_version_value_to_change(self) -> None:
        self.assertIn('if [[ "$file_version" != "$previous_version" ]]', AUTO_RELEASE)
        self.assertIn(
            "version.go changed without changing Version; no release will be created.",
            AUTO_RELEASE,
        )

    def test_release_version_is_go_module_compatible(self) -> None:
        self.assertIn("must be canonical vMAJOR.MINOR.PATCH", AUTO_RELEASE)
        self.assertIn("this module can publish only v0 or v1", AUTO_RELEASE)
        self.assertIn("refusing to reuse an immutable module version", AUTO_RELEASE)

    def test_release_can_use_a_ruleset_bypass_app(self) -> None:
        self.assertIn("actions/create-github-app-token@", AUTO_RELEASE)
        self.assertIn(
            "steps.release_app_token.outputs.token || github.token",
            AUTO_RELEASE,
        )

    def test_release_waits_for_the_reusable_validation_workflow(self) -> None:
        self.assertIn(
            "uses: ./.github/workflows/validation_pipeline.yml",
            AUTO_RELEASE,
        )
        self.assertIn(
            "needs.release_preflight.result == 'success'",
            AUTO_RELEASE,
        )

    def test_preflight_uses_full_history_and_requires_the_adapter_example(self) -> None:
        preflight = VALIDATION.split("  root_floor_validation:", 1)[0]
        self.assertIn("fetch-depth: 0", preflight)
        self.assertIn("name: Require current PR base", preflight)
        self.assertIn("git ls-remote", preflight)
        self.assertIn("git merge-base --is-ancestor", preflight)
        self.assertIn(".examples/adapter/go.mod", preflight)
        self.assertIn("exactly the tracked .examples/adapter/go.mod", preflight)
        self.assertIn(".github/tools/go.mod", preflight)

    def test_validation_uses_exact_local_setup_go_runtimes(self) -> None:
        self.assertGreaterEqual(VALIDATION.count("GOTOOLCHAIN: local"), 3)
        self.assertEqual(VALIDATION.count("steps.setup_go.outputs.go-version"), 3)
        self.assertEqual(VALIDATION.count('go env GOTOOLCHAIN)" == "local"'), 3)
        self.assertIn("root_floor_spec", VALIDATION)
        self.assertIn("root_spec", VALIDATION)
        self.assertIn("example_spec", VALIDATION)

    def test_native_ci_tools_are_tidy_logged_and_executed(self) -> None:
        self.assertIn("(cd .github/tools && go mod tidy)", VALIDATION)
        self.assertIn("go list -modfile .github/tools/go.mod -m", VALIDATION)
        for tool in ("golangci-lint", "goimports", "govulncheck", "license-eye"):
            with self.subTest(tool=tool):
                self.assertIn(f".github/tools/go.mod {tool}", VALIDATION)

    def test_root_and_example_validation_are_independent_and_fail_closed(self) -> None:
        self.assertIn("go test -mod=readonly -race -count=1 ./...", VALIDATION)
        self.assertIn("name: Validate Adapter Example", VALIDATION)
        self.assertIn("(cd .examples/adapter && go mod tidy)", VALIDATION)
        self.assertIn(
            "(cd .examples/adapter && go test -race -count=1 ./...)",
            VALIDATION,
        )
        self.assertIn('require_success "Root compatibility validation"', VALIDATION)
        self.assertIn('require_success "Preferred root validation"', VALIDATION)
        self.assertIn('require_success "Adapter example validation"', VALIDATION)
        self.assertNotIn("sync_example_go_versions", VALIDATION)

    def test_required_aggregate_name_and_release_preflight_are_preserved(self) -> None:
        self.assertEqual(VALIDATION.count("name: Adapter Local Validation Policy"), 1)
        self.assertIn("uses: ./.github/workflows/validation_pipeline.yml", AUTO_RELEASE)

    def test_latest_canary_reuses_complete_validation_and_requires_equal_versions(self) -> None:
        self.assertIn("uses: ./.github/workflows/validation_pipeline.yml", LATEST_CANARY)
        self.assertIn("go_validation_mode: latest", LATEST_CANARY)
        self.assertIn("needs.validate_latest_go.result", LATEST_CANARY)
        self.assertIn("needs.validate_latest_go.outputs.validation_passed", LATEST_CANARY)
        self.assertIn("Adapter Latest Go Policy", LATEST_CANARY)
        self.assertIn('[[ "$ROOT_VERSION" != "$EXAMPLE_VERSION" ]]', LATEST_CANARY)
        self.assertNotIn("id-token: write", LATEST_CANARY)

    def test_every_referenced_local_ci_script_exists(self) -> None:
        references: set[str] = set()
        for source in WORKFLOW_SOURCES.values():
            references.update(
                re.findall(r"\.github/scripts/[A-Za-z0-9_.\-/]+", source)
            )

        self.assertTrue(references)
        for reference in sorted(references):
            with self.subTest(reference=reference):
                self.assertTrue((ROOT / reference).is_file(), reference)

    def test_version_is_semver_and_not_older_than_latest_release(self) -> None:
        match = re.search(
            r'^const Version = "(v(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*))"$',
            VERSION_SOURCE,
            flags=re.MULTILINE,
        )
        self.assertIsNotNone(match)
        current = tuple(int(part) for part in match.group(1)[1:].split("."))
        self.assertLessEqual(current[0], 1)

        tags = subprocess.run(
            ["git", "tag", "--list", "v[0-9]*.[0-9]*.[0-9]*"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
        released = [
            tuple(int(part) for part in tag[1:].split("."))
            for tag in tags
            if re.fullmatch(r"v\d+\.\d+\.\d+", tag)
        ]
        if released:
            self.assertGreaterEqual(current, max(released))


if __name__ == "__main__":
    unittest.main()
