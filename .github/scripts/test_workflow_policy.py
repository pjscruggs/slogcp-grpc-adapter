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

    def test_validation_uses_immutable_commit_and_race_checks_examples(self) -> None:
        self.assertIn(
            "ref: ${{ github.event.pull_request.head.sha || github.sha }}",
            VALIDATION,
        )
        self.assertIn('(cd "$dir" && go test -race ./...)', VALIDATION)
        self.assertIn('(cd "$dir" && go mod tidy)', VALIDATION)
        self.assertIn("git status --porcelain", VALIDATION)
        self.assertIn(
            "set -euo pipefail\n          go test -json -race",
            VALIDATION,
        )

    def test_latest_go_sync_is_limited_to_its_renovate_pr(self) -> None:
        condition = (
            "github.event_name == 'pull_request' && "
            "contains(github.event.pull_request.labels.*.name, "
            "'renovate:go-version')"
        )
        self.assertEqual(VALIDATION.count(condition), 2)

    def test_validation_prefers_the_pinned_go_toolchain(self) -> None:
        self.assertIn("Using pinned Go toolchain", VALIDATION)
        self.assertIn('echo "version=$TOOLCHAIN_VERSION"', VALIDATION)

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
