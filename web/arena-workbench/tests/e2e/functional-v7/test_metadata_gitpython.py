# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Real GitPython compatibility; run only in a fresh preflighted API sandbox."""
import itertools
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

import api


class GitPythonMetadataTests(unittest.TestCase):
    def test_real_import_and_version_semantics_without_package_subprocesses(self):
        # This must fail before importing any dependency if invoked on the host.
        api.preflight()
        self.assertNotIn("git", sys.modules, "Requires a fresh test interpreter")
        if Path("/pydeps").exists():
            sys.path.insert(0, "/pydeps")
        metadata = api.capture_git_metadata()
        counters = dict.fromkeys(("network", "provider", "graph", "render", "workload", "subprocess"), 0)
        replay = api.MetadataReplay(metadata, counters)
        sys.addaudithook(api.make_audit(counters))
        with mock.patch.object(subprocess, "Popen", api.metadata_popen(replay)):
            import git
        self.assertTrue(git.__version__)
        self.assertTrue(1 <= replay.reads <= 2)
        self.assertEqual(counters["subprocess"], 0)
        version = metadata["stdout"].decode("ascii").rstrip("\n")
        fields = version.split(" ")[2].split(".")[:4]
        expected = tuple(map(int, itertools.takewhile(str.isdigit, fields)))
        # Give each independent semantic check a fresh bounded metadata reader;
        # the real API's single reader still permits only two import-time reads.
        reader = api.MetadataReplay(metadata, counters)
        with mock.patch.object(git.cmd, "safer_popen", api.metadata_popen(reader)):
            command = git.Git()
            self.assertEqual(command.version_info, expected)
            self.assertEqual(command.version_info, expected)  # genuine GitPython cache
            self.assertEqual(command.version(stdout_as_string=False), metadata["stdout"].rstrip(b"\n"))
        self.assertEqual(reader.reads, 2)
        reader = api.MetadataReplay(metadata, counters)
        with mock.patch.object(git.cmd, "safer_popen", api.metadata_popen(reader)):
            self.assertEqual(git.Git().version(), version)
            self.assertEqual(git.Git().version(with_extended_output=True), (0, version, ""))
        self.assertEqual(reader.reads, 2)
        self.assertFalse(any(counters.values()), counters)
        api.write("metadata-gitpython.json", {"passed": True, "gitpython_version": git.__version__,
                                             "git_version": version, "version_info": expected,
                                             "import_metadata_reads": replay.reads,
                                             "forbidden": counters})


if __name__ == "__main__":
    unittest.main()
