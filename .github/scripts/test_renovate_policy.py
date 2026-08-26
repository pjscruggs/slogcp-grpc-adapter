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

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
NON_VULNERABILITY = "$not($exists(vulnerabilityFixVersion))"
COMPILER_TOOLS = {
    "github.com/golangci/golangci-lint/v2",
    "golang.org/x/tools",
    "golang.org/x/vuln",
}
AUXILIARY_TOOLS = {
    "github.com/apache/skywalking-eyes",
}


class RenovatePolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = json.loads((ROOT / "renovate.json").read_text(encoding="utf-8"))
        cls.package_rules = cls.config["packageRules"]
        cls.tools_go_mod = (ROOT / ".github/tools/go.mod").read_text(encoding="utf-8")

    def find_rule(self, description: str) -> dict:
        for rule in self.package_rules:
            if rule.get("description") == description:
                return rule
        self.fail(f"rule not found: {description!r}")

    def test_security_alerts_are_enabled_and_not_automerge(self) -> None:
        vulnerability = self.config["vulnerabilityAlerts"]
        self.assertTrue(vulnerability["enabled"])
        self.assertEqual(vulnerability["vulnerabilityFixStrategy"], "lowest")
        self.assertFalse(vulnerability["automerge"])
        self.assertTrue(self.config["osvVulnerabilityAlerts"])
        self.assertFalse(self.config["platformAutomerge"])

        security_floor = self.find_rule(
            "Security floor updates await an explicit release decision"
        )
        self.assertEqual(
            security_floor["matchJsonata"],
            ["$exists(vulnerabilityFixVersion)"],
        )
        self.assertTrue(security_floor["enabled"])
        self.assertFalse(security_floor["dependencyDashboardApproval"])
        self.assertFalse(security_floor["automerge"])

    def test_native_go_module_manages_each_ci_tool_once(self) -> None:
        self.assertNotIn("customManagers", self.config)
        declared_tools = set(
            re.findall(r"^\s*([^\s]+/cmd/[^\s]+)\s*$", self.tools_go_mod, re.MULTILINE)
        )
        expected_tools = {
            "github.com/apache/skywalking-eyes/cmd/license-eye",
            "github.com/golangci/golangci-lint/v2/cmd/golangci-lint",
            "golang.org/x/tools/cmd/goimports",
            "golang.org/x/vuln/cmd/govulncheck",
        }
        self.assertEqual(declared_tools, expected_tools)
        for module in COMPILER_TOOLS | AUXILIARY_TOOLS:
            with self.subTest(module=module):
                self.assertRegex(
                    self.tools_go_mod,
                    rf"(?m)^\s*{re.escape(module)}\s+v\d+\.\d+\.\d+\b",
                )

    def test_ci_dependency_groups_are_disjoint_and_exclude_security_updates(self) -> None:
        actions = self.find_rule(
            "GitHub Actions updates stay separate from executable CI tools"
        )
        compiler = self.find_rule("Compiler-sensitive Go CI tools update together")
        auxiliary = self.find_rule("Auxiliary Go CI tools update separately")

        self.assertEqual(actions["matchManagers"], ["github-actions"])
        self.assertEqual(compiler["matchManagers"], ["gomod"])
        self.assertEqual(auxiliary["matchManagers"], ["gomod"])
        self.assertEqual(compiler["matchFileNames"], [".github/tools/go.mod"])
        self.assertEqual(auxiliary["matchFileNames"], [".github/tools/go.mod"])
        self.assertEqual(set(compiler["matchPackageNames"]), COMPILER_TOOLS)
        self.assertEqual(set(auxiliary["matchPackageNames"]), AUXILIARY_TOOLS)
        self.assertTrue(COMPILER_TOOLS.isdisjoint(AUXILIARY_TOOLS))
        for rule in (actions, compiler, auxiliary):
            self.assertEqual(rule["matchJsonata"], [NON_VULNERABILITY])

    def test_root_and_tools_go_directives_are_not_updated_independently(self) -> None:
        for description, file_name in (
            (
                "Do not automate the adapter's public Go compatibility floor",
                "go.mod",
            ),
            (
                "Do not update the CI tools module Go directive independently",
                ".github/tools/go.mod",
            ),
        ):
            with self.subTest(description=description):
                rule = self.find_rule(description)
                self.assertEqual(rule["matchFileNames"], [file_name])
                self.assertEqual(rule["matchDatasources"], ["golang-version"])
                self.assertEqual(rule["matchDepTypes"], ["golang"])
                self.assertFalse(rule["enabled"])

    def test_routine_root_dependencies_remain_disabled(self) -> None:
        rule = self.find_rule(
            "Do not propose routine root go.mod dependency floor updates"
        )
        self.assertEqual(rule["matchFileNames"], ["go.mod"])
        self.assertEqual(rule["matchDatasources"], ["go"])
        self.assertEqual(rule["matchDepTypes"], ["require"])
        self.assertFalse(rule["enabled"])

    def test_root_toolchain_and_example_updates_are_separate(self) -> None:
        root_toolchain = self.find_rule(
            "Keep the root go.mod toolchain directive on the latest released Go toolchain"
        )
        example_go = self.find_rule(
            "Keep checked-in example module go directives on the latest released Go version"
        )
        example_dependencies = self.find_rule(
            "Routine latest-compatible updates for the checked-in adapter example"
        )

        self.assertEqual(root_toolchain["matchDepTypes"], ["toolchain"])
        self.assertEqual(root_toolchain["matchFileNames"], ["go.mod"])
        self.assertEqual(example_go["matchDatasources"], ["golang-version"])
        self.assertEqual(example_go["matchDepTypes"], ["golang"])
        self.assertEqual(example_go["matchFileNames"], [".examples/adapter/go.mod"])
        self.assertEqual(example_dependencies["matchDatasources"], ["go"])
        self.assertEqual(
            example_dependencies["matchFileNames"], [".examples/adapter/go.mod"]
        )
        for rule in (root_toolchain, example_go, example_dependencies):
            self.assertEqual(rule["matchJsonata"], [NON_VULNERABILITY])

    def test_examples_keep_local_adapter_requirement_pinned(self) -> None:
        rule = self.find_rule(
            "Do not update the local unpublished adapter requirement used by examples"
        )
        self.assertEqual(
            rule["matchPackageNames"],
            ["github.com/pjscruggs/slogcp-grpc-adapter"],
        )
        self.assertFalse(rule["enabled"])


if __name__ == "__main__":
    unittest.main()
