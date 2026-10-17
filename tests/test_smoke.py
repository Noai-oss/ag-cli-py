"""Verify the tagged AtomGit version formats and isolated command execution."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.smoke import check_version_json, cli_version, run_cli


class SmokeTests(unittest.TestCase):
    def test_upstream_text_versions(self):
        for output in (
            "ag-cli version v0.7.4\n",
            "ag-cli version v0.7.4 (commit: abc, built: 2026-10-01T00:00:00Z)\n",
        ):
            self.assertEqual(cli_version(output), "0.7.4")
        for output in (
            "ag version v0.7.4",
            "ag-cli v0.7.4",
            "ag-cli version dev",
            "ag-cli version v0.7.4\nerror",
        ):
            with self.subTest(output=output), self.assertRaises(ValueError):
                cli_version(output)

    def test_json_requires_matching_release_and_build_metadata(self):
        info = {
            "version": "v0.7.4",
            "commit": "abc123",
            "buildDate": "2026-10-01T00:00:00Z",
        }
        self.assertEqual(check_version_json(json.dumps(info), "0.7.4"), info)
        for value in (
            [],
            {},
            {**info, "version": "v0.7.3"},
            {**info, "commit": "unknown"},
            {**info, "buildDate": ""},
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                check_version_json(json.dumps(value), "0.7.4")

    def test_cli_isolated_from_user_configuration_and_credentials(self):
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.dict(
                os.environ,
                {
                    "AG_TOKEN": "private",
                    "ATOMGIT_TOKEN": "private",
                    "GITCODE_TOKEN": "private",
                },
            ),
        ):
            work = Path(temporary)
            result = run_cli(
                [
                    sys.executable,
                    "-c",
                    'import os, json; print(json.dumps({key: os.environ.get(key) for key in ["HOME", "AG_TOKEN", "ATOMGIT_TOKEN", "GITCODE_TOKEN"]}))',
                ],
                work,
            )
            self.assertEqual(
                json.loads(result.stdout),
                {
                    "HOME": str(work),
                    "AG_TOKEN": None,
                    "ATOMGIT_TOKEN": None,
                    "GITCODE_TOKEN": None,
                },
            )
            with self.assertRaises(subprocess.CalledProcessError):
                run_cli([sys.executable, "-c", "raise SystemExit(3)"], work)
