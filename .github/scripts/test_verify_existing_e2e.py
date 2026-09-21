"""Negative tests for the one-time, read-only PR53 historical verifier."""

import copy
import hashlib
from pathlib import Path
import unittest
from unittest.mock import patch

import verify_existing_e2e as v


HEAD = "a" * 40
ACTIVE = 123
LOCAL = 124
LOG = (v.TESTED + v.INFRASTRUCTURE + v.RUNTIME_CORE).encode()


def run(run_id, sha, event, path, completed=True):
    return dict(id=run_id, head_sha=sha, head_branch=v.BRANCH, event=event, path=path,
                repository={"full_name": v.REPO}, head_repository={"full_name": v.REPO},
                run_attempt=1, status="completed" if completed else "in_progress",
                conclusion="success" if completed else None)


def job(job_id, name, sha, run_id, steps, conclusion="success"):
    return dict(id=job_id, name=name, head_sha=sha, run_id=run_id, run_attempt=1,
                status="completed", conclusion=conclusion,
                steps=[dict(name=n, status="completed", conclusion="success") for n in steps])


class Fixture:
    def __init__(self):
        historical = run(v.HISTORICAL_RUN, v.TESTED, "workflow_dispatch", ".github/workflows/auto-release.yml")
        historical["referenced_workflows"] = [
            dict(path=f"{v.REPO}/.github/workflows/{n}@{v.TESTED}", sha=v.TESTED,
                 ref=f"refs/heads/{v.BRANCH}")
            for n in ("ci-action-smoke.yml", "module-e2e.yml", "validation_pipeline.yml")
        ] + [dict(path=f"pjscruggs/slogcp/.github/workflows/module-candidate-e2e.yml@{v.INFRASTRUCTURE}",
                  sha=v.INFRASTRUCTURE)]
        old = dict(truncated=False, tree=[dict(path="go.mod", mode="100644", type="blob", sha="b" * 40)])
        new = copy.deepcopy(old)
        new["tree"] += [dict(path=p, mode="100644", type="blob", sha="c" * 40) for p in v.ADDITIONS]
        self.data = {
            f"actions/runs/{v.HISTORICAL_RUN}": historical,
            f"actions/runs/{v.HISTORICAL_RUN}/attempts/1": copy.deepcopy(historical),
            f"actions/runs/{ACTIVE}": run(ACTIVE, HEAD, "push", v.WORKFLOW, False),
            f"actions/runs/{LOCAL}": run(LOCAL, HEAD, "pull_request", ".github/workflows/validation_pipeline.yml"),
            "pulls/53": dict(state="open", draft=False,
                             head=dict(sha=HEAD, ref=v.BRANCH, repo={"full_name": v.REPO}),
                             base=dict(sha=v.BASE, ref="main", repo={"full_name": v.REPO})),
            "git/ref/heads/main": {"object": {"sha": v.BASE}},
            f"compare/{v.BASE}...{HEAD}": dict(status="ahead", merge_base_commit={"sha": v.BASE}),
            f"git/commits/{HEAD}": dict(parents=[{"sha": v.TESTED}], verification={"verified": True},
                                        author=dict(name="pjscruggs", email="PatrickJScruggs@gmail.com"),
                                        committer=dict(name="pjscruggs", email="PatrickJScruggs@gmail.com")),
            f"git/trees/{v.TESTED}?recursive=1": old,
            f"git/trees/{HEAD}?recursive=1": new,
        }
        self.lists = {
            f"actions/runs/{v.HISTORICAL_RUN}/attempts/1/jobs": [
                job(i, name, v.TESTED, v.HISTORICAL_RUN,
                    v.CLOUD_STEPS if i == v.HISTORICAL_JOB else (
                        {"Require the full candidate suite"} if i == 105995746136 else
                        {"Require the full manual candidate suite"} if i == 105995756752 else set()), conclusion)
                for i, (name, conclusion) in v.HISTORICAL_JOBS.items()
            ],
            f"actions/workflows/validation_pipeline.yml/runs?event=pull_request&head_sha={HEAD}":
                [copy.deepcopy(self.data[f"actions/runs/{LOCAL}"])],
            f"actions/runs/{LOCAL}/attempts/1/jobs": [
                job(i, name, HEAD, LOCAL, steps)
                for i, (name, steps) in enumerate(v.LOCAL_STEPS.items())
            ] + [job(99, "Validate Root Compatibility Floor (Go 1.27.x)", HEAD, LOCAL,
                     {"Test root module at its compatibility floor"})],
        }
        self.log = LOG
        self.env = dict(GITHUB_REPOSITORY=v.REPO, GITHUB_EVENT_NAME="push",
                        GITHUB_REF=f"refs/heads/{v.BRANCH}", GITHUB_SHA=HEAD,
                        GITHUB_RUN_ID=str(ACTIVE), GITHUB_RUN_ATTEMPT="1")

    def get(self, path):
        return copy.deepcopy(self.data[path])

    def pages(self, path, _key):
        return copy.deepcopy(self.lists[path])

    def raw(self, path):
        if path != f"actions/jobs/{v.HISTORICAL_JOB}/logs":
            raise AssertionError(path)
        return self.log


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.f = Fixture()
        self.digest = patch.object(v, "HISTORICAL_LOG_SHA256", hashlib.sha256(LOG).hexdigest())
        self.digest.start()
        self.addCleanup(self.digest.stop)

    def test_complete_proof_is_accepted_and_reports_its_limits(self):
        with patch("builtins.print") as output:
            v.verify(self.f, self.f.env)
        self.assertIn("has not executed in GCP", " ".join(str(c) for c in output.call_args_list))

    def test_each_historical_run_identity_mismatch_fails(self):
        path = f"actions/runs/{v.HISTORICAL_RUN}"
        for field, wrong in [("id", 1), ("head_sha", HEAD), ("head_branch", "main"),
                             ("event", "push"), ("path", v.WORKFLOW), ("run_attempt", 2),
                             ("status", "queued"), ("conclusion", "failure"),
                             ("repository", {"full_name": "wrong/repo"}),
                             ("head_repository", {"full_name": "wrong/repo"})]:
            for route in (path, path + "/attempts/1"):
                with self.subTest(field=field, route=route):
                    f = Fixture()
                    f.data[route][field] = wrong
                    with self.assertRaises(ValueError):
                        v.verify_history(f)

    def test_missing_changed_or_extra_workflow_provenance_fails(self):
        for change in (lambda r: r.pop(), lambda r: r.append(r[0]),
                       lambda r: r[0].update(sha=HEAD), lambda r: r[0].update(ref="refs/heads/main")):
            f = Fixture()
            change(f.data[f"actions/runs/{v.HISTORICAL_RUN}"]["referenced_workflows"])
            with self.assertRaises(ValueError):
                v.verify_history(f)

    def test_every_required_cloud_step_rejects_missing_skipped_failed(self):
        path = f"actions/runs/{v.HISTORICAL_RUN}/attempts/1/jobs"
        for name in v.CLOUD_STEPS:
            for conclusion in (None, "skipped", "failure"):
                with self.subTest(name=name, conclusion=conclusion):
                    f = Fixture()
                    steps = f.lists[path][0]["steps"]
                    if conclusion is None:
                        steps[:] = [s for s in steps if s["name"] != name]
                    else:
                        next(s for s in steps if s["name"] == name)["conclusion"] = conclusion
                    with self.assertRaises(ValueError):
                        v.verify_history(f)

    def test_historical_job_identity_failure_and_missing_wrappers_fail(self):
        path = f"actions/runs/{v.HISTORICAL_RUN}/attempts/1/jobs"
        for index in range(3):
            for field, wrong in [("id", 0), ("run_id", 0), ("run_attempt", 2),
                                 ("head_sha", HEAD), ("conclusion", "skipped"), ("status", "queued")]:
                f = Fixture()
                f.lists[path][index][field] = wrong
                with self.subTest(index=index, field=field), self.assertRaises(ValueError):
                    v.verify_history(f)

    def test_missing_or_changed_log_fails(self):
        for log in (b"", LOG + b"different", b"success"):
            self.f.log = log
            with self.assertRaises(ValueError):
                v.verify_history(self.f)

    def test_old_content_mode_type_path_deletion_and_unreviewed_additions_fail(self):
        for change in (lambda t: t["tree"][0].update(sha=HEAD),
                       lambda t: t["tree"][0].update(mode="100755"),
                       lambda t: t["tree"][0].update(type="commit", mode="160000"),
                       lambda t: t["tree"][0].update(mode="120000"),
                       lambda t: t["tree"][0].update(path="renamed"),
                       lambda t: t["tree"].pop(0), lambda t: t["tree"].pop(),
                       lambda t: t["tree"].append(dict(path=".github/unchecked", mode="100644", type="blob", sha=HEAD)),
                       lambda t: t["tree"][1].update(mode="100755"),
                       lambda t: t.update(truncated=True)):
            f = Fixture()
            change(f.data[f"git/trees/{HEAD}?recursive=1"])
            with self.assertRaises(ValueError):
                v.verify_trees(f.data[f"git/trees/{v.TESTED}?recursive=1"],
                               f.data[f"git/trees/{HEAD}?recursive=1"])

    def test_current_pr_base_ancestry_signature_and_parent_mismatches_fail(self):
        mutations = [
            ("pulls/53", lambda p: p.update(state="closed")),
            ("pulls/53", lambda p: p["head"].update(sha=v.TESTED)),
            ("pulls/53", lambda p: p["head"].update(ref="other")),
            ("pulls/53", lambda p: p["base"].update(sha=HEAD)),
            ("git/ref/heads/main", lambda p: p["object"].update(sha=HEAD)),
            (f"compare/{v.BASE}...{HEAD}", lambda p: p.update(status="diverged")),
            (f"compare/{v.BASE}...{HEAD}", lambda p: p["merge_base_commit"].update(sha=HEAD)),
            (f"git/commits/{HEAD}", lambda p: p.update(parents=[{"sha": v.BASE}])),
            (f"git/commits/{HEAD}", lambda p: p["verification"].update(verified=False)),
            (f"git/commits/{HEAD}", lambda p: p["committer"].update(email="other@example.com")),
        ]
        for path, change in mutations:
            f = Fixture()
            change(f.data[path])
            with self.subTest(path=path), self.assertRaises(ValueError):
                v.current_authority(f, HEAD)

    def test_each_substantive_local_job_and_step_must_execute(self):
        path = f"actions/runs/{LOCAL}/attempts/1/jobs"
        for index, original in enumerate(self.f.lists[path]):
            for conclusion in ("failure", "skipped"):
                f = Fixture()
                f.lists[path][index]["conclusion"] = conclusion
                with self.subTest(job=original["name"], conclusion=conclusion), self.assertRaises(ValueError):
                    v.local_validation(f, HEAD)
            for step_index in range(len(original["steps"])):
                f = Fixture()
                f.lists[path][index]["steps"][step_index]["conclusion"] = "skipped"
                with self.assertRaises(ValueError):
                    v.local_validation(f, HEAD)

    def test_stale_failed_and_superseded_local_runs_fail(self):
        path = f"actions/workflows/validation_pipeline.yml/runs?event=pull_request&head_sha={HEAD}"
        for field, value in [("head_sha", v.TESTED), ("event", "workflow_dispatch"),
                             ("run_attempt", 2), ("conclusion", "failure")]:
            f = Fixture()
            f.lists[path][0][field] = value
            with self.assertRaises(ValueError):
                v.local_validation(f, HEAD)

    def test_local_wait_is_bounded_and_rechecks_authority(self):
        path = f"actions/workflows/validation_pipeline.yml/runs?event=pull_request&head_sha={HEAD}"
        self.f.lists[path] = []
        with self.assertRaisesRegex(ValueError, "Timed out"):
            v.verify(self.f, self.f.env, monotonic=iter([0, 1201]).__next__, sleep=lambda _: None)

    def test_base_change_while_waiting_fails(self):
        self.f.lists[f"actions/workflows/validation_pipeline.yml/runs?event=pull_request&head_sha={HEAD}"] = []
        def change(_):
            self.f.data["git/ref/heads/main"]["object"]["sha"] = HEAD
        with self.assertRaisesRegex(ValueError, "Current main changed"):
            v.verify(self.f, self.f.env, monotonic=lambda: 0, sleep=change)

    def test_wrong_execution_scope_and_rerun_fail(self):
        for key, value in [("GITHUB_REPOSITORY", "wrong/repo"), ("GITHUB_EVENT_NAME", "workflow_dispatch"),
                           ("GITHUB_REF", "refs/heads/main"), ("GITHUB_RUN_ATTEMPT", "2"),
                           ("GITHUB_SHA", v.TESTED)]:
            env = dict(self.f.env, **{key: value})
            with self.assertRaises(ValueError):
                v.execution_identity(self.f, env)

    def test_final_head_change_rejects_previously_valid_proof(self):
        original = self.f.get
        reads = 0
        def get(path):
            nonlocal reads
            result = original(path)
            if path == "pulls/53":
                reads += 1
                if reads >= 2:
                    result["head"]["sha"] = v.TESTED
            return result
        self.f.get = get
        with self.assertRaisesRegex(ValueError, "current head mismatch"):
            v.verify(self.f, self.f.env)

    def test_historical_rerun_after_log_read_invalidates_proof(self):
        original = self.f.raw
        def raw(path):
            result = original(path)
            self.f.data[f"actions/runs/{v.HISTORICAL_RUN}"]["run_attempt"] = 2
            return result
        self.f.raw = raw
        with self.assertRaisesRegex(ValueError, "Superseded"):
            v.verify_history(self.f)

    def test_new_failed_local_run_invalidates_prior_success(self):
        path = f"actions/workflows/validation_pipeline.yml/runs?event=pull_request&head_sha={HEAD}"
        newer = copy.deepcopy(self.f.lists[path][0])
        newer.update(id=LOCAL + 1, conclusion="failure")
        self.f.lists[path].append(newer)
        with self.assertRaisesRegex(ValueError, "did not succeed"):
            v.local_validation(self.f, HEAD)


class TransportTests(unittest.TestCase):
    def test_complete_pagination(self):
        api = v.GitHub()
        with patch.object(api, "get", side_effect=[
            dict(total_count=101, jobs=[{"id": n} for n in range(100)]),
            dict(total_count=101, jobs=[{"id": 100}]),
        ]) as get:
            self.assertEqual(len(api.pages("jobs", "jobs")), 101)
        self.assertIn("page=2", get.call_args.args[0])

    def test_pagination_gap_duplicate_and_count_change_fail(self):
        for pages in ([dict(total_count=2, jobs=[{"id": 1}])],
                      [dict(total_count=2, jobs=[{"id": 1}, {"id": 1}])],
                      [dict(total_count=101, jobs=[{"id": n} for n in range(100)]),
                       dict(total_count=102, jobs=[{"id": 100}])]):
            api = v.GitHub()
            with patch.object(api, "get", side_effect=pages), self.assertRaises(ValueError):
                api.pages("jobs", "jobs")

    def test_api_errors_and_missing_evidence_fail_without_writes(self):
        for returncode, stdout in [(1, b"failure"), (0, b"")]:
            with patch.object(v.subprocess, "run") as run_command:
                run_command.return_value.returncode = returncode
                run_command.return_value.stdout = stdout
                with self.assertRaises(ValueError):
                    v.GitHub().raw("actions/jobs/1/logs")
                command = run_command.call_args.args[0]
                self.assertEqual(command[:4], ["gh", "api", "--method", "GET"])


class WorkflowTests(unittest.TestCase):
    def test_bootstrap_trigger_permissions_and_script_digests(self):
        root = Path(__file__).resolve().parents[2]
        workflow = (root / v.WORKFLOW).read_text()
        self.assertIn("branches: [feat/v2-major-release]", workflow)
        self.assertNotIn("workflow_dispatch:", workflow)
        self.assertNotIn("pull_request_target:", workflow)
        self.assertNotIn("id-token:", workflow)
        self.assertNotIn(": write", workflow)
        self.assertNotIn("secrets: inherit", workflow)
        self.assertNotIn("    if:", workflow)
        for permission in ("actions", "checks", "contents", "pull-requests"):
            self.assertIn(f"  {permission}: read", workflow)
        self.assertIn("persist-credentials: false", workflow)
        self.assertIn("actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1", workflow)
        self.assertIn("name: Module E2E", workflow)
        for name in ("verify_existing_e2e.py", "test_verify_existing_e2e.py"):
            path = f".github/scripts/{name}"
            self.assertIn(hashlib.sha256((root / path).read_bytes()).hexdigest() + "  " + path, workflow)


if __name__ == "__main__":
    unittest.main()
