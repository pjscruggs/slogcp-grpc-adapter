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

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sync_example_go_versions


class _VersionResponse:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def __enter__(self) -> _VersionResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.payload


class SyncExampleGoVersionsTests(unittest.TestCase):
    def test_latest_go_version_parses_first_response_line(self) -> None:
        response = _VersionResponse(b"go1.26.6\ntime 2026-07-01T00:00:00Z\n")
        with mock.patch.object(
            sync_example_go_versions.urllib.request,
            "urlopen",
            return_value=response,
        ):
            self.assertEqual(sync_example_go_versions.latest_go_version(), "1.26.6")

    def test_latest_go_version_rejects_unexpected_response(self) -> None:
        response = _VersionResponse(b"not-a-go-version\n")
        with mock.patch.object(
            sync_example_go_versions.urllib.request,
            "urlopen",
            return_value=response,
        ):
            with self.assertRaisesRegex(ValueError, "unexpected Go version response"):
                sync_example_go_versions.latest_go_version()

    def test_example_go_mods_are_sorted_and_directives_are_read(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            second = root / ".examples" / "zeta" / "go.mod"
            first = root / ".examples" / "alpha" / "go.mod"
            second.parent.mkdir(parents=True)
            first.parent.mkdir(parents=True)
            second.write_text("module example/zeta\n\ngo 1.25.1\n", encoding="utf-8")
            first.write_text("module example/alpha\n\ngo 1.26.6\n", encoding="utf-8")

            self.assertEqual(
                sync_example_go_versions.example_go_mods(root),
                [first, second],
            )
            self.assertEqual(
                sync_example_go_versions.go_directive_version(first),
                "1.26.6",
            )

    def test_sync_uses_explicit_edit_then_tidy_transaction(self) -> None:
        module_dir = Path("example")
        with mock.patch.object(sync_example_go_versions, "run_go_command") as run:
            sync_example_go_versions.sync_go_mod(module_dir / "go.mod", "1.26.6")

        self.assertEqual(
            run.call_args_list,
            [
                mock.call(["go", "mod", "edit", "-go=1.26.6"], module_dir),
                mock.call(["go", "mod", "tidy"], module_dir),
            ],
        )


if __name__ == "__main__":
    unittest.main()
