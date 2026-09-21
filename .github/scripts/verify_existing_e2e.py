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

"""Verify PR53's reviewed historical cloud proof without starting cloud work.

This bootstrap accepts unchanged pre-existing content plus three reviewed new
files. It deliberately does not claim that the new commit executed in GCP.
The maintainer must review the exact added blobs before protected integration.
"""

import hashlib
import json
import os
import re
import subprocess
import time


REPO = "pjscruggs/slogcp-grpc-adapter"
BRANCH = "feat/v2-major-release"
PR = 53
TESTED = "2ea38212529a704462df8ebaf9061596e9117e34"
BOOTSTRAP = "aa91cf17a30ebf576ecb719c3fbbcecea9d51ead"
BASE = "1f1c50d00022f378313672e285bc3fd32ed2b41a"
INFRASTRUCTURE = "b60588036a577b6f840ac83c3526adcae8cdcfe3"
RUNTIME_CORE = "26c3370d6c7e8f595d2041a460deba26e801f952"
HISTORICAL_RUN = 35478887283
HISTORICAL_JOB = 105992921373
HISTORICAL_LOG_SHA256 = "183d571a0a83f28f163288461fdc6e25d21e427d78853b6ecbc9f4c1d6b3a980"
WORKFLOW = ".github/workflows/verify-existing-e2e.yml"
ADDITIONS = {
    WORKFLOW,
    ".github/scripts/verify_existing_e2e.py",
    ".github/scripts/test_verify_existing_e2e.py",
}
HISTORICAL_JOBS = {
    HISTORICAL_JOB: ("manual_module_e2e / candidate / Module E2E", "success"),
    105995746136: ("manual_module_e2e / Module E2E", "success"),
    105995756752: ("Module E2E", "success"),
    105992921780: ("Detect Release Intent", "skipped"),
    105992922076: ("Validate Release With Cloud E2E", "skipped"),
    105992922362: ("Create Signed Tag And Release", "skipped"),
    105992932939: ("Validate Release Commit", "skipped"),
}
CLOUD_STEPS = {
    "Authorize candidate and wait for current local validation",
    "Checkout reviewed infrastructure",
    "Checkout exact optional module",
    "Resolve the required core commit",
    "Checkout required core source",
    "Authenticate to the configured GCP project",
    "Run the complete cloud suite with immutable candidates",
    "Require successful full cloud validation",
    "Require unchanged candidate authority",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


class GitHub:
    """Only GET requests to this repository, with bounded complete pagination."""

    def raw(self, path):
        immutable_comparison = re.fullmatch(r"compare/[0-9a-f]{40}\.\.\.[0-9a-f]{40}", path)
        require(not path.startswith("/") and (".." not in path or immutable_comparison),
                "Invalid API path")
        result = subprocess.run(
            ["gh", "api", "--method", "GET", f"repos/{REPO}/{path}"],
            capture_output=True, check=False, timeout=45,
        )
        require(result.returncode == 0, f"GitHub read failed: {path}")
        require(bool(result.stdout), f"Missing evidence: {path}")
        return result.stdout

    def get(self, path):
        return json.loads(self.raw(path))

    def pages(self, path, key):
        values, expected = [], None
        for page in range(1, 101):
            separator = "&" if "?" in path else "?"
            data = self.get(f"{path}{separator}per_page=100&page={page}")
            require(isinstance(data.get("total_count"), int), "Missing page count")
            expected = data["total_count"] if expected is None else expected
            require(data["total_count"] == expected, "Pagination changed during read")
            batch = data.get(key)
            require(isinstance(batch, list), "Missing page data")
            values.extend(batch)
            require(len(values) <= expected, "Overlapping or inconsistent pages")
            if len(values) == expected:
                require(len({v["id"] for v in values}) == expected, "Duplicate evidence")
                return values
            require(len(batch) == 100, "Incomplete pagination")
        raise ValueError("Pagination limit exceeded")


def successful_steps(job, required):
    steps = job.get("steps", [])
    require(len({s["name"] for s in steps}) == len(steps), "Duplicate step names")
    by_name = {s["name"]: s for s in steps}
    for name in required:
        step = by_name.get(name, {})
        require(step.get("status") == "completed" and step.get("conclusion") == "success",
                f"Missing or unsuccessful executed step: {name}")


def validate_run(run, run_id, sha, event, path, branch, completed=True):
    require(run.get("id") == run_id, "Run ID mismatch")
    require(run.get("repository", {}).get("full_name") == REPO, "Run repository mismatch")
    require(run.get("head_repository", {}).get("full_name") == REPO, "Head repository mismatch")
    require(run.get("head_sha") == sha and run.get("head_branch") == branch, "Run source mismatch")
    require(run.get("event") == event and run.get("path") == path, "Run workflow mismatch")
    require(run.get("run_attempt") == 1, "Superseded or repeated attempt")
    if completed:
        require(run.get("status") == "completed" and run.get("conclusion") == "success",
                "Run did not succeed")


def verify_history(api):
    path = f"actions/runs/{HISTORICAL_RUN}"
    for run in (api.get(path), api.get(path + "/attempts/1")):
        validate_run(run, HISTORICAL_RUN, TESTED, "workflow_dispatch",
                     ".github/workflows/auto-release.yml", BRANCH)
        expected = {
            (f"{REPO}/.github/workflows/{name}@{TESTED}", TESTED)
            for name in ("ci-action-smoke.yml", "module-e2e.yml", "validation_pipeline.yml")
        } | {(f"pjscruggs/slogcp/.github/workflows/module-candidate-e2e.yml@{INFRASTRUCTURE}", INFRASTRUCTURE)}
        references = run.get("referenced_workflows", [])
        require(len(references) == len(expected), "Incomplete workflow provenance")
        require({(r["path"], r["sha"]) for r in references} == expected,
                "Referenced workflow identity mismatch")
        for reference in references:
            if reference["sha"] == TESTED:
                require(reference.get("ref") == f"refs/heads/{BRANCH}", "Workflow ref mismatch")
    jobs = api.pages(path + "/attempts/1/jobs", "jobs")
    require({j["id"] for j in jobs} == set(HISTORICAL_JOBS), "Historical job set mismatch")
    for job in jobs:
        name, conclusion = HISTORICAL_JOBS[job["id"]]
        require((job.get("name"), job.get("conclusion"), job.get("status")) ==
                (name, conclusion, "completed"), "Historical job outcome mismatch")
        require((job.get("run_id"), job.get("run_attempt"), job.get("head_sha")) ==
                (HISTORICAL_RUN, 1, TESTED), "Historical job source mismatch")
        if conclusion == "success":
            required = CLOUD_STEPS if job["id"] == HISTORICAL_JOB else {
                "Require the full candidate suite" if job["id"] == 105995746136
                else "Require the full manual candidate suite"
            }
            successful_steps(job, required)
    log = api.raw(f"actions/jobs/{HISTORICAL_JOB}/logs")
    require(hashlib.sha256(log).hexdigest() == HISTORICAL_LOG_SHA256,
            "Historical execution log missing or different from reviewed proof")
    # The digest pins the complete reviewed execution, including immutable
    # source selection, cloud result validation and final authority checks.
    for sha in (TESTED, INFRASTRUCTURE, RUNTIME_CORE):
        require(sha.encode() in log, "Historical source evidence missing")
    validate_run(api.get(path), HISTORICAL_RUN, TESTED, "workflow_dispatch",
                 ".github/workflows/auto-release.yml", BRANCH)


def tree_files(tree):
    require(tree.get("truncated") is False, "Truncated tree evidence")
    entries = tree["tree"]
    require(len({e["path"] for e in entries}) == len(entries), "Duplicate tree paths")
    return {e["path"]: (e["mode"], e["type"], e["sha"])
            for e in entries if e["type"] != "tree"}


def verify_trees(old_tree, new_tree):
    old, new = tree_files(old_tree), tree_files(new_tree)
    require(bool(old), "Empty historical tree")
    require(all(new.get(path) == value for path, value in old.items()),
            "Pre-existing content, path, type or mode changed")
    require(set(new) - set(old) == ADDITIONS, "Unreviewed or missing additions")
    require(all(new[path][:2] == ("100644", "blob") for path in ADDITIONS),
            "Bootstrap additions must be regular files")


def reviewed_commit(api, sha, parent):
    commit = api.get(f"git/commits/{sha}")
    require([p["sha"] for p in commit["parents"]] == [parent],
            "Bootstrap repair parent differs from the exact reviewed chain")
    require(commit.get("verification", {}).get("verified") is True,
            "Bootstrap commit signature is not verified")
    for role in ("author", "committer"):
        require((commit[role]["name"], commit[role]["email"]) ==
                ("pjscruggs", "PatrickJScruggs@gmail.com"), "Bootstrap signer identity mismatch")


def current_authority(api, sha):
    pr = api.get(f"pulls/{PR}")
    require(pr.get("state") == "open" and not pr.get("draft"), "PR53 is not open and ready")
    require((pr["head"]["sha"], pr["head"]["ref"], pr["head"]["repo"]["full_name"]) ==
            (sha, BRANCH, REPO), "PR53 current head mismatch")
    require((pr["base"]["ref"], pr["base"]["sha"], pr["base"]["repo"]["full_name"]) ==
            ("main", BASE, REPO), "Recorded adapter base changed")
    require(api.get("git/ref/heads/main")["object"]["sha"] == BASE, "Current main changed")
    comparison = api.get(f"compare/{BASE}...{sha}")
    require(comparison.get("merge_base_commit", {}).get("sha") == BASE and
            comparison.get("status") == "ahead", "Candidate does not contain current base")
    # Preserve the first signed bootstrap without rewriting history. Only its
    # single direct, reviewed repair is accepted; arbitrary ancestry is not.
    reviewed_commit(api, BOOTSTRAP, TESTED)
    reviewed_commit(api, sha, BOOTSTRAP)


LOCAL_STEPS = {
    "Plan Go Validation": {"Require current PR base", "Test CI support tooling", "Plan repository validation"},
    "Fix and Validate Code": {"Ensure root module metadata is tidy", "Ensure working tree is clean",
                              "Verify linting", "Run root Go tests", "Run root vulnerability check"},
    "Validate Adapter Example": {"Validate adapter example", "Ensure adapter example is clean"},
    "Adapter Local Validation Policy": {"Recheck validated PR identity", "Evaluate adapter local validation result"},
    "Exercise Candidate CI Actions / Exercise CI Actions": {"Exercise App Token Creation", "Verify Action Results And Protocol Requests"},
}


def local_validation(api, sha):
    runs = api.pages(f"actions/workflows/validation_pipeline.yml/runs?event=pull_request&head_sha={sha}",
                     "workflow_runs")
    if not runs:
        return False
    run = max(runs, key=lambda r: r["id"])
    validate_run(run, run["id"], sha, "pull_request", ".github/workflows/validation_pipeline.yml",
                 BRANCH, completed=False)
    if run["status"] != "completed":
        return False
    validate_run(run, run["id"], sha, "pull_request", ".github/workflows/validation_pipeline.yml", BRANCH)
    jobs = api.pages(f'actions/runs/{run["id"]}/attempts/1/jobs', "jobs")
    require(len({j["name"] for j in jobs}) == len(jobs), "Duplicate local jobs")
    names = {j["name"]: j for j in jobs}
    floor = [name for name in names if re.fullmatch(r"Validate Root Compatibility Floor \(Go [^)]+\)", name)]
    require(len(floor) == 1 and set(names) == set(LOCAL_STEPS) | set(floor), "Local job set mismatch")
    for name, job in names.items():
        require((job.get("run_id"), job.get("run_attempt"), job.get("head_sha")) ==
                (run["id"], 1, sha), "Local job source mismatch")
        require(job.get("status") == "completed" and job.get("conclusion") == "success",
                "Substantive local job failed or skipped")
        successful_steps(job, LOCAL_STEPS.get(name, {"Test root module at its compatibility floor"}))
    validate_run(api.get(f'actions/runs/{run["id"]}'), run["id"], sha, "pull_request",
                 ".github/workflows/validation_pipeline.yml", BRANCH)
    return True


def execution_identity(api, env):
    require(env.get("GITHUB_REPOSITORY") == REPO and env.get("GITHUB_EVENT_NAME") == "push" and
            env.get("GITHUB_REF") == f"refs/heads/{BRANCH}", "Bootstrap execution scope mismatch")
    sha = env.get("GITHUB_SHA", "")
    require(re.fullmatch(r"[0-9a-f]{40}", sha) and sha != TESTED, "Invalid new candidate")
    require(env.get("GITHUB_RUN_ATTEMPT") == "1", "Bootstrap rerun is not accepted")
    run_id = int(env["GITHUB_RUN_ID"])
    run = api.get(f"actions/runs/{run_id}")
    validate_run(run, run_id, sha, "push", WORKFLOW, BRANCH, completed=False)
    require(run.get("status") == "in_progress", "Bootstrap run is not active")
    return sha


def verify(api, env, monotonic=time.monotonic, sleep=time.sleep):
    sha = execution_identity(api, env)
    current_authority(api, sha)
    verify_trees(api.get(f"git/trees/{TESTED}?recursive=1"), api.get(f"git/trees/{sha}?recursive=1"))
    verify_history(api)
    deadline = monotonic() + 20 * 60
    while not local_validation(api, sha):
        require(monotonic() < deadline, "Timed out waiting for current local validation")
        current_authority(api, sha)
        print("Waiting for substantive current-head local validation.", flush=True)
        sleep(15)
    current_authority(api, sha)
    execution_identity(api, env)
    require(local_validation(api, sha), "Local validation changed before final acceptance")
    verify_history(api)
    current_authority(api, sha)
    print(f"Verified historical cloud run {HISTORICAL_RUN}, attempt 1 for unchanged content at {TESTED}.")
    print(f"Current local validation covers reviewed bootstrap additions at {sha}.")
    print("The new commit itself has not executed in GCP. No cloud work was started by this verifier.")


if __name__ == "__main__":
    verify(GitHub(), os.environ)
