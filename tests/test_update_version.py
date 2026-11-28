"""Check GitHub release selection and atomic version updates."""

import base64
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from scripts import update_version
from scripts.common import ROOT
from scripts.upstream import asset_names

CONFIG = json.loads((ROOT / "wheel.json").read_text())


def release(version="0.8.0"):
    return {
        "tag_name": "v" + version,
        "assets": [
            {
                "name": name,
                "browser_download_url": (
                    f"{CONFIG['homepage']}/releases/download/v{version}/{name}"
                ),
            }
            for name in asset_names(CONFIG)
        ],
    }


class UpdateTests(unittest.TestCase):
    def test_updates_only_version_using_github_release_assets(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "wheel.json"
            path.write_text(json.dumps(CONFIG, indent=2) + "\n")
            report = path.with_suffix(".md")
            with patch.object(
                update_version, "latest_release", return_value=release()
            ) as latest:
                self.assertTrue(
                    update_version.update_version(path, "github-token", report)
                )
            latest.assert_called_once_with(
                "hust-open-atom-club/atomgit-cli", "github-token"
            )
            self.assertEqual(
                json.loads(path.read_text()), {**CONFIG, "version": "0.8.0"}
            )
            body = report.read_text()
            self.assertIn(
                "https://github.com/hust-open-atom-club/atomgit-cli/releases/tag/v0.8.0",
                body,
            )
            self.assertIn("`$atomgit-release-upgrade`", body)
            self.assertIn("`.agents/skills/atomgit-release-upgrade/SKILL.md`", body)

    def test_invalid_assets_leave_config_and_report_unchanged(self):
        for fault in ("missing", "duplicate", "http", "no_url", "no_checksums"):
            candidate = release()
            if fault == "missing":
                candidate["assets"].pop(0)
            elif fault == "duplicate":
                candidate["assets"].append(copy.deepcopy(candidate["assets"][0]))
            elif fault == "http":
                candidate["assets"][0]["browser_download_url"] = (
                    "http://example.org/file"
                )
            elif fault == "no_url":
                candidate["assets"][0].pop("browser_download_url")
            else:
                candidate["assets"] = [
                    item
                    for item in candidate["assets"]
                    if item["name"] != "checksums.txt"
                ]
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "wheel.json"
                original = json.dumps(CONFIG)
                path.write_text(original)
                report = path.with_suffix(".md")
                with (
                    patch.object(
                        update_version, "latest_release", return_value=candidate
                    ),
                    self.assertRaises((ValueError, KeyError)),
                ):
                    update_version.update_version(path, report_path=report)
                self.assertEqual(path.read_text(), original)
                self.assertFalse(report.exists())

    def test_no_update_does_not_require_assets_or_rewrite(self):
        for version in ("0.7.4", "0.7.3"):
            with (
                self.subTest(version=version),
                tempfile.TemporaryDirectory() as temporary,
            ):
                path = Path(temporary) / "wheel.json"
                original = json.dumps(CONFIG)
                path.write_text(original)
                with patch.object(
                    update_version,
                    "latest_release",
                    return_value={"tag_name": "v" + version},
                ):
                    self.assertFalse(update_version.update_version(path))
                self.assertEqual(path.read_text(), original)

    def test_api_failure_does_not_rewrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "wheel.json"
            original = json.dumps(CONFIG)
            path.write_text(original)
            with (
                patch.object(
                    update_version, "latest_release", side_effect=TimeoutError
                ),
                self.assertRaises(TimeoutError),
            ):
                update_version.update_version(path)
            self.assertEqual(path.read_text(), original)

    def test_latest_stable_uses_version_order_and_github_release_flags(self):
        values = [release("0.7.4"), release("0.10.0"), release("0.9.0")]
        values += [
            dict(release("8.0.0"), draft=True),
            dict(release("9.0.0"), prerelease=True),
        ]
        values += [
            {"tag_name": tag}
            for tag in ("v1.0.0rc1", "v1.0.0-beta.1", "v01.0.0", "snapshot", "v1.0")
        ]
        with patch.object(update_version, "get_json", return_value=values) as get:
            selected = update_version.latest_release("owner/repo", "github-token")
        self.assertEqual(selected["tag_name"], "v0.10.0")
        get.assert_called_once_with(
            "https://api.github.com/repos/owner/repo/releases?page=1&per_page=100",
            "github-token",
        )

    def test_pagination_is_not_limited_to_first_hundred_releases(self):
        first = [release(f"0.0.{index}") for index in range(100)]
        with patch.object(
            update_version, "get_json", side_effect=[first, [release("0.8.0")]]
        ) as get:
            selected = update_version.latest_release("owner/repo")
        self.assertEqual(selected["tag_name"], "v0.8.0")
        self.assertIn("page=2&", get.call_args.args[0])

    def test_repeated_pages_and_invalid_responses_fail(self):
        first = [release(f"0.0.{index}") for index in range(100)]
        with (
            patch.object(update_version, "get_json", side_effect=[first, first]),
            self.assertRaisesRegex(ValueError, "Repeated"),
        ):
            update_version.latest_release("owner/repo")
        for value in ([], {}, [dict(release(), prerelease=True)]):
            with (
                self.subTest(value=value),
                patch.object(update_version, "get_json", return_value=value),
                self.assertRaises((ValueError, TypeError)),
            ):
                update_version.latest_release("owner/repo")


class OpenUpgradeTests(unittest.TestCase):
    repository = "Noai-oss/ag-cli-py"
    branch = "update-upstream-version"
    api = "https://api.github.com/repos/Noai-oss/ag-cli-py"
    sha = "a" * 40

    def setUp(self):
        self.pr = {
            "number": 5,
            "state": "open",
            "base": {"ref": "main"},
            "head": {
                "ref": self.branch,
                "repo": {"full_name": self.repository},
                "sha": self.sha,
            },
        }
        self.commits = []
        self.comments = []
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.config = Path(self.temporary.name) / "wheel.json"
        self.original = json.dumps({**CONFIG, "version": "0.7.4"})
        self.config.write_text(self.original)
        self.report = self.config.with_suffix(".md")
        self.report.write_text("existing report\n")

    def request(self, url, token):
        self.assertEqual(token, "token")
        self.commits.append(url)
        if url.startswith(f"{self.api}/pulls?"):
            self.assertEqual(
                parse_qs(urlsplit(url).query),
                {
                    "state": ["open"],
                    "base": ["main"],
                    "head": ["Noai-oss:" + self.branch],
                },
            )
            return [] if self.pr is None else [self.pr]
        if url == f"{self.api}/contents/wheel.json?ref={self.sha}":
            return {
                "encoding": "base64",
                "content": base64.b64encode(b'{"version":"0.7.5"}').decode(),
            }
        if url == f"{self.api}/issues/5/comments?per_page=100&page=1":
            return self.comments[:100]
        if url == f"{self.api}/issues/5/comments?per_page=100&page=2":
            return self.comments[100:]
        self.fail(f"Unexpected request: {url}")

    def run_update(self, version):
        with (
            patch.object(
                update_version, "latest_release", return_value=release(version)
            ),
            patch.object(update_version, "get_json", side_effect=self.request),
            patch.object(update_version.urllib.request, "urlopen") as post,
        ):
            post.return_value.__enter__.return_value.status = 201
            changed = update_version.update_version(
                self.config,
                "token",
                self.report,
                packaging_repository=self.repository,
                pr_branch=self.branch,
            )
        return changed, post

    def assert_no_rewrite(self):
        self.assertEqual(self.config.read_text(), self.original)
        self.assertEqual(self.report.read_text(), "existing report\n")

    def test_same_or_older_candidate_does_not_touch_open_pr(self):
        for version in ("0.7.5", "0.7.4"):
            with self.subTest(version=version):
                changed, post = self.run_update(version)
                self.assertFalse(changed)
                post.assert_not_called()
                self.assert_no_rewrite()
        self.assertFalse(any("/comments" in url for url in self.commits))

    def test_newer_candidate_comments_once_without_rewriting(self):
        changed, post = self.run_update("0.7.6")
        self.assertFalse(changed)
        post.assert_called_once()
        request = post.call_args.args[0]
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.full_url, f"{self.api}/issues/5/comments")
        body = json.loads(request.data)["body"]
        self.assertIn("ag-cli-py-upstream-release:v0.7.6", body)
        self.assertIn("This PR still targets v0.7.5", body)
        self.assert_no_rewrite()

        self.comments = [{"body": "unrelated"}] * 100 + [
            {"user": {"login": "github-actions[bot]"}, "body": body}
        ]
        changed, post = self.run_update("0.7.6")
        self.assertFalse(changed)
        post.assert_not_called()
        self.assert_no_rewrite()

    def test_no_open_pr_preserves_version_only_update(self):
        self.pr = None
        changed, post = self.run_update("0.7.6")
        self.assertTrue(changed)
        self.assertEqual(
            json.loads(self.config.read_text()), {**CONFIG, "version": "0.7.6"}
        )
        self.assertIn("atomgit-release-upgrade", self.report.read_text())
        post.assert_not_called()

    def test_unexpected_pr_identity_fails_without_writing(self):
        self.pr["head"]["repo"]["full_name"] = "another-user/ag-cli-py"
        with self.assertRaisesRegex(ValueError, "Unexpected upgrade PR identity"):
            self.run_update("0.7.6")
        self.assert_no_rewrite()
