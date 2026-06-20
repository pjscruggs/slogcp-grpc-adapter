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
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]


class RenovatePolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = json.loads((ROOT / "renovate.json").read_text(encoding="utf-8"))
        cls.package_rules = cls.config.get("packageRules", [])

    def find_rule(self, description: str) -> dict:
        for rule in self.package_rules:
            if rule.get("description") == description:
                return rule
        self.fail(f"rule not found: {description!r}")

    def test_security_alerts_are_enabled(self) -> None:
        vuln = self.config.get("vulnerabilityAlerts", {})
        self.assertTrue(vuln.get("enabled"))
        self.assertEqual(vuln.get("vulnerabilityFixStrategy"), "lowest")
        self.assertTrue(self.config.get("osvVulnerabilityAlerts"))

    def test_workflow_go_install_pins_are_managed(self) -> None:
        managers = self.config.get("customManagers", [])
        self.assertTrue(
            any(
                manager.get("description")
                == "Update go install tool pins used by GitHub Actions workflows"
                for manager in managers
            )
        )

    def test_ci_dependency_updates_stay_under_github(self) -> None:
        rule = self.find_rule("CI-only dependency updates stay under .github")
        self.assertEqual(rule.get("matchManagers"), ["github-actions", "custom.regex"])
        self.assertEqual(rule.get("matchFileNames"), [".github/**"])
        self.assertIn("dependency-scope:ci", rule.get("labels", []))

    def test_routine_root_floor_updates_are_disabled(self) -> None:
        rule = self.find_rule(
            "Do not propose routine root go.mod dependency floor updates"
        )
        self.assertEqual(rule.get("matchFileNames"), ["go.mod"])
        self.assertEqual(rule.get("matchDatasources"), ["go"])
        self.assertEqual(rule.get("matchDepTypes"), ["require"])
        self.assertFalse(rule.get("enabled"))

    def test_security_floor_updates_are_enabled(self) -> None:
        rule = self.find_rule(
            "Security floor updates must not wait for normal root Dependency Dashboard approval"
        )
        self.assertEqual(rule.get("matchFileNames"), ["go.mod"])
        self.assertEqual(rule.get("matchJsonata"), ["$exists(vulnerabilityFixVersion)"])
        self.assertTrue(rule.get("enabled"))
        self.assertFalse(rule.get("dependencyDashboardApproval"))
        self.assertTrue(rule.get("automerge"))
        self.assertEqual(rule.get("automergeType"), "pr")
        self.assertEqual(rule.get("automergeStrategy"), "squash")

    def test_root_toolchain_updates_are_automerge(self) -> None:
        rule = self.find_rule(
            "Keep the root go.mod toolchain directive on the latest released Go toolchain"
        )
        self.assertEqual(rule.get("matchDepTypes"), ["toolchain"])
        self.assertFalse(rule.get("dependencyDashboardApproval"))
        self.assertTrue(rule.get("automerge"))
        self.assertEqual(rule.get("automergeType"), "pr")

    def test_examples_keep_local_adapter_requirement_pinned(self) -> None:
        rule = self.find_rule(
            "Do not update the local unpublished adapter requirement used by examples"
        )
        self.assertEqual(rule.get("matchFileNames"), [".examples/**"])
        self.assertEqual(
            rule.get("matchPackageNames"),
            ["github.com/pjscruggs/slogcp-grpc-adapter"],
        )
        self.assertFalse(rule.get("enabled"))

    def test_example_dependency_updates_are_automerge(self) -> None:
        rule = self.find_rule(
            "Routine latest-compatible updates for checked-in example modules"
        )
        self.assertEqual(rule.get("matchFileNames"), [".examples/**"])
        self.assertTrue(rule.get("automerge"))
        self.assertEqual(rule.get("automergeType"), "pr")
        self.assertEqual(rule.get("automergeStrategy"), "squash")

    def test_no_adapter_e2e_rules_remain(self) -> None:
        for rule in self.package_rules:
            self.assertNotIn(".e2e/**", rule.get("matchFileNames", []))
            self.assertNotIn(".e2e/**/go.mod", rule.get("matchFileNames", []))


if __name__ == "__main__":
    unittest.main()
