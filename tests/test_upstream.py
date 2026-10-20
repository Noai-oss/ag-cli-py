"""Test the release naming and HTTP boundary without credentials or network."""

import io
import json
import unittest
import urllib.error
from unittest.mock import patch

from scripts import upstream
from scripts.common import ROOT


class UpstreamTests(unittest.TestCase):
    def test_six_publishable_targets_and_one_checksum_manifest(self):
        config = json.loads((ROOT / "wheel.json").read_text())
        names = upstream.asset_names(config)
        self.assertEqual(len(names), 7)
        self.assertIn("ag_windows_arm64.zip", names)
        # Warehouse excludes this architecture from both Linux tag allowlists.
        self.assertNotIn("ag_linux_loong64.tar.gz", names)
        self.assertIn("checksums.txt", names)

    def test_repository_hosts_and_url_shapes(self):
        self.assertEqual(
            upstream.upstream_repository("https://github.com/owner/repo/"),
            "owner/repo",
        )
        for url in (
            "http://github.com/owner/repo",
            "https://github.com.evil/owner/repo",
            "https://atomgit.com/owner/repo",
            "https://gitcode.com/owner/repo",
            "https://github.com/owner/repo?token=x",
            "https://github.com/owner/repo/tree/main",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                upstream.upstream_repository(url)

    def test_only_stable_three_component_tags_are_accepted(self):
        self.assertEqual(upstream.stable_version("v0.7.4"), "0.7.4")
        for tag in ("0.7.4", "v00.7.4", "v0.7.4rc1", "v0.7.4.post1", "v0.7.4\n", None):
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                upstream.stable_version(tag)

    def test_api_token_is_explicit_and_never_added_to_asset_download(self):
        with patch(
            "scripts.upstream.urllib.request.urlopen", return_value=io.BytesIO(b"[]")
        ) as request:
            self.assertEqual(
                upstream.get_json("https://api.github.com/test", "test-token"), []
            )
            self.assertEqual(
                request.call_args.args[0].get_header("Authorization"),
                "Bearer test-token",
            )
            self.assertEqual(request.call_args.kwargs["timeout"], 30)
            self.assertEqual(
                request.call_args.args[0].get_header("Accept"),
                "application/vnd.github+json",
            )
        with patch(
            "scripts.upstream.urllib.request.urlopen",
            return_value=io.BytesIO(b"archive"),
        ) as request:
            self.assertEqual(upstream.fetch("https://github.com/file"), b"archive")
            self.assertIsNone(request.call_args.args[0].get_header("Authorization"))

    def test_http_failure_is_reported_without_retry(self):
        error = urllib.error.HTTPError(
            "https://github.com/file", 503, "unavailable", {}, None
        )
        with (
            patch(
                "scripts.upstream.urllib.request.urlopen", side_effect=error
            ) as request,
            self.assertRaises(urllib.error.HTTPError),
        ):
            upstream.fetch("https://github.com/file")
        request.assert_called_once()
