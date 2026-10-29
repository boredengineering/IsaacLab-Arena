# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Import-safe proof rejection tests, not substitutes for real process runs."""
import copy
import unittest

from revision_process_checks import assert_resync, validate_death


class DeathProofChecks(unittest.TestCase):
    def test_exit_137_alone_is_never_intentional_kill(self):
        with self.assertRaises(AssertionError):
            validate_death({"exit": 137}, None, None)

    def test_resync_requires_each_real_file_and_ancestor(self):
        state = "/private/after-promotion/state"
        area = state + "/editor-revision-bundles"
        bundle = area + "/" + "a" * 32
        paths = [state, area, bundle, *[bundle + "/" + name for name in
                 ("manifest.json", "snapshot.json", "export.yaml")]]
        proof = {"case": "after-promotion", "revision_id": "a" * 32, "successful_fsync_paths": paths}
        assert_resync(proof)
        for missing in paths:
            with self.subTest(missing=missing), self.assertRaises(AssertionError):
                assert_resync(dict(proof, successful_fsync_paths=[p for p in paths if p != missing]))

    def test_reject_oom_or_ack_or_wrong_failpoint_or_identity(self):
        witness = {"status": "failpoint-reached", "failpoint": "partial-payload", "case": "partial-payload",
                   "signal": "SIGKILL", "ack_emitted": False, "run": "owned", "invocation": "kill",
                   "oom_before_kill": {"oom": 0, "oom_kill": 0, "oom_group_kill": 0},
                   "identity": {"pid": 2, "start_ticks": "42", "pid_namespace": "pid:[1]"},
                   "forbidden": dict.fromkeys(("network", "provider", "graph", "render", "workload", "subprocess"), 0)}
        record = {"exit": 137, "run": "owned", "invocation": "kill", "case": "partial-payload"}
        following = {"oom": {"oom": 0, "oom_kill": 0, "oom_group_kill": 0}, "docker_oom_killed": False,
                     "identity": copy.deepcopy(witness["identity"])}
        self.assertTrue(validate_death(record, witness, following))
        for field, value in (("ack_emitted", True), ("failpoint", "after-promotion"), ("run", "other"),
                             ("signal", "SIGTERM"), ("status", "passed"), ("forbidden", {})):
            changed = copy.deepcopy(witness)
            changed[field] = value
            with self.subTest(field=field), self.assertRaises(AssertionError):
                validate_death(record, changed, following)
        for field, value in (("oom", {"oom": 0, "oom_kill": 1, "oom_group_kill": 0}),
                             ("docker_oom_killed", True), ("identity", {"pid": 99})):
            changed = copy.deepcopy(following)
            changed[field] = value
            with self.subTest(field=field), self.assertRaises(AssertionError):
                validate_death(record, witness, changed)


if __name__ == "__main__":
    unittest.main()
